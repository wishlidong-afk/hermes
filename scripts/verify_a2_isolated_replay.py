"""Offline mechanism rehearsal; never captures or reruns an official live run."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import ExitStack, closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "src/hermes_escape_top"
AS_OF = "2026-05-29"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path, value: object, *, sort_keys: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=sort_keys, default=str) + "\n")
    path.chmod(0o600)


def _worker(root: Path, config_path: Path, mode: str, tape_path: Path) -> None:
    from hermes_escape_top import pipeline
    from hermes_escape_top.config import load_config
    from hermes_escape_top.ibkr.executions import ExecutionRecord, ExecutionSnapshot
    from hermes_escape_top.ibkr.positions import PositionRecord, PositionSnapshot

    work = root.resolve().parent
    temporary_root = Path(tempfile.gettempdir()).resolve()
    if (not work.is_relative_to(temporary_root) or not work.name.startswith("hermes-a2-isolated-replay-")
            or root.name not in {"source", "reference", "replay"}
            or config_path.resolve() != work / "config.json"
            or Path(os.environ.get("HERMES_DATA_DIR", "")).resolve() != root.resolve()
            or not tape_path.resolve().is_relative_to(work)):
        raise ValueError("worker requires the explicitly created isolated rehearsal root")
    config = load_config(config_path)
    tape = json.loads(tape_path.read_text()) if mode == "replay" else {}
    calls = {"positions": 0, "executions": 0, "soft_data": 0}
    network_attempts = 0
    actual_soft = pipeline.build_soft_data
    instant = datetime(2026, 5, 29 if mode == "seed" else 30, 0, 10, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    def deny_network(*_args, **_kwargs):
        nonlocal network_attempts
        network_attempts += 1
        raise AssertionError("network forbidden in isolated replay")

    def positions(_config):
        calls["positions"] += 1
        if mode != "replay":
            snap = PositionSnapshot(
                account_id="OFFLINE-SYNTHETIC", net_liq=100000, gross_position_value=5000,
                total_cash=95000, unrealized_pnl=0, realized_pnl=0,
                positions=[PositionRecord("SOXL", "STK", 20, 250, 5000)],
                sync_time="2026-05-29T20:10:00+00:00", source="tws", client_id=991,
            )
            tape["positions"] = snap.to_dict()
        return PositionSnapshot.from_dict(copy.deepcopy(tape["positions"]))

    def executions(_config):
        calls["executions"] += 1
        if mode != "replay":
            snap = ExecutionSnapshot(
                records=[ExecutionRecord("OFFLINE-FILL", "SOXL", "BUY", 2, 250,
                                         "2026-05-29T19:00:00+00:00", account="OFFLINE-SYNTHETIC")],
                sync_time="2026-05-29T20:10:00+00:00", source="tws", client_id=1041,
            )
            tape["executions"] = snap.to_dict()
        return ExecutionSnapshot.from_dict(copy.deepcopy(tape["executions"]))

    def soft(as_of, cfg, store):
        calls["soft_data"] += 1
        if mode != "replay":
            tape["soft_data"] = actual_soft(as_of, cfg, store)
        result = copy.deepcopy(tape["soft_data"])
        result["path"] = str(store.archive_path("soft_adapter_snapshot", as_of))
        return result

    with ExitStack() as stack:
        stack.enter_context(patch.object(pipeline, "datetime", Clock))
        for name in ("connect", "connect_ex"):
            stack.enter_context(patch.object(socket.socket, name, deny_network))
        stack.enter_context(patch.object(socket, "create_connection", deny_network))
        stack.enter_context(patch.object(pipeline, "build_soft_data", soft))
        if mode != "seed":
            stack.enter_context(patch("hermes_escape_top.ibkr.positions.read_positions", positions))
            stack.enter_context(patch("hermes_escape_top.ibkr.executions.read_executions", executions))
        payload = pipeline.score_pipeline(
            "2026-05-28" if mode == "seed" else AS_OF, config_path=config_path,
            include_ibkr=mode != "seed", run_type="manual_rerun" if mode == "seed" else "scheduled",
        )
    if network_attempts:
        raise AssertionError(f"replay attempted network {network_attempts} times")
    if mode == "reference":
        _json(tape_path, tape, sort_keys=False)
    _json(root / "payload.json", payload)
    _json(root / "worker.json", {"pid": os.getpid(), "calls": calls, "network_attempts": network_attempts})
    assert config["ibkr"]["readonly"] is True


def _child(root: Path, config: Path, mode: str, tape: Path) -> dict:
    env = {**os.environ, "HERMES_DATA_DIR": str(root), "PYTHONPATH": str(REPO / "src"),
           "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker", str(root), str(config), mode, str(tape)],
        env=env, cwd=REPO, capture_output=True, text=True, timeout=90,
    )
    if result.returncode:
        raise RuntimeError(f"{mode} worker failed:\n{result.stdout}\n{result.stderr}")
    return json.loads((root / "payload.json").read_text())


def _comparator():
    spec = importlib.util.spec_from_file_location("a2_existing_strict_comparator", REPO / "scripts/compare_pipeline_persistence.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _snapshot(root: Path, payload: dict, sandbox_roots: tuple[Path, ...]) -> dict:
    comparator = _comparator()
    artifacts = {}
    for name in sorted(comparator._business_artifact_names(AS_OF)):
        path = root / "data/archive" / name
        if path.suffix == ".sqlite":
            artifacts[name] = comparator._snapshot_sqlite(path, root)
        elif path.suffix == ".jsonl":
            artifacts[name] = comparator._snapshot_jsonl(path, root)
        else:
            artifacts[name] = comparator._normalize(json.loads(path.read_text()), root)
    result = {"payload": comparator._normalize(payload, root), "artifacts": artifacts}
    # Old rows and taped provenance retain their source paths; use the fixed three sandbox roots.
    for other_root in sandbox_roots:
        result = comparator._normalize(result, other_root)
    return result


def _nonempty_state(business: list[Path]) -> bool:
    for path in business:
        if path.suffix != ".sqlite":
            continue
        with closing(sqlite3.connect(path)) as db:
            tables = [row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )]
            if not any(db.execute('SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0]
                       for table in tables):
                return False
    return True


def _difference_paths(left, right, prefix="$", limit=30) -> list[str]:
    if type(left) is not type(right):
        return [prefix]
    if isinstance(left, dict):
        paths = []
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                paths.append(f"{prefix}.{key}")
            else:
                paths.extend(_difference_paths(left[key], right[key], f"{prefix}.{key}", limit))
            if len(paths) >= limit:
                break
        return paths[:limit]
    if isinstance(left, list):
        if len(left) != len(right):
            return [prefix + ".length"]
        paths = []
        for index, (before, after) in enumerate(zip(left, right, strict=True)):
            paths.extend(_difference_paths(before, after, f"{prefix}[{index}]", limit))
            if len(paths) >= limit:
                break
        return paths[:limit]
    return [prefix] if left != right else []


def rehearse(*, probe_net_liq_change: bool = False) -> dict:
    from hermes_escape_top.config import load_config
    from hermes_escape_top.core.data import run_transaction
    from hermes_escape_top.core.data.manifest import write_manifest
    from hermes_escape_top.core.data.store import LocalStore
    from hermes_escape_top.core.data.transaction_evidence import business_paths
    from hermes_escape_top.core.reporting.decision_inputs import archive_decision_inputs, restore_decision_inputs
    from hermes_escape_top.core.reporting.transaction_restore import restore_committed_before_images
    from hermes_escape_top.core.safe_io import pipeline_lock

    with tempfile.TemporaryDirectory(prefix="hermes-a2-isolated-replay-") as temporary_directory:
        work = Path(temporary_directory).resolve()
        source, reference, replay = (work / name for name in ("source", "reference", "replay"))
        seed = Path(os.environ.get("HERMES_DATA_DIR", str(PACKAGE))) / "data"
        data = source / "data"
        data.mkdir(parents=True)
        for name in ("history", "soft_history", "legacy_history"):
            if (seed / name).exists():
                shutil.copytree(seed / name, data / name)
        config = load_config()
        config["ibkr"]["enabled"] = True
        config["ibkr"]["executions"]["enabled"] = True
        config_path = work / "config.json"
        _json(config_path, config)
        tape = work / "read_returns.json"
        _child(source, config_path, "seed", tape)
        shutil.copytree(data, reference / "data")
        write_manifest(reference / "data/history", reference / "data/archive/data_manifest_latest.json")
        with patch.dict(os.environ, {"HERMES_DATA_DIR": str(source)}):
            store = LocalStore(config)
            archive = store.archive_dir
            business = [data / relative for relative in sorted(business_paths(AS_OF))]
            nonempty = _nonempty_state(business) and bool((archive / "audit_log.jsonl").read_text().strip())
            capture_id = "b" * 32
            bundle = archive / "decision_inputs" / capture_id
            evidence = [bundle / "manifest.json", bundle / "pre_state.json", bundle / "read_returns.json",
                        bundle / "market_manifest.json"]
            evidence += [bundle / "pre_state" / path.relative_to(data) for path in business if path.exists()]
            with pipeline_lock(path=archive / ".pipeline.lock") as lease:
                with run_transaction.score_run_transaction(
                    archive, business, metadata={"as_of": AS_OF, "run_type": "scheduled", "shadow": False},
                    _lease=lease, capture_id=capture_id, evidence_artifacts=evidence,
                ) as txn:
                    pre_state = run_transaction.export_score_run_before_images(txn, _lease=lease)
                    expected = _child(reference, config_path, "reference", tape)
                    for path in business:
                        shutil.copy2(reference / "data" / path.relative_to(data), path)
                    _json(evidence[1], pre_state)
                    shutil.copy2(tape, evidence[2])
                    shutil.copy2(reference / "data/archive/data_manifest_latest.json", evidence[3])
                    binding = {"run_id": txn.run_id, "capture_id": capture_id, "as_of": AS_OF,
                               "decision_id": expected["decision_evidence"]["decision_id"],
                               "input_hash": expected["input_hash"]}
                    _json(evidence[0], {"schema_version": "hermes-in-run-input-binding-v1",
                                       "capture_mode": "IN_RUN_CAPTURE", "binding": binding,
                                       "files": [{"path": path.relative_to(data).as_posix(), "sha256": _sha(path)}
                                                 for path in evidence[1:]]})
                    run_transaction.bind_score_run_inputs(
                        txn, manifest_path=evidence[0], expected_manifest_sha256=_sha(evidence[0]),
                        decision_id=binding["decision_id"], input_hash=binding["input_hash"], _lease=lease,
                    )
            journal = archive / f".score_run_transactions/runs/{txn.run_id}/manifest.json"
            before = {path: _sha(path) for path in data.rglob("*") if path.is_file()}
            restored = restore_committed_before_images(
                store=store, run_id=txn.run_id, expected_journal_sha256=_sha(journal),
                decision_id=binding["decision_id"], input_hash=binding["input_hash"], destination=replay / "data",
            )
        with patch.dict(os.environ, {"HERMES_DATA_DIR": str(reference)}):
            inputs = archive_decision_inputs(
                expected, config, store=LocalStore(config), package_root=PACKAGE, destination=work / "input_bundle",
            )
        frozen = restore_decision_inputs(
            Path(inputs["manifest_path"]), expected_manifest_sha256=inputs["manifest_sha256"],
            decision_id=inputs["decision_id"], destination=work / "restored_inputs", package_root=PACKAGE,
        )
        shutil.copytree(frozen / "history", restored / "history")
        shutil.copy2(evidence[3], restored / "archive/data_manifest_latest.json")
        replay_tape = evidence[2]
        if probe_net_liq_change:
            changed = json.loads(replay_tape.read_text())
            changed["positions"]["net_liq"] += 1000
            replay_tape = work / "negative_probe_returns.json"
            _json(replay_tape, changed, sort_keys=False)
        actual = _child(replay, config_path, "replay", replay_tape)
        comparator = _comparator()
        roots = (source, reference, replay)
        expected_snapshot, actual_snapshot = _snapshot(reference, expected, roots), _snapshot(replay, actual, roots)
        differences = comparator._differences(expected_snapshot, actual_snapshot)
        workers = [json.loads((root / "worker.json").read_text()) for root in (source, reference, replay)]
        replay_journal = replay / "data/archive/.score_run_transactions/runs" / actual["persistence"]["run_id"] / "manifest.json"
        result = {
            "scope": "ISOLATED_MECHANISM_REHEARSAL_NOT_PRODUCTION_CAPTURE", "production_capture": False,
            "negative_probe": "NET_LIQ_CHANGED_BY_1000" if probe_net_liq_change else None,
            "status": "PASS" if not differences and nonempty else "FAIL", "as_of": AS_OF,
            "nonempty_pre_state": nonempty, "artifacts_compared": 7, "strict_differences": differences,
            "strict_difference_paths": _difference_paths(expected_snapshot, actual_snapshot),
            "input_hash_equal": actual["input_hash"] == expected["input_hash"],
            "reader_calls": workers[-1]["calls"], "worker_pids": [worker["pid"] for worker in workers],
            "network_attempts": sum(worker["network_attempts"] for worker in workers),
            "source_unchanged": {path: _sha(path) for path in data.rglob("*") if path.is_file()} == before,
            "replay_transaction_status": json.loads(replay_journal.read_text())["status"],
            "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
            "rehearsal_sha256": _sha(Path(__file__).resolve()),
            "runtime_lock_sha256": _sha(REPO / "requirements.lock"),
            "python": comparator._python_evidence(sys.executable),
            "source": comparator._tree_fingerprint(
                REPO, relative_roots=("src/hermes_escape_top", "scripts/verify_a2_isolated_replay.py", "requirements.lock"),
                excluded_prefixes=("src/hermes_escape_top/data",),
            ),
            "input_manifest_sha256": inputs["manifest_sha256"],
            "committed_journal_sha256": _sha(journal),
            "normalized_reference_sha256": comparator._hash(expected_snapshot),
            "normalized_replay_sha256": comparator._hash(actual_snapshot),
            "normalization": {"contract": "existing strict comparator", "temporary_roots": 3,
                              "additional_ignored_fields": [], "scoring_clock": "2026-05-30T00:10:00+00:00"},
            "sandbox_config_overrides": {"ibkr.enabled": True, "ibkr.executions.enabled": True},
            "execution_sync_status": actual["execution_sync"]["status"],
            "comparator_sha256": _sha(REPO / "scripts/compare_pipeline_persistence.py"),
            "consumer_sha256": _sha(PACKAGE / "core/reporting/transaction_restore.py"),
            "limitations": ["v2 producer is a sandbox fixture, not a production pipeline hook",
                            "input bundle is RETROSPECTIVE_AS_OF_MATCH, not proof of in-run consumption",
                            "synthetic broker returns, no live IBKR or natural-run evidence",
                            "no source/runtime archive or A1 release/migration proof"],
        }
        if not all((result["input_hash_equal"], result["source_unchanged"], nonempty,
                    result["reader_calls"] == {"positions": 1, "executions": 1, "soft_data": 1},
                    result["network_attempts"] == 0, result["replay_transaction_status"] == "COMMITTED")):
            result["status"] = "FAIL"
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--probe-net-liq-change", action="store_true", help="negative control; expect FAIL")
    parser.add_argument("--worker", nargs=4, metavar=("ROOT", "CONFIG", "MODE", "TAPE"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        root, config, mode, tape = args.worker
        if mode not in {"seed", "reference", "replay"}:
            parser.error("invalid worker mode")
        _worker(Path(root), Path(config), mode, Path(tape))
        return 0
    if args.output is not None:
        roots = (Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve())
        if (args.output.exists() or args.output.is_symlink()
                or not any(args.output.resolve().is_relative_to(root) for root in roots)):
            parser.error("output must be a new file under a temporary root")
    result = rehearse(probe_net_liq_change=args.probe_net_liq_change)
    if args.output is not None:
        _json(args.output, result)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
