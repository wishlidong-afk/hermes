"""Kill a real sandbox capture, then recover under a new process's lease."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import select
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
from unittest.mock import patch

from verify_a2_isolated_replay import AS_OF, REPO, _json, _sha
from verify_a2_runtime_replay import _child, _seed


PHASES = ("after_prepare", "after_schema", "during_write", "after_binding", "after_commit", "cleanup_error")


def _business(root: Path) -> dict:
    from hermes_escape_top.core.data.sqlite_snapshot import sqlite_state_hash
    from hermes_escape_top.core.data.transaction_evidence import business_paths

    result = {}
    for name in sorted(business_paths(AS_OF)):
        path = root / "data" / name
        if not path.exists():
            result[name] = {"availability": "ABSENT"}
            continue
        if path.suffix == ".sqlite":
            with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
                digest = sqlite_state_hash(db)
        else:
            digest = _sha(path)
        result[name] = {"availability": "PRESENT", "digest": digest,
                        "mode": path.stat().st_mode & 0o777}
    return result


def _worker(root: Path, config: Path, mode: str, phase: str) -> None:
    work = root.resolve().parent
    if (mode not in {"capture", "recover"} or phase not in PHASES
            or not work.is_relative_to(Path(tempfile.gettempdir()).resolve())
            or not work.name.startswith("hermes-a2-runtime-replay-")
            or root.resolve() != work / "capture"
            or Path(os.environ.get("HERMES_DATA_DIR", "")).resolve() != root.resolve()
            or config.resolve() != work / "config.json"
            or not (work / "code/hermes_escape_top/pipeline.py").is_file()):
        raise ValueError("worker requires the explicitly created capture crash root")
    attempts = 0

    def deny_network(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise AssertionError("network forbidden in capture crash rehearsal")

    with ExitStack() as stack:
        for name in ("connect", "connect_ex"):
            stack.enter_context(patch.object(socket.socket, name, deny_network))
        stack.enter_context(patch.object(socket, "create_connection", deny_network))
        from hermes_escape_top import pipeline
        from hermes_escape_top.config import load_config
        from hermes_escape_top.core.data import run_transaction as transaction
        from hermes_escape_top.core.safe_io import pipeline_lock

        package = work / "code/hermes_escape_top"
        if Path(pipeline.__file__).resolve().parent != package:
            raise ValueError("crash worker must execute the frozen candidate source")
        assert load_config(config)["ibkr"]["readonly"] is True
        archive = root / "data/archive"
        if mode == "recover":
            checkpoint = json.loads((work / "checkpoint.json").read_bytes())
            restored = False
            with pipeline_lock(path=archive / ".pipeline.lock") as lease:
                recovered = transaction.recover_incomplete_score_run(archive, _lease=lease)
                after = _business(root)
                if checkpoint["status"] == "COMMITTED":
                    from hermes_escape_top.core.data.store import LocalStore
                    from hermes_escape_top.core.reporting.transaction_restore import restore_committed_runtime_inputs

                    record = transaction.load_score_run_transaction(archive, checkpoint["run_id"])
                    restore_committed_runtime_inputs(
                        store=LocalStore(load_config(config)), run_id=record["run_id"],
                        expected_journal_sha256=checkpoint["journal_sha256"],
                        decision_id=record["input_binding"]["decision_id"],
                        input_hash=record["input_binding"]["input_hash"], destination=work / "restored",
                    )
                    restored = (work / "restored/inputs/manifest.json").is_file()
                    after = _business(root)
            _json(work / "recovery.json", {"pid": os.getpid(), "recovered": recovered,
                                         "business": after, "network_attempts": attempts,
                                         "committed_inputs_restored": restored})
            if attempts:
                raise AssertionError("recovery attempted network")
            return

        instant = datetime(2026, 5, 30, 0, 10, tzinfo=timezone.utc)

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

        stack.enter_context(patch.object(pipeline, "datetime", Clock))
        db = stack.enter_context(closing(sqlite3.connect(archive / "hermes_state.sqlite")))
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("CREATE TABLE capture_crash_wal_probe (value TEXT)")
        db.execute("INSERT INTO capture_crash_wal_probe VALUES ('committed before capture')")
        db.commit()
        main = work / "main-only.sqlite"
        shutil.copyfile(archive / "hermes_state.sqlite", main)
        with closing(sqlite3.connect(f"{main.as_uri()}?immutable=1", uri=True)) as frozen:
            only_in_wal = not frozen.execute(
                "SELECT name FROM sqlite_master WHERE name='capture_crash_wal_probe'",
            ).fetchall()
        _json(work / "before.json", {"business": _business(root), "wal_only": only_in_wal})

        def checkpoint():
            record = transaction.pending_score_run_transaction(archive)
            if record is None:
                raise AssertionError("checkpoint requires an active real transaction")
            observation = {"pid": os.getpid(), "phase": phase, "run_id": record["run_id"],
                           "capture_id": record["capture_id"], "status": record["status"],
                           "journal_sha256": _sha(archive / ".score_run_transactions/runs"
                                                  / record["run_id"] / "manifest.json"),
                           "input_binding_present": bool(record.get("input_binding")),
                           "all_evidence_present": all((root / "data" / row["path"]).is_file()
                                                       for row in record["artifacts"]
                                                       if row["role"] == "DECISION_INPUT_EVIDENCE"),
                           "network_attempts": attempts, "business": _business(root),
                           "registered_business_roles": sum(row["role"] == "BUSINESS"
                                                            for row in record["artifacts"]),
                           "evidence_paths": [row["path"] for row in record["artifacts"]
                                              if row["role"] == "DECISION_INPUT_EVIDENCE"]}
            observation["evidence_sha256"] = {
                name: _sha(root / "data" / name) for name in observation["evidence_paths"]
                if (root / "data" / name).is_file()}
            _json(work / "checkpoint.json", observation)
            print(json.dumps({"pid": os.getpid(), "phase": phase}), flush=True)
            if phase == "cleanup_error":
                raise OSError("injected post-commit active cleanup error")
            sys.stdin.read(1)
            raise AssertionError("parent must SIGKILL the checkpointed writer")

        original = pipeline.export_score_run_before_images

        def export(*args, **kwargs):
            if phase == "after_prepare":
                checkpoint()
            return original(*args, **kwargs)

        stack.enter_context(patch.object(pipeline, "export_score_run_before_images", export))
        reader = pipeline.read_reentry_states

        def read_state(*args, **kwargs):
            result = reader(*args, **kwargs)
            if phase == "after_schema":
                checkpoint()
            return result

        stack.enter_context(patch.object(pipeline, "read_reentry_states", read_state))
        persistence_checkpoint = pipeline._persistence_checkpoint

        def observe_write(name):
            persistence_checkpoint(name)
            if phase == "during_write" and name == "unified_state":
                checkpoint()

        stack.enter_context(patch.object(pipeline, "_persistence_checkpoint", observe_write))
        finish = pipeline.RuntimeCapture.finish

        def bind(capture, *args, **kwargs):
            result = finish(capture, *args, **kwargs)
            if phase == "after_binding":
                checkpoint()
            return result

        stack.enter_context(patch.object(pipeline.RuntimeCapture, "finish", bind))
        clear_active = transaction._clear_active

        def clear(path):
            if phase in {"after_commit", "cleanup_error"}:
                checkpoint()
            return clear_active(path)

        stack.enter_context(patch.object(transaction, "_clear_active", clear))
        pipeline.score_pipeline(AS_OF, config_path=config, include_ibkr=False,
                                run_type="scheduled", capture_inputs=True)
        raise AssertionError("writer did not reach its crash checkpoint")


def rehearse(phase: str) -> dict:
    from hermes_escape_top.core.data.manifest import write_manifest
    from hermes_escape_top.core.data.run_transaction import load_score_run_transaction

    with tempfile.TemporaryDirectory(prefix="hermes-a2-runtime-replay-") as temporary:
        work = Path(temporary).resolve()
        seed = _seed(work)
        config = work / "config.json"
        _child(work / "seed", config, "seed")
        root = work / "capture"
        shutil.copytree(work / "seed/data", root / "data")
        archive = root / "data/archive"
        if phase == "after_schema":
            with closing(sqlite3.connect(archive / "reentry_state.sqlite")) as db, db:
                db.execute("DROP TABLE reentry_state")
        write_manifest(root / "data/history", archive / "data_manifest_latest.json")
        environment = {**os.environ, "PYTHONPATH": str(work / "code"),
                       "HERMES_DATA_DIR": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
        command = [sys.executable, str(Path(__file__).resolve()), "--worker", str(root),
                   str(config), "capture", "--phase", phase]
        child = subprocess.Popen(command, cwd=REPO, env=environment, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            assert child.stdout is not None
            if not select.select([child.stdout], [], [], 120)[0]:
                raise AssertionError("capture did not reach its crash checkpoint")
            ready = child.stdout.readline()
            if not ready:
                raise AssertionError("capture exited before its crash checkpoint")
            assert json.loads(ready)["phase"] == phase
            if phase != "cleanup_error":
                os.kill(child.pid, signal.SIGKILL)
            child.wait(timeout=10)
            returncode = child.returncode
        finally:
            if child.poll() is None:
                child.kill()
            _, error = child.communicate(timeout=10)
        expected_returncode = 1 if phase == "cleanup_error" else -signal.SIGKILL
        cleanup_error = "injected post-commit active cleanup error" in error
        if returncode != expected_returncode or (phase == "cleanup_error" and not cleanup_error):
            raise AssertionError(f"capture did not produce its expected interruption: {error}")
        subprocess.run(command[:5] + ["recover", "--phase", phase], cwd=REPO, env=environment,
                       check=True, capture_output=True, text=True, timeout=60)
        before = json.loads((work / "before.json").read_bytes())
        checkpoint = json.loads((work / "checkpoint.json").read_bytes())
        recovery = json.loads((work / "recovery.json").read_bytes())
        record = load_score_run_transaction(archive, checkpoint["run_id"])
        seed_worker = json.loads((work / "seed/worker.json").read_bytes())
        pids = [seed_worker["pid"], checkpoint["pid"], recovery["pid"]]
        matches_before = recovery["business"] == before["business"]
        removed = not (archive / "decision_inputs" / checkpoint["capture_id"]).exists()
        active_absent = not (archive / ".score_run_transactions/active.json").exists()
        attempts = seed_worker["network_attempts"] + checkpoint["network_attempts"] + recovery["network_attempts"]
        matches_checkpoint = recovery["business"] == checkpoint["business"]
        evidence_preserved = bool(checkpoint["evidence_sha256"]) and all(
            (root / "data" / name).is_file() and _sha(root / "data" / name) == digest
            for name, digest in checkpoint["evidence_sha256"].items())
        journal_unchanged = _sha(archive / ".score_run_transactions/runs"
                                 / record["run_id"] / "manifest.json") == checkpoint["journal_sha256"]
        committed_phase = phase in {"after_commit", "cleanup_error"}
        expected_state = (matches_checkpoint and evidence_preserved and journal_unchanged
                          and recovery["committed_inputs_restored"] and record["status"] == "COMMITTED"
                          if committed_phase else
                          matches_before and removed and record["status"] == "RECOVERED_ROLLBACK")
        checkpoint_matches_phase = (
            checkpoint["status"] == ("COMMITTED" if committed_phase else "PENDING")
            and checkpoint["input_binding_present"] == (phase in {"after_binding", "after_commit", "cleanup_error"})
            and checkpoint["registered_business_roles"] == len(before["business"]) == 7)
        passed = (expected_state and checkpoint_matches_phase and active_absent and before["wal_only"]
                  and len(set(pids)) == 3 and attempts == 0)
        return {"status": "PASS" if passed else "FAIL", "phase": phase,
                "scope": "REAL_CAPTURE_INTERRUPTION_AND_LEASED_RECOVERY", "natural_run_evidence": False,
                "interruption": "CLEANUP_EXCEPTION" if phase == "cleanup_error" else "SIGKILL",
                "checkpoint": checkpoint, "before": before, "after": recovery["business"],
                "interrupted_returncode": returncode, "recovery_status": record["status"],
                "injected_cleanup_error_observed": cleanup_error,
                "legacy_schema_fixture": phase == "after_schema",
                "business_changed_at_checkpoint": checkpoint["business"] != before["business"],
                "business_matches_before": matches_before, "business_roles_compared": len(before["business"]),
                "business_matches_checkpoint": matches_checkpoint,
                "capture_evidence_preserved": evidence_preserved,
                "committed_journal_unchanged": journal_unchanged,
                "committed_inputs_restored": recovery["committed_inputs_restored"],
                "registered_business_roles": checkpoint["registered_business_roles"],
                "checkpoint_matches_phase": checkpoint_matches_phase,
                "capture_evidence_removed": removed, "active_absent": active_absent,
                "wal_row_only_in_wal_before_capture": before["wal_only"], "worker_pids": pids,
                "network_attempts": attempts, "seed": seed, "source_commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
                "rehearsal_sha256": _sha(Path(__file__).resolve()),
                "runtime_lock_sha256": _sha(REPO / "requirements.lock"),
                "helper_sha256": _sha(REPO / "scripts/verify_a2_runtime_replay.py"),
                "pipeline_sha256": _sha(work / "code/hermes_escape_top/pipeline.py"),
                "transaction_sha256": _sha(work / "code/hermes_escape_top/core/data/run_transaction.py"),
                "capture_sha256": _sha(work / "code/hermes_escape_top/core/reporting/runtime_capture.py"),
                "deployment": "HOLD", "a2": "OPEN",
                "limitations": ["SIGKILL is not power-loss or filesystem durability evidence",
                                "sandbox scheduled capture; no live run, no broker reads",
                                "recovery process holds a real lease but does not rescore",
                                "SQLite logical rows and file modes, not raw SQLite bytes, are compared"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=PHASES, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", nargs=3, metavar=("ROOT", "CONFIG", "MODE"))
    arguments = parser.parse_args()
    if arguments.worker:
        root, config, mode = arguments.worker
        _worker(Path(root), Path(config), mode, arguments.phase)
    else:
        if arguments.output is None:
            parser.error("rehearsal requires an output path")
        result = rehearse(arguments.phase)
        _json(arguments.output, result)
        print(json.dumps({"status": result["status"], "output": str(arguments.output)}))
        raise SystemExit(0 if result["status"] == "PASS" else 1)
