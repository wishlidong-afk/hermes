"""Sandbox post-commit broker cache failures and independent leased recovery."""
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

from verify_a2_capture_crash import _business
from verify_a2_isolated_replay import AS_OF, REPO, _json, _sha
from verify_a2_runtime_replay import _child, _seed


PHASES = ("positions_error", "executions_error", "receipt_error", "before_publish",
          "after_positions", "after_executions", "after_receipt", "success")
OLD_CACHE = b'{"synthetic_old_cache": true}'


def _auxiliary(root: Path, run_id: str) -> dict:
    receipt = root / "data/archive/broker_cache_publications" / f"{run_id}.json"
    caches = {name: _sha(root / "broker-cache" / f"{name}.json")
              for name in ("positions", "executions")}
    return {"caches": caches, "cache_modes": {name: (root / "broker-cache" / f"{name}.json").stat().st_mode & 0o777
                                             for name in caches},
            "receipt": json.loads(receipt.read_bytes()) if receipt.is_file() else None,
            "receipt_sha256": _sha(receipt) if receipt.is_file() else None,
            "receipt_mode": receipt.stat().st_mode & 0o777 if receipt.is_file() else None,
            "receipt_directory_mode": receipt.parent.stat().st_mode & 0o777 if receipt.parent.is_dir() else None,
            "official_receipt_sha256": _sha(root / "data/archive/run_receipt.json")}


