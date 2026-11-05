"""Real old-writer probes before and after v2 recovery in synthetic R6 roots."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import select
import shutil
import signal
import sqlite3
import subprocess
import sys
from contextlib import ExitStack, closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
BASE = Path("/Users/liweishi/Documents/New project/hermes-a2-a1-boundaries-verified-2026-11-04/verify_boundaries.py")
BASE_SHA = "067572cc7931acf40026a0e044d4c380add3d97ff0561a4d771e97ec21462dd5"
PYTHON = Path("/Users/liweishi/Documents/New project/hermes-a2-integration-2026-11-04/venv/bin/python")
CASES = ("pending", "committed_active", "committed_clean")
AS_OF = "2026-05-29"
SEQUENCES = {
    "pending": ("old_r1", "capture_pending", "old_blocked", "recover", "old_repeat"),
    "committed_active": ("old_r1", "capture_active", "old_blocked", "recover", "old_budget"),
    "committed_clean": ("old_r1", "capture_clean", "old_budget"),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_base(case):
    path = ROOT / "cases" / case / "verify_boundaries.py"
    assert not path.is_symlink() and sha(path) == BASE_SHA
    spec = importlib.util.spec_from_file_location("frozen_boundary", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(base, path, value):
    base.output_json(path, value)


def gate(base):
    base.verify_gate()
    assert sha(Path(__file__)) == json.loads((ROOT / "tool-binding.json").read_text())["driver_sha256"]


def prepare():
    assert not (ROOT / "cases").exists() and sha(BASE) == BASE_SHA
    for case in CASES:
        directory = ROOT / "cases" / case
        directory.mkdir(parents=True)
        shutil.copy2(BASE, directory / BASE.name)
        base = load_base(case)
        base.prepare()
        record = json.loads((directory / "source-binding.json").read_text())
        record["preparation_helper_sha256"] = record["helper_sha256"]
        record["helper_sha256"] = BASE_SHA
        write(base, directory / "source-binding-execution.json", record)
    binding = ROOT / "tool-binding.json"
    with binding.open("x") as stream:
        json.dump(
            {
                "driver_sha256": sha(Path(__file__)),
                "base_sha256": BASE_SHA,
                "synthetic_only": True,
                "source_materials_per_case": 594,
            },
            stream,
            indent=2,
        )
    print("Prepared three new private roots; 594 unchanged source materials each.")


def raw_business(base):
    archive = base.PRIVATE / "r6/shared/hermes_escape_top/data/archive"
    return {name: sha(archive / name) if (archive / name).is_file() else None for name in base.anchor.BUSINESS}


def logical_business(base):
    from hermes_escape_top.core.data.sqlite_snapshot import sqlite_state_hash

    archive = base.PRIVATE / "r6/shared/hermes_escape_top/data/archive"
    result = {}
    for name in base.anchor.BUSINESS:
        path = archive / name
        if not path.exists():
            result[name] = None
            continue
        if path.suffix == ".sqlite":
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
                digest = sqlite_state_hash(connection)
        else:
            digest = sha(path)
        result[name] = {"digest": digest, "mode": path.stat().st_mode & 0o777}
    return result


def worker(case, stage):
    base = load_base(case)
    base.require_os_isolation()
    gate(base)
    base.helper.verify_launch(stage)
    if stage in {"old_r1", "old_repeat"}:
        base.worker(stage)
        return
    attempts = []

    def deny_network(event, _args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            attempts.append(event)
            raise RuntimeError("v2 rollback rehearsal forbids network")

    sys.addaudithook(deny_network)
    from hermes_escape_top import pipeline
    from hermes_escape_top.config import load_config, resolve_path
    from hermes_escape_top.core.data import run_transaction as transaction
    from hermes_escape_top.core.data.decision_revision import DecisionRevisionConflict
    from hermes_escape_top.core.safe_io import pipeline_lock
    from hermes_escape_top.ibkr import executions, positions

    old = stage in {"old_blocked", "old_budget"}
    assert Path(pipeline.__file__).resolve().parent == base.PACKAGES["old" if old else "candidate"]
    positions._SNAPSHOT_PATH = base.PRIVATE / "broker-caches/positions.json"
    executions._CACHE_PATH = base.PRIVATE / "broker-caches/executions.json"
    archive = resolve_path(load_config(), "archive_dir")
    assert archive.resolve() == base.PRIVATE / "r6/shared/hermes_escape_top/data/archive"
    active = archive / ".score_run_transactions/active.json"
    before = raw_business(base)
    active_before = sha(active) if active.exists() else None
    instant = datetime(2026, 6, 3, 7, 20, tzinfo=ZoneInfo("Asia/Shanghai"))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    if old:
        error = None
        try:
            with patch.object(pipeline, "datetime", Clock):
                pipeline.score_pipeline(AS_OF, include_ibkr=False, run_type="scheduled")
        except (transaction.PersistenceRecoveryError, DecisionRevisionConflict) as exc:
            error = {"type": type(exc).__name__, "detail": str(exc)}
        assert error is not None
        if stage == "old_blocked":
            assert error["type"] == "PersistenceRecoveryError" and "V2_REQUIRES_UPGRADED_WRITER" in error["detail"]
        else:
            assert error["type"] == "DecisionRevisionConflict" and "revision budget exhausted" in error["detail"]
        assert before == raw_business(base)
        assert active_before == (sha(active) if active.exists() else None)
        result = {
            "pid": os.getpid(),
            "error": error,
            "raw_business_before": before,
            "raw_business_after": raw_business(base),
            "active_pointer_unchanged": True,
        }
    elif stage == "recover":
        prior = transaction.pending_score_run_transaction(archive)
        assert prior is not None
        journal = archive / f".score_run_transactions/runs/{prior['run_id']}/manifest.json"
        journal_before = sha(journal)
        evidence_before = {
            row["path"]: sha(archive.parent / row["path"])
            for row in prior["artifacts"]
            if row["role"] == "DECISION_INPUT_EVIDENCE" and (archive.parent / row["path"]).exists()
        }
        business_before = logical_business(base)
        with pipeline_lock(path=archive / ".pipeline.lock") as lease:
            recovered = transaction.recover_incomplete_score_run(archive, _lease=lease)
        latest = transaction.load_score_run_transaction(archive, prior["run_id"])
        assert not active.exists()
        if prior["status"] == "PENDING":
            assert recovered is not None and latest["status"] == "RECOVERED_ROLLBACK"
            assert all(not (archive.parent / name).exists() for name in evidence_before)
        else:
            assert prior["status"] == latest["status"] == "COMMITTED" and recovered is None
            assert journal_before == sha(journal)
            assert all(sha(archive.parent / name) == digest for name, digest in evidence_before.items())
            assert business_before == logical_business(base)
        result = {
            "pid": os.getpid(),
            "status_before": prior["status"],
            "status_after": latest["status"],
            "business_before": business_before,
            "business_after": logical_business(base),
            "journal_before_sha256": journal_before,
            "journal_after_sha256": sha(journal),
            "registered_evidence_files": len(evidence_before),
            "active_absent": True,
            "evidence_removed": prior["status"] == "PENDING",
            "evidence_preserved": prior["status"] == "COMMITTED",
        }
    else:
        before_logical = logical_business(base)

        def snapshot():
            record = transaction.pending_score_run_transaction(archive)
            assert record is not None and record["schema_version"] == "hermes-score-run-transaction-v2"
            assert record["input_binding"]
            expected = "PENDING" if stage == "capture_pending" else "COMMITTED"
            assert record["status"] == expected
            latest = json.loads((archive / "audit_log.jsonl").read_text().splitlines()[-1])["payload"]
            assert latest["decision_evidence"]["decision_revision"] == 2
            report = {
                "pid": os.getpid(),
                "stage": stage,
                "status": record["status"],
                "run_id": record["run_id"],
                "decision_evidence": latest["decision_evidence"],
                "business_before": before_logical,
                "business_at_checkpoint": logical_business(base),
                "raw_business": raw_business(base),
                "network_attempts": len(attempts),
                "active_pointer": json.loads(active.read_text()),
            }
            write(base, base.ROOT / (stage + ".json"), report)
            print(json.dumps({"ready": stage, "pid": os.getpid()}), flush=True)
            sys.stdin.read(1)
            raise AssertionError("parent must SIGKILL the checkpointed producer")

        with ExitStack() as stack:
            stack.enter_context(patch.object(pipeline, "datetime", Clock))
            if stage == "capture_pending":
                finish = pipeline.RuntimeCapture.finish

                def finish_and_stop(*args, **kwargs):
                    value = finish(*args, **kwargs)
                    snapshot()
                    return value

                stack.enter_context(patch.object(pipeline.RuntimeCapture, "finish", finish_and_stop))
            elif stage == "capture_active":
                clear = transaction._clear_active

                def clear_and_stop(path):
                    snapshot()
                    return clear(path)

                stack.enter_context(patch.object(transaction, "_clear_active", clear_and_stop))
            payload = pipeline.score_pipeline(AS_OF, include_ibkr=False, run_type="scheduled", capture_inputs=True)
        assert stage == "capture_clean" and not active.exists()
        record = transaction.load_score_run_transaction(archive, payload["persistence"]["run_id"])
        assert record["status"] == "COMMITTED" and record["schema_version"] == "hermes-score-run-transaction-v2"
        assert payload["decision_evidence"]["decision_revision"] == 2
        result = {
            "pid": os.getpid(),
            "status": "COMMITTED",
            "active_absent": True,
            "decision_evidence": payload["decision_evidence"],
            "business_before": before_logical,
            "business_after": logical_business(base),
            "raw_business": raw_business(base),
        }
    assert not attempts and not list((base.PRIVATE / "broker-caches").iterdir())
    result.update(network_attempts=0, broker_cache_files=0)
    write(base, base.ROOT / (stage + ".json"), result)


def launch(base, case, stage):
    package = base.PACKAGES["old" if stage.startswith("old_") else "candidate"]
    pointer = base.PRIVATE / ".launch.json"
    assert not base.PRIVATE.is_symlink()
    if pointer.exists():
        assert not pointer.is_symlink()
        pointer.unlink()
    token = os.urandom(32).hex()
    write(base, pointer, {"parent_pid": os.getpid(), "step": stage, "token": token})
    profile = "(version 1) (allow default) (deny network*) (deny file-write*) "
    for path in (
        base.PRIVATE / "r6/shared/hermes_escape_top/data",
        base.PRIVATE / "tmp",
        base.PRIVATE / "broker-caches",
    ):
        profile += f'(allow file-write* (subpath "{path}")) '
    profile += f'(allow file-write* (literal "{base.ROOT / (stage + ".json")}") (literal "/dev/null")) '
    profile += '(deny file-read* (subpath "/Users/liweishi/.hermes"))'
    environment = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(base.PRIVATE / "home"),
        "TMPDIR": str(base.PRIVATE / "tmp"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(package.parent),
        "HERMES_DATA_DIR": str(package),
        "HERMES_A1_PRIVATE_LAUNCH_TOKEN": token,
    }
    command = ["/usr/bin/sandbox-exec", "-p", profile, str(PYTHON), "-B", __file__, "worker", case, stage]
    child = subprocess.Popen(
        command,
        cwd=base.PRIVATE,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    killed = stage in {"capture_pending", "capture_active"}
    try:
        ready = ""
        if killed:
            assert child.stdout is not None
            if not select.select([child.stdout], [], [], 120)[0]:
                raise AssertionError("producer did not reach checkpoint")
            ready = child.stdout.readline()
            if not ready:
                raise AssertionError("producer exited before checkpoint")
            assert json.loads(ready)["ready"] == stage
            os.kill(child.pid, signal.SIGKILL)
        output, error = child.communicate(timeout=180)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)
    base.output_bytes(base.ROOT / (stage + ".stdout.log"), (ready + output).encode())
    base.output_bytes(base.ROOT / (stage + ".stderr.log"), error.encode())
    assert child.returncode == (-signal.SIGKILL if killed else 0), error[-5000:]
    return json.loads((base.ROOT / (stage + ".json")).read_text())


def run():
    for case in CASES:
        base = load_base(case)
        gate(base)
        for stage in SEQUENCES[case]:
            for suffix in (".json", ".stdout.log", ".stderr.log"):
                target = base.ROOT / (stage + suffix)
                assert not target.exists() and not target.is_symlink()
        reports = {stage: launch(base, case, stage) for stage in SEQUENCES[case]}
        assert len({row["pid"] for row in reports.values()}) == len(reports)
        if case == "pending":
            assert reports["capture_pending"]["business_before"] == reports["recover"]["business_after"]
            assert reports["capture_pending"]["business_at_checkpoint"] != reports["recover"]["business_after"]
            assert reports["old_repeat"]["decision_evidence"]["decision_revision"] == 1
            assert (
                reports["old_repeat"]["decision_evidence"]["decision_id"]
                == reports["old_r1"]["decision_evidence"]["decision_id"]
            )
        elif case == "committed_active":
            assert reports["capture_active"]["business_at_checkpoint"] == reports["recover"]["business_after"]
        gate(base)
        write(
            base,
            base.ROOT / "summary.json",
            {
                "status": "PASS",
                "case": case,
                "synthetic_only": True,
                "stages": list(reports),
                "distinct_processes": len(reports),
                "driver_sha256": sha(Path(__file__)),
                "old_writer_outcome": "POINTER_REFUSAL_THEN_R1_REPEAT"
                if case == "pending"
                else "REVISION_BUDGET_REFUSAL",
                "power_loss_proved": False,
                "live_config_data_proved": False,
                "DEPLOY": "HOLD",
                "A2": "OPEN",
            },
        )
        print(case + ": PASS", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "run", "worker"))
    parser.add_argument("case", nargs="?", choices=CASES)
    parser.add_argument("stage", nargs="?")
    args = parser.parse_args()
    if args.mode == "worker":
        if args.case is None or args.stage not in SEQUENCES[args.case]:
            parser.error("worker requires a declared case and stage")
        worker(args.case, args.stage)
    else:
        if args.case is not None or args.stage is not None:
            parser.error("parent mode takes no worker arguments")
        {"prepare": prepare, "run": run}[args.mode]()