def _worker(root: Path, config: Path, mode: str, phase: str) -> None:
    work = root.resolve().parent
    if (mode not in {"capture", "recover"} or phase not in PHASES
            or not work.is_relative_to(Path(tempfile.gettempdir()).resolve())
            or not work.name.startswith("hermes-a2-runtime-replay-")
            or root.resolve() != work / "capture"
            or Path(os.environ.get("HERMES_DATA_DIR", "")).resolve() != root.resolve()
            or config.resolve() != work / "config.json"
            or not (work / "code/hermes_escape_top/pipeline.py").is_file()):
        raise ValueError("worker requires the explicitly created publication rehearsal root")
    calls = {"positions": 0, "executions": 0}
    attempts = 0

    def deny_network(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise AssertionError("network forbidden in publication rehearsal")

    with ExitStack() as stack:
        for name in ("connect", "connect_ex"):
            stack.enter_context(patch.object(socket.socket, name, deny_network))
        stack.enter_context(patch.object(socket, "create_connection", deny_network))
        from hermes_escape_top import pipeline
        from hermes_escape_top.config import load_config
        from hermes_escape_top.core.data import run_transaction as transaction
        from hermes_escape_top.core.data.store import LocalStore
        from hermes_escape_top.core.reporting.broker_capture import BrokerCapture
        from hermes_escape_top.core.reporting.transaction_restore import restore_committed_runtime_inputs
        from hermes_escape_top.core.safe_io import assert_pipeline_lease, pipeline_lock
        from hermes_escape_top.ibkr import executions, positions

        package = work / "code/hermes_escape_top"
        if Path(pipeline.__file__).resolve().parent != package:
            raise ValueError("publication worker must execute frozen candidate source")
        for name, module in tuple(sys.modules.items()):
            file = getattr(module, "__file__", None)
            if name.startswith("hermes_escape_top") and file and not Path(file).resolve().is_relative_to(package):
                raise ValueError("publication worker imported project code outside frozen package")
        assert load_config(config)["ibkr"]["readonly"] is True
        archive = root / "data/archive"
        for module, attribute, name in ((positions, "_SNAPSHOT_PATH", "positions"),
                                        (executions, "_CACHE_PATH", "executions")):
            stack.enter_context(patch.object(module, attribute, root / "broker-cache" / f"{name}.json"))
        responses = {
            "positions": positions.PositionSnapshot(
                account_id="OFFLINE-SYNTHETIC", net_liq=100000, total_cash=95000,
                unrealized_pnl=0, realized_pnl=0,
                gross_position_value=5000, positions=[positions.PositionRecord("SOXL", "STK", 20, 250, 5000)],
                sync_time="2026-05-29T20:10:00+00:00", source="tws", client_id=991,
            ),
            "executions": executions.ExecutionSnapshot(
                records=[executions.ExecutionRecord("OFFLINE-FILL", "SOXL", "BUY", 2, 250,
                         "2026-05-29T19:00:00+00:00", account="OFFLINE-SYNTHETIC")],
                sync_time="2026-05-29T20:10:00+00:00", source="tws", client_id=1041,
            ),
        }

        def reader(name):
            def read(_config, *, publish_cache=True):
                calls[name] += 1
                if mode == "recover":
                    raise AssertionError("recovery must not reread a broker")
                assert publish_cache is False
                return responses[name]
            return read

        for name, module in (("positions", positions), ("executions", executions)):
            stack.enter_context(patch.object(module, f"read_{name}", reader(name)))
        if mode == "recover":
            checkpoint = json.loads((work / "commit.json").read_bytes())
            before_aux = _auxiliary(root, checkpoint["run_id"])
            with pipeline_lock(path=archive / ".pipeline.lock") as lease:
                recovered = transaction.recover_incomplete_score_run(archive, _lease=lease)
                record = transaction.load_score_run_transaction(archive, checkpoint["run_id"])
                restore_committed_runtime_inputs(
                    store=LocalStore(load_config(config)), run_id=record["run_id"],
                    expected_journal_sha256=checkpoint["journal_sha256"],
                    decision_id=record["input_binding"]["decision_id"],
                    input_hash=record["input_binding"]["input_hash"], destination=work / "restored",
                )
                business = _business(root)
            _json(work / "recovery.json", {"pid": os.getpid(), "recovery": recovered,
                                         "business": business, "reader_calls": calls,
                                         "network_attempts": attempts,
                                         "committed_inputs_restored": (work / "restored/inputs/manifest.json").is_file(),
                                         "auxiliary_unchanged": _auxiliary(root, record["run_id"]) == before_aux})
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
        db.execute("CREATE TABLE publication_wal_probe (value TEXT)")
        db.execute("INSERT INTO publication_wal_probe VALUES ('committed before capture')")
        db.commit()
        shutil.copyfile(archive / "hermes_state.sqlite", work / "main-only.sqlite")
        with closing(sqlite3.connect(f"{(work / 'main-only.sqlite').as_uri()}?immutable=1", uri=True)) as frozen:
            wal_only = not frozen.execute(
                "SELECT name FROM sqlite_master WHERE name='publication_wal_probe'",
            ).fetchall()
        _json(work / "before.json", {"business": _business(root), "wal_only": wal_only})
        failures = []
        publish = BrokerCapture.publish

        def observe_publication(broker, persistence, *, _lease):
            assert_pipeline_lease(_lease, path=archive / ".pipeline.lock")
            record = transaction.load_score_run_transaction(archive, persistence.run_id)
            assert record["status"] == "COMMITTED" and transaction.pending_score_run_transaction(archive) is None
            assert record["capture_id"] == persistence.capture_id
            assert all(path.read_bytes() == OLD_CACHE for path in broker.targets.values())
            journal = archive / ".score_run_transactions/runs" / persistence.run_id / "manifest.json"
            checkpoint = {"pid": os.getpid(), "run_id": persistence.run_id, "reader_calls": dict(calls),
                          "business": _business(root), "journal_sha256": _sha(journal),
                          "evidence_sha256": {row["path"]: _sha(root / "data" / row["path"])
                                              for row in record["artifacts"] if row["role"] == "DECISION_INPUT_EVIDENCE"},
                          "expected_caches": {name: response.to_dict() for name, response in responses.items()},
                          "publication_lease_checked": True,
                          "registered_business_roles": sum(row["role"] == "BUSINESS" for row in record["artifacts"]),
                          "network_attempts": attempts}
            _json(work / "commit.json", checkpoint)

            def stop_at(name):
                if phase != name:
                    return
                _json(work / "interruption.json", {"phase": name, "pid": os.getpid(),
                                                   "network_attempts": attempts, "reader_calls": dict(calls)})
                print(json.dumps({"phase": name}), flush=True)
                sys.stdin.read(1)
                raise AssertionError("parent must SIGKILL the publication checkpoint")

            stop_at("before_publish")
            replace = os.replace

            def replace_with_failure(source, destination):
                for name, target in broker.targets.items():
                    if phase == f"{name}_error" and Path(destination) == target:
                        failures.append(name)
                        raise OSError(f"injected {name} cache replace error")
                if phase == "receipt_error" and Path(destination) == archive / "broker_cache_publications" / f"{persistence.run_id}.json":
                    failures.append("receipt")
                    raise OSError("injected publication receipt replace error")
                result = replace(source, destination)
                if Path(destination) == broker.targets["positions"]:
                    stop_at("after_positions")
                if Path(destination) == broker.targets["executions"]:
                    stop_at("after_executions")
                if Path(destination) == archive / "broker_cache_publications" / f"{persistence.run_id}.json":
                    stop_at("after_receipt")
                return result

            with patch.object(os, "replace", replace_with_failure):
                result = publish(broker, persistence, _lease=_lease)
            _json(work / "publication.json", {"returned_receipt": result, "injected_failures": failures})
            return result

        stack.enter_context(patch.object(BrokerCapture, "publish", observe_publication))
        pipeline.score_pipeline(AS_OF, config_path=config, include_ibkr=True,
                                run_type="scheduled", capture_inputs=True)
        for name, module in tuple(sys.modules.items()):
            file = getattr(module, "__file__", None)
            if name.startswith("hermes_escape_top") and file and not Path(file).resolve().is_relative_to(package):
                raise ValueError("publication worker imported project code outside frozen package")
        if attempts or calls != {"positions": 1, "executions": 1}:
            raise AssertionError("unexpected network or broker read count")


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
        write_manifest(root / "data/history", archive / "data_manifest_latest.json")
        cache = root / "broker-cache"
        cache.mkdir(mode=0o700)
        for name in ("positions", "executions"):
            path = cache / f"{name}.json"
            path.write_bytes(OLD_CACHE)
            path.chmod(0o600)
        official_receipt = archive / "run_receipt.json"
        official_receipt.write_bytes(b'{"synthetic_old_official_receipt": true}')
        official_sha = _sha(official_receipt)
        environment = {**os.environ, "PYTHONPATH": str(work / "code"),
                       "HERMES_DATA_DIR": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
        command = [sys.executable, str(Path(__file__).resolve()), "--worker", str(root),
                   str(config), "capture", "--phase", phase]
        interrupted = phase in {"before_publish", "after_positions", "after_executions", "after_receipt"}
        if interrupted:
            child = subprocess.Popen(command, cwd=REPO, env=environment, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                assert child.stdout is not None
                if not select.select([child.stdout], [], [], 120)[0]:
                    raise AssertionError("publication did not reach the interruption checkpoint")
                ready = child.stdout.readline()
                if not ready or json.loads(ready)["phase"] != phase:
                    raise AssertionError("unexpected publication interruption checkpoint")
                os.kill(child.pid, signal.SIGKILL)
                child.wait(timeout=10)
            finally:
                if child.poll() is None:
                    child.kill()
                output, error = child.communicate(timeout=10)
            writer = subprocess.CompletedProcess(command, child.returncode, output, error)
        else:
            writer = subprocess.run(command, cwd=REPO, env=environment, capture_output=True, text=True, timeout=120)
        if writer.returncode != (-signal.SIGKILL if interrupted else 0):
            raise AssertionError(f"publication writer failed: {writer.stdout}\n{writer.stderr}")
        checkpoint = json.loads((work / "commit.json").read_bytes())
        before = json.loads((work / "before.json").read_bytes())
        publication = ({"returned_receipt": None, "injected_failures": []} if interrupted else
                       json.loads((work / "publication.json").read_bytes()))
        interruption = json.loads((work / "interruption.json").read_bytes()) if interrupted else None
        if interruption and (interruption["pid"] != checkpoint["pid"] or interruption["reader_calls"] != checkpoint["reader_calls"]
                             or interruption["network_attempts"] != checkpoint["network_attempts"]):
            raise AssertionError("publication interruption observation changed")
        subprocess.run(command[:5] + ["recover", "--phase", phase], cwd=REPO, env=environment,
                       check=True, capture_output=True, text=True, timeout=60)
        recovery = json.loads((work / "recovery.json").read_bytes())
        seed_worker = json.loads((work / "seed/worker.json").read_bytes())
        record = load_score_run_transaction(archive, checkpoint["run_id"])
        auxiliary = _auxiliary(root, record["run_id"])
        states = {name: "OLD" if (cache / f"{name}.json").read_bytes() == OLD_CACHE else
                  "NEW" if json.loads((cache / f"{name}.json").read_bytes()) == expected else "UNEXPECTED"
                  for name, expected in checkpoint["expected_caches"].items()}
        receipt = auxiliary["receipt"]
        receipt_matches = bool(receipt and receipt["run_id"] == record["run_id"]
                               and receipt["capture_id"] == record["capture_id"]
                               and receipt["business_status"] == "COMMITTED")
        evidence_preserved = bool(checkpoint["evidence_sha256"]) and all(_sha(root / "data" / path) == sha
                                 for path, sha in checkpoint["evidence_sha256"].items())
        journal_unchanged = _sha(archive / ".score_run_transactions/runs" / record["run_id"]
                                 / "manifest.json") == checkpoint["journal_sha256"]
        pids = [seed_worker["pid"], checkpoint["pid"], recovery["pid"]]
        attempts = seed_worker["network_attempts"] + checkpoint["network_attempts"] + recovery["network_attempts"]
        temporary_files = [str(path.relative_to(root)) for directory in (cache, archive / "broker_cache_publications")
                           for path in directory.glob(".*.tmp")]
        business_matches = recovery["business"] == checkpoint["business"]
        receipt_warning = "Committed broker cache publication receipt unavailable" in writer.stderr
        if phase in {"success", "after_receipt"}:
            expected_auxiliary = (states == {"positions": "NEW", "executions": "NEW"} and receipt_matches
                                  and all(row["status"] == "PUBLISHED" for row in receipt["caches"].values())
                                  and (interrupted or publication["returned_receipt"] == receipt)
                                  and not publication["injected_failures"])
        elif interrupted:
            expected_auxiliary = (states == {"positions": "OLD" if phase == "before_publish" else "NEW",
                                            "executions": "NEW" if phase == "after_executions" else "OLD"}
                                  and receipt is None)
        elif phase == "receipt_error":
            expected_auxiliary = (states == {"positions": "NEW", "executions": "NEW"} and receipt is None
                                  and receipt_warning and publication["injected_failures"] == ["receipt"]
                                  and all(row["status"] == "PUBLISHED" for row in publication["returned_receipt"]["caches"].values()))
        else:
            failed_name = phase.removesuffix("_error")
            expected_auxiliary = (receipt_matches and publication["injected_failures"] == [failed_name]
                                  and publication["returned_receipt"] == receipt
                                  and all(states[name] == ("OLD" if name == failed_name else "NEW")
                                          and receipt["caches"][name]["status"] == ("FAILED" if name == failed_name else "PUBLISHED")
                                          for name in states))
        active_absent = not (archive / ".score_run_transactions/active.json").exists()
        changed_before_publication = checkpoint["business"] != before["business"]
        passed = (record["status"] == "COMMITTED" and business_matches and evidence_preserved and changed_before_publication
                  and journal_unchanged and recovery["committed_inputs_restored"] and active_absent
                  and recovery["recovery"] is None and recovery["auxiliary_unchanged"]
                  and attempts == 0 and len(set(pids)) == 3 and before["wal_only"]
                  and checkpoint["reader_calls"] == {"positions": 1, "executions": 1}
                  and recovery["reader_calls"] == {"positions": 0, "executions": 0}
                  and auxiliary["cache_modes"] == {"positions": 0o600, "executions": 0o600}
                  and auxiliary["receipt_mode"] in (None, 0o644)
                  and auxiliary["receipt_directory_mode"] in (None, 0o700)
                  and checkpoint["publication_lease_checked"] and checkpoint["registered_business_roles"] == 7
                  and not temporary_files and auxiliary["official_receipt_sha256"] == official_sha
                  and expected_auxiliary)
        return {"status": "PASS" if passed else "FAIL", "phase": phase,
                "business_status": record["status"], "business_roles_compared": len(checkpoint["business"]),
                "business_matches_commit": business_matches,
                "business_changed_before_publication": changed_before_publication,
                "journal_unchanged": journal_unchanged, "capture_evidence_preserved": evidence_preserved,
                "committed_inputs_restored": recovery["committed_inputs_restored"], "active_absent": active_absent,
                "recovery": recovery["recovery"], "auxiliary_unchanged_during_recovery": recovery["auxiliary_unchanged"],
                "wal_only_before_capture": before["wal_only"], "reader_calls": checkpoint["reader_calls"],
                "recovery_reader_calls": recovery["reader_calls"], "worker_pids": pids, "network_attempts": attempts,
                "cache_states": states, "receipt": receipt, "receipt_matches_run": receipt_matches,
                "cache_modes": auxiliary["cache_modes"], "receipt_mode": auxiliary["receipt_mode"],
                "receipt_directory_mode": auxiliary["receipt_directory_mode"],
                "registered_business_roles": checkpoint["registered_business_roles"],
                "publication_lease_checked": checkpoint["publication_lease_checked"],
                "returned_receipt": publication["returned_receipt"],
                "receipt_warning_observed": receipt_warning,
                "injected_failures": publication["injected_failures"], "writer_returncode": writer.returncode,
                "interruption_checkpoint": interruption["phase"] if interruption else None,
                "cache_temporary_files": temporary_files, "official_receipt_unchanged": auxiliary["official_receipt_sha256"] == official_sha,
                "seed": seed, "rehearsal_sha256": _sha(Path(__file__).resolve()),
                "runtime_helper_sha256": _sha(REPO / "scripts/verify_a2_runtime_replay.py"),
                "business_helper_sha256": _sha(REPO / "scripts/verify_a2_capture_crash.py"),
                "publisher_sha256": _sha(work / "code/hermes_escape_top/core/reporting/broker_capture.py"),
                "pipeline_sha256": _sha(work / "code/hermes_escape_top/pipeline.py"),
                "runtime_lock_sha256": _sha(REPO / "requirements.lock"),
                "natural_run_evidence": False, "deployment": "HOLD", "a2": "OPEN",
                "limitations": ["Synthetic read boundary; no live IBKR or official daily",
                                "Auxiliary caches and receipts are not an atomic group with the seven business roles",
                                "SIGKILL is not power-loss or filesystem durability evidence",
                                "Recovery does not retry publication; a missing receipt is not cache success evidence"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=PHASES, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", nargs=3, metavar=("ROOT", "CONFIG", "MODE"))
    args = parser.parse_args()
    if args.worker:
        root, config, mode = args.worker
        _worker(Path(root), Path(config), mode, args.phase)
    else:
        if args.output is None:
            parser.error("rehearsal requires an output path")
        result = rehearse(args.phase)
        _json(args.output, result)
        print(json.dumps({"status": result["status"], "output": str(args.output)}))
        raise SystemExit(0 if result["status"] == "PASS" else 1)
