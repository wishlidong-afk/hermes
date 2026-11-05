"""Sandbox-only replay of a real ON capture; no live entry points or network."""
from __future__ import annotations

import argparse
import copy
import csv
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
from typing import Any
from unittest.mock import patch

from verify_a2_isolated_replay import (
    AS_OF, PACKAGE, REPO, _comparator, _difference_paths, _json, _nonempty_state, _sha, _snapshot,
)


def _worker(root: Path, config_path: Path, mode: str, *, probe_net_liq_change: bool = False,
            confirmation_tranche: str | None = None, probe_execution_sell: bool = False,
            probe_input_change: str | None = None, capture_replay: bool = False,
            external_legacy: bool = False) -> None:
    work = root.resolve().parent.parent if external_legacy else root.resolve().parent
    if (mode not in {"seed", "capture", "replay"} or (probe_net_liq_change and mode != "replay")
            or (capture_replay and mode != "replay")
            or confirmation_tranche not in {None, "T1", "T2"}
            or (probe_execution_sell and (mode != "replay" or not confirmation_tranche))
            or probe_input_change not in {None, "history", "soft", "state"}
            or (probe_input_change and mode != "replay")
            or sum(bool(value) for value in (
                probe_net_liq_change, probe_execution_sell, probe_input_change)) > 1
            or not work.is_relative_to(Path(tempfile.gettempdir()).resolve())
            or not work.name.startswith("hermes-a2-runtime-replay-")
            or root.resolve() != (work / mode / "runtime" if external_legacy else work / mode)
            or Path(os.environ.get("HERMES_DATA_DIR", "")).resolve() != root.resolve()
            or config_path.resolve() != (root / "config.json" if mode == "replay" else work / "config.json")
            or not (work / "code/hermes_escape_top/pipeline.py").is_file()):
        raise ValueError("worker requires the explicitly created runtime rehearsal root")
    network_attempts = 0

    def deny_network(*_args, **_kwargs):
        nonlocal network_attempts
        network_attempts += 1
        raise AssertionError("network forbidden in runtime replay")

    calls = {"positions": 0, "executions": 0, "soft_data": 0}
    input_change = None
    instant = datetime(2026, 5, 29 if mode == "seed" else 30, 0, 10, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    with ExitStack() as stack:
        for name in ("connect", "connect_ex"):
            stack.enter_context(patch.object(socket.socket, name, deny_network))
        stack.enter_context(patch.object(socket, "create_connection", deny_network))
        from hermes_escape_top import pipeline
        from hermes_escape_top.config import load_config
        from hermes_escape_top.core.data.store import safe_symbol
        from hermes_escape_top.ibkr import executions, positions

        expected_package = (root / "package" if mode == "replay" else work / "code/hermes_escape_top")
        if Path(pipeline.__file__).resolve().parent != expected_package:
            raise ValueError("worker must execute the frozen candidate source")
        stack.enter_context(patch.object(pipeline, "datetime", Clock))
        stack.enter_context(patch.object(positions, "_SNAPSHOT_PATH", root / "broker-cache/positions.json"))
        stack.enter_context(patch.object(executions, "_CACHE_PATH", root / "broker-cache/executions.json"))
        frozen = root / "inputs"
        tape = json.loads((frozen / "broker.json").read_bytes()) if mode == "replay" else None

        def read_positions(_config, *, publish_cache=True):
            calls["positions"] += 1
            if mode == "replay":
                assert publish_cache is not capture_replay
                value = copy.deepcopy(tape["reads"]["positions"]["snapshot"])
                if probe_net_liq_change:
                    value["net_liq"] += 1000
                return positions.PositionSnapshot.from_dict(value)
            assert publish_cache is False
            return positions.PositionSnapshot(
                account_id="OFFLINE-SYNTHETIC", net_liq=100000, gross_position_value=5000,
                total_cash=95000, unrealized_pnl=0, realized_pnl=0,
                positions=[positions.PositionRecord("SOXL", "STK", 20, 250, 5000)],
                sync_time="2026-05-29T20:10:00+00:00", source="tws", client_id=991,
            )

        def read_executions(_config, *, publish_cache=True):
            calls["executions"] += 1
            if mode == "replay":
                assert publish_cache is not capture_replay
                value = copy.deepcopy(tape["reads"]["executions"]["snapshot"])
                if probe_execution_sell:
                    value["records"][0]["side"] = "SELL"
                return executions.ExecutionSnapshot.from_dict(value)
            assert publish_cache is False
            return executions.ExecutionSnapshot(
                records=[executions.ExecutionRecord("OFFLINE-FILL", "SOXL", "BUY", 2, 250,
                         "2026-05-29T19:00:00+00:00", account="OFFLINE-SYNTHETIC")],
                sync_time="2026-05-29T20:10:00+00:00", source="tws", client_id=1041,
            )

        if mode != "seed":
            stack.enter_context(patch.object(positions, "read_positions", read_positions))
            stack.enter_context(patch.object(executions, "read_executions", read_executions))
        if mode == "replay":
            saved_soft = json.loads((frozen / "soft.json").read_bytes())
            manifest = json.loads((frozen / "manifest.json").read_bytes())
            for symbol, row in manifest["histories"].items():
                paths = {"primary": root / "data/history" / f"{safe_symbol(symbol)}.csv",
                         "legacy": (root.parent / "data/history" if external_legacy
                                    else root / "data/history_legacy") / f"{safe_symbol(symbol)}.csv"}
                selected = ("primary" if paths["primary"].is_file()
                            else "legacy" if paths["legacy"].is_file() else "missing")
                if row["selected"] != selected or selected == "missing":
                    raise ValueError("restored history selection mismatch")
                for role, path in paths.items():
                    present = row[role]["availability"] == "PRESENT"
                    if (path.is_symlink() or path.is_file() != present
                            or (present and _sha(path) != row[role]["sha256"])):
                        raise ValueError("restored history material mismatch")

            def soft(as_of, config, store):
                nonlocal input_change
                if as_of != AS_OF or config != json.loads((frozen / "config.json").read_bytes()):
                    raise ValueError("frozen soft read binding mismatch")
                calls["soft_data"] += 1
                result = copy.deepcopy(saved_soft["value"])
                result["records"] = {key: result["records"][key] for key in saved_soft["record_order"]}
                orders = saved_soft["record_field_order"]
                if set(orders) != set(result["records"]):
                    raise ValueError("frozen soft field order binding mismatch")
                for key, row in result["records"].items():
                    fields = row.get("fields", {})
                    if set(orders[key]) != set(fields) or len(orders[key]) != len(fields):
                        raise ValueError("frozen soft field order binding mismatch")
                    row["fields"] = {field: fields[field] for field in orders[key]}
                if probe_input_change == "soft":
                    fields = result["records"]["dollar"]["fields"]
                    previous = fields["dollar_broad_pctl"]
                    if previous is None or float(previous) >= 50:
                        raise ValueError("soft probe requires a low observed dollar percentile")
                    fields["dollar_broad_pctl"] = 99.0
                    input_change = {"kind": "soft", "field": "dollar.fields.dollar_broad_pctl",
                                    "before": previous, "after": fields["dollar_broad_pctl"]}
                return result

            stack.enter_context(patch.object(pipeline, "build_soft_data", soft))
        # Keep a committed WAL frame open throughout the actual producer transaction.
        if mode == "capture":
            connection = stack.enter_context(closing(sqlite3.connect(root / "data/archive/hermes_state.sqlite")))
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA wal_autocheckpoint=0")
            connection.execute("CREATE TABLE runtime_wal_probe (value TEXT)")
            connection.execute("INSERT INTO runtime_wal_probe VALUES ('committed before capture')")
            connection.commit()
            if Path(str(root / "data/archive/hermes_state.sqlite") + "-wal").stat().st_size <= 0:
                raise AssertionError("producer must have a real committed WAL frame")
        if probe_input_change == "history":
            path = root / "data/history/SOXL.csv"
            if manifest["histories"]["SOXL"]["selected"] == "legacy":
                path = (root.parent / "data/history" if external_legacy
                        else root / "data/history_legacy") / "SOXL.csv"
            before_sha = _sha(path)
            with path.open(newline="") as file:
                reader = csv.DictReader(file)
                columns, rows = reader.fieldnames, list(reader)
            matching = [row for row in rows if row["Date"] == AS_OF]
            if len(matching) != 1:
                raise ValueError("history probe requires exactly one decision-date bar")
            row = matching[0]
            before_bar = {field: float(row[field]) for field in ("Open", "High", "Low", "Close")}
            after_bar = {field: value * 1.15 for field, value in before_bar.items()}
            row.update({field: str(value) for field, value in after_bar.items()})
            with path.open("w", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=columns, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
            input_change = {"kind": "history", "path": path.relative_to(root.parent if external_legacy else root).as_posix(), "as_of": AS_OF,
                            "before": before_bar, "after": after_bar,
                            "before_sha256": before_sha, "after_sha256": _sha(path)}
        if probe_input_change == "state":
            from hermes_escape_top.core.safe_io import pipeline_lock

            archive = root / "data/archive"
            path = archive / "reentry_state.sqlite"
            before_sha = _sha(path)
            with pipeline_lock(path=archive / ".pipeline.lock"), closing(sqlite3.connect(path)) as db, db:
                row = db.execute("SELECT t1_active FROM reentry_state WHERE symbol='SOXL'").fetchone()
                if row is None or row[0] not in (0, 1):
                    raise ValueError("state probe requires an existing boolean SOXL tranche flag")
                previous, changed = bool(row[0]), not bool(row[0])
                db.execute("UPDATE reentry_state SET t1_active=? WHERE symbol='SOXL'", (int(changed),))
            input_change = {"kind": "state", "path": "data/archive/reentry_state.sqlite",
                            "field": "reentry_state.SOXL.t1_active", "before": previous, "after": changed,
                            "before_sha256": before_sha, "after_sha256": _sha(path)}
        payload = pipeline.score_pipeline(
            "2026-05-28" if mode == "seed" else AS_OF, config_path=config_path,
            include_ibkr=mode != "seed", run_type="manual_rerun" if mode == "seed" else "scheduled",
            capture_inputs=mode == "capture" or capture_replay,
        )
        if mode == "seed" and confirmation_tranche == "T2":
            from hermes_escape_top.core.data.state_store import record_execution_confirmation
            from hermes_escape_top.core.reentry.plan import ReentryPlan
            from hermes_escape_top.core.reentry.store import ReentryState, write_reentry_snapshot
            from hermes_escape_top.core.safe_io import pipeline_lock

            archive = root / "data/archive"
            with pipeline_lock(path=archive / ".pipeline.lock"):
                record_execution_confirmation(
                    archive / "hermes_state.sqlite", symbol="SOXL", tranche="T1",
                    source="offline_seed_manual_confirmation", confirmed_at="2026-05-20T20:00:00+00:00",
                )
                write_reentry_snapshot(
                    archive / "reentry_state.sqlite", "2026-05-28",
                    {"SOXL": ReentryPlan(**payload["reentry"]["SOXL"])},
                    {"SOXL": ReentryState("SOXL", t1_active=True, last_tranche="T1",
                                           updated_at="2026-05-20T20:00:00+00:00")},
                )
        assert load_config(config_path)["ibkr"]["readonly"] is True
        for name, module in tuple(sys.modules.items()):
            file = getattr(module, "__file__", None)
            if name.startswith("hermes_escape_top") and file and not Path(file).resolve().is_relative_to(expected_package):
                raise ValueError("worker imported project code outside the frozen package")
    if network_attempts:
        raise AssertionError("network was attempted")
    _json(root / "payload.json", payload)
    _json(root / "worker.json", {"pid": os.getpid(), "calls": calls,
                               "network_attempts": network_attempts, "package": str(expected_package),
                               "input_change": input_change})


def _child(root: Path, config: Path, mode: str, *, probe_net_liq_change: bool = False,
           confirmation_tranche: str | None = None, probe_execution_sell: bool = False,
           probe_input_change: str | None = None, capture_replay: bool = False,
           external_legacy: bool = False) -> dict:
    work = root.parent.parent if external_legacy else root.parent
    python_path = root / "import" if mode == "replay" else work / "code"
    if mode == "replay":
        python_path.mkdir()
        (python_path / "hermes_escape_top").symlink_to(root / "package", target_is_directory=True)
        if capture_replay:
            shutil.copy2(root / "inputs/source/requirements.lock", root / "requirements.lock")
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", str(root), str(config), mode]
    if probe_net_liq_change:
        command.append("--probe-net-liq-change")
    if confirmation_tranche:
        command.extend(["--confirmation-tranche", confirmation_tranche])
    if probe_execution_sell:
        command.append("--probe-execution-sell")
    if probe_input_change:
        command.extend(["--probe-input-change", probe_input_change])
    if capture_replay:
        command.append("--capture-replay")
    if external_legacy:
        command.append("--external-legacy")
    result = subprocess.run(
        command,
        cwd=REPO, env={**os.environ, "HERMES_DATA_DIR": str(root), "PYTHONPATH": str(python_path),
                       "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=120,
    )
    if result.returncode:
        raise RuntimeError(f"{mode} worker failed:\n{result.stdout}\n{result.stderr}")
    return json.loads((root / "payload.json").read_bytes())


def _seed(work: Path, confirmation_tranche: str | None = None, *, selected_legacy: bool = False,
          external_legacy: bool = False) -> dict:
    from hermes_escape_top.config import load_config

    source = work / ("seed/runtime/data" if external_legacy else "seed/data")
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "src/hermes_escape_top/data"], cwd=REPO,
    ).decode().split("\0")
    files = {path: REPO / path for path in paths if path and "/archive/" not in path}
    for path in (PACKAGE / "tests/fixtures/data").rglob("*"):
        if path.is_file():
            relative = path.relative_to(PACKAGE / "tests/fixtures/data")
            files["src/hermes_escape_top/data/" + relative.as_posix()] = path
    seed_manifest = []
    for name, path in sorted(files.items()):
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(REPO):
            raise ValueError("seed must be a regular repository fixture")
        relative = Path(name).relative_to("src/hermes_escape_top/data")
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        seed_manifest.append({"path": relative.as_posix(), "sha256": _sha(target),
                              "source": str(path), "role": "TRACKED_OR_TEST_FIXTURE"})
    package = work / "code/hermes_escape_top"
    for path in PACKAGE.rglob("*.py"):
        relative = path.relative_to(PACKAGE)
        if "tests" not in relative.parts:
            if path.is_symlink() or not path.resolve(strict=True).is_relative_to(REPO):
                raise ValueError("candidate source must be a regular repository file")
            target = package / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    for relative in ("governance/approved_live_config.json", "VERSION"):
        path = PACKAGE / relative
        if path.is_file():
            target = package / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    shutil.copy2(REPO / "requirements.lock", work / "code/requirements.lock")
    config = load_config()
    config["ibkr"]["enabled"] = True
    config["ibkr"]["executions"]["enabled"] = True
    if selected_legacy:
        config["paths"]["legacy_history_dir"] = "data/history_legacy"
    _json(work / "config.json", config)
    if confirmation_tranche:
        import numpy as np
        import pandas as pd

        index = pd.bdate_range(end=AS_OF, periods=320)
        steps = np.arange(len(index))
        phase = (steps - steps[-1]) * 2 * np.pi / 9 + np.pi / 2
        for name in ("SOXL", "SOXX", "QQQ", "SPY", "SMH", "_SOX", "FNGU", "FNGS"):
            slope, amplitude = (0.06, 0.6) if name == "SOXX" else (0.12, 1.2)
            close = 80 + slope * steps + amplitude * np.sin(phase)
            frame = pd.DataFrame({"Open": close * .998, "High": close * 1.01,
                                  "Low": close * .985, "Close": close, "Volume": 1000000}, index=index)
            target = source / "history" / f"{name}.csv"
            frame.to_csv(target, index_label="Date")
            row = next(item for item in seed_manifest if item["path"] == f"history/{name}.csv")
            row.update(sha256=_sha(target), source="SYNTHETIC_TREND_PLUS_NINE_SESSION_OSCILLATION",
                       role="SYNTHETIC_CONFIRMATION_MARKET")
    if selected_legacy or external_legacy:
        legacy = work / "seed/data/history/SOXL.csv" if external_legacy else source / "history_legacy/SOXL.csv"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        if legacy.exists():
            raise ValueError("selected legacy fixture must not overwrite an existing history")
        (source / "history/SOXL.csv").rename(legacy)
        row = next(item for item in seed_manifest if item["path"] == "history/SOXL.csv")
        row.update(path="history_legacy/SOXL.csv", role="SELECTED_LEGACY_FIXTURE")
        if external_legacy:
            for entry in seed_manifest:
                entry["path"] = "runtime/data/" + entry["path"]
            row.update(path="data/history/SOXL.csv", role="DEFAULT_EXTERNAL_LEGACY_FIXTURE")
    return {"files": seed_manifest, "config_sha256": _sha(work / "config.json")}


def _tree(root: Path) -> dict:
    return {path.relative_to(root).as_posix(): (_sha(path), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def rehearse_runtime(*, probe_net_liq_change: bool = False, confirmation_tranche: str | None = None,
                     probe_execution_sell: bool = False, probe_input_change: str | None = None,
                     capture_replay: bool = False, selected_legacy: bool = False,
                     external_legacy: bool = False) -> dict:
    from hermes_escape_top.config import load_config
    from hermes_escape_top.core.data.manifest import write_manifest
    from hermes_escape_top.core.data.state_store import latest_execution_confirmations
    from hermes_escape_top.core.data.store import LocalStore
    from hermes_escape_top.core.data.transaction_evidence import business_paths
    from hermes_escape_top.core.reporting.transaction_restore import restore_committed_runtime_inputs

    with tempfile.TemporaryDirectory(prefix="hermes-a2-runtime-replay-") as temporary:
        work = Path(temporary).resolve()
        seed, source, replay = (work / name / "runtime" if external_legacy else work / name
                                for name in ("seed", "capture", "replay"))
        seed_binding = _seed(work, confirmation_tranche, selected_legacy=selected_legacy,
                             external_legacy=external_legacy)
        config = work / "config.json"
        _child(seed, config, "seed", confirmation_tranche=confirmation_tranche, external_legacy=external_legacy)
        shutil.copytree(seed / "data", source / "data")
        if external_legacy:
            shutil.copytree(seed.parent / "data/history", source.parent / "data/history")
        write_manifest(source / "data/history", source / "data/archive/data_manifest_latest.json")
        expected = _child(source, config, "capture", confirmation_tranche=confirmation_tranche,
                          external_legacy=external_legacy)
        archive = source / "data/archive"
        run_id = expected["persistence"]["run_id"]
        journal = archive / f".score_run_transactions/runs/{run_id}/manifest.json"
        journal_sha = _sha(journal)
        record = json.loads(journal.read_bytes())
        # Deliberately poison current CSVs after capture. The consumer must not use them.
        (source / "data/history/MSTR.csv").write_text("Date,Close\n2026-05-29,1\n")
        (source / "data/soft_history/dollar.csv").write_text("date,value\n2026-05-29,999\n")
        if selected_legacy or external_legacy:
            legacy_source = (source.parent / "data/history" if external_legacy
                             else source / "data/history_legacy") / "SOXL.csv"
            for path in (source / "data/history/SOXL.csv", legacy_source):
                path.write_text("Date,Close\n2026-05-29,1\n")
        before = _tree(source.parent if external_legacy else source)
        with patch.dict(os.environ, {"HERMES_DATA_DIR": str(source)}):
            restore_committed_runtime_inputs(
                store=LocalStore(load_config(config)), run_id=run_id, expected_journal_sha256=journal_sha,
                decision_id=expected["decision_evidence"]["decision_id"], input_hash=expected["input_hash"],
                destination=replay.parent if external_legacy else replay,
                external_legacy_layout=external_legacy,
            )
        history_selection: dict[str, Any] | None = None
        if selected_legacy or external_legacy:
            bundle = archive / "decision_inputs" / record["capture_id"]
            captured = json.loads((bundle / "manifest.json").read_bytes())["histories"]
            restored_histories = json.loads((replay / "inputs/manifest.json").read_bytes())["histories"]
            legacy_restored = (replay.parent / "data/history" if external_legacy
                               else replay / "data/history_legacy") / "SOXL.csv"
            history_selection = {
                "capture": {symbol: row["selected"] for symbol, row in captured.items()},
                "restored": {symbol: row["selected"] for symbol, row in restored_histories.items()},
                "recaptured": None,
                "legacy_bytes_match": _sha(bundle / "market/legacy/SOXL.csv")
                                      == _sha(legacy_restored),
                "primary_absent": not (replay / "data/history/SOXL.csv").exists(),
                "source_legacy_changed_after_capture": _sha(legacy_source)
                                                       != _sha(bundle / "market/legacy/SOXL.csv"),
                "sandbox_legacy_history_dir": "../data/history" if external_legacy else "data/history_legacy",
            }
            if external_legacy:
                history_selection.update(
                    config_bytes_unchanged=_sha(replay / "config.json") == _sha(config),
                    legacy_inside_private_container=legacy_restored.resolve().is_relative_to(replay.parent),
                )
        with closing(sqlite3.connect(replay / "data/archive/hermes_state.sqlite")) as db:
            wal_restored = db.execute("SELECT value FROM runtime_wal_probe").fetchall() == [("committed before capture",)]
        restored_business = [replay / "data" / path for path in sorted(business_paths(AS_OF))]
        nonempty_before = _nonempty_state(restored_business)
        before_confirmations = latest_execution_confirmations(replay / "data/archive/hermes_state.sqlite")
        actual = _child(replay, replay / "config.json", "replay", probe_net_liq_change=probe_net_liq_change,
                        confirmation_tranche=confirmation_tranche, probe_execution_sell=probe_execution_sell,
                        probe_input_change=probe_input_change, capture_replay=capture_replay,
                        external_legacy=external_legacy)
        comparator = _comparator()
        roots = (seed, source, replay)
        workers = [json.loads((root / "worker.json").read_bytes()) for root in (seed, source, replay)]
        replay_journal = replay / "data/archive/.score_run_transactions/runs" / actual["persistence"]["run_id"] / "manifest.json"
        replay_record = json.loads(replay_journal.read_bytes())
        recapture = None
        if capture_replay:
            replay_before = _tree(replay.parent if external_legacy else replay)
            with patch.dict(os.environ, {"HERMES_DATA_DIR": str(replay)}):
                restored = restore_committed_runtime_inputs(
                    store=LocalStore(load_config(replay / "config.json")),
                    run_id=actual["persistence"]["run_id"], expected_journal_sha256=_sha(replay_journal),
                    decision_id=actual["decision_evidence"]["decision_id"], input_hash=actual["input_hash"],
                    destination=work / "recaptured",
                    external_legacy_layout=external_legacy,
                )
            replay_after = _tree(replay.parent if external_legacy else replay)
            recapture = {
                "committed_inputs_restored": (restored / "inputs/manifest.json").is_file(),
                "capture_ids_distinct": record["capture_id"] != replay_record["capture_id"],
                "run_ids_distinct": run_id != replay_record["run_id"],
                "runtime_lock_matches": _sha(restored / "inputs/source/requirements.lock")
                                        == _sha(replay / "inputs/source/requirements.lock"),
                "source_unchanged_during_restore": replay_after == replay_before,
                "restore_changed_paths": [name for name in sorted(set(replay_before) | set(replay_after))
                                          if replay_before.get(name) != replay_after.get(name)],
                "manifest_sha256": replay_record["input_binding"]["manifest_sha256"],
                "committed_journal_sha256": _sha(replay_journal),
            }
            if probe_input_change:
                change = workers[-1]["input_change"]
                details = {}
                original_value: Any
                restored_value: Any
                if probe_input_change == "history":
                    original = json.loads((replay / "inputs/manifest.json").read_bytes())["histories"]["SOXL"]
                    selected = original["selected"]
                    recaptured_history = (restored / "data/history" if selected == "primary" else
                                          restored.parent / "data/history" if external_legacy else
                                          restored / "data/history_legacy") / "SOXL.csv"
                    original_value = _sha(replay / "inputs/market" / selected / "SOXL.csv")
                    restored_value = _sha(recaptured_history)
                    before_value, expected_value = change["before_sha256"], change["after_sha256"]
                    details["history_selected"] = selected
                elif probe_input_change == "soft":
                    values = [json.loads((root / "inputs/soft.json").read_bytes())["value"]
                              ["records"]["dollar"]["fields"]["dollar_broad_pctl"]
                              for root in (replay, restored)]
                    original_value, restored_value = values
                    before_value, expected_value = change["before"], change["after"]
                else:
                    state_values = []
                    for state_root in (replay / "inputs/pre_state", restored / "data"):
                        state_path = state_root / "archive/reentry_state.sqlite"
                        with closing(sqlite3.connect(state_path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
                            row = db.execute("SELECT t1_active FROM reentry_state WHERE symbol='SOXL'").fetchone()
                        if row is None or row[0] not in (0, 1):
                            raise AssertionError("recaptured state requires an existing boolean tranche flag")
                        state_values.append(bool(row[0]))
                    original_value, restored_value = state_values
                    before_value, expected_value = change["before"], change["after"]
                recapture["input_change"] = {
                    "kind": probe_input_change, **details,
                    "original_value": original_value, "restored_value": restored_value,
                    "expected_value": expected_value, "matches_expected": restored_value == expected_value,
                    "differs_from_original": restored_value != original_value,
                }
                if (original_value != before_value
                        or not recapture["input_change"]["matches_expected"]
                        or not recapture["input_change"]["differs_from_original"]):
                    raise AssertionError("recaptured material does not match the changed replay input")
            if history_selection is not None:
                histories = json.loads((restored / "inputs/manifest.json").read_bytes())["histories"]
                history_selection["recaptured"] = {symbol: row["selected"] for symbol, row in histories.items()}
        # Observe restore before SQLite comparison readers can affect sidecars.
        left, right = _snapshot(source, expected, roots), _snapshot(replay, actual, roots)
        differences = comparator._differences(left, right)
        result = {
            "scope": "REAL_CAPTURE_ISOLATED_FULL_PIPELINE_REPLAY", "production_capture": True,
            "natural_run_evidence": False, "status": "PASS" if not differences else "FAIL",
            "negative_probe": ("NET_LIQ_CHANGED_BY_1000" if probe_net_liq_change else
                               "EXECUTION_BUY_CHANGED_TO_SELL" if probe_execution_sell else
                               "RESTORED_HISTORY_OHLC_CHANGED" if probe_input_change == "history" else
                               "FROZEN_SOFT_RETURN_CHANGED" if probe_input_change == "soft" else
                               "RESTORED_REENTRY_STATE_CHANGED" if probe_input_change == "state" else None),
            "input_change": workers[-1]["input_change"],
            "as_of": AS_OF, "capture_protocol": expected["persistence"]["protocol"],
            "replay_capture": capture_replay, "replay_protocol": actual["persistence"]["protocol"],
            "recapture": recapture,
            "capture_transaction_status": record["status"],
            "replay_transaction_status": replay_record["status"],
            "nonempty_pre_state": nonempty_before, "wal_before_row_restored": wal_restored,
            "before_artifact_availability": {key: row["availability"] for key, row in
                json.loads((replay / "inputs/pre_state.json").read_bytes())["artifacts"].items()},
            "canonical_changed_after_capture": True,
            "source_unchanged_during_restore_replay": _tree(source.parent if external_legacy else source) == before,
            "captured_source_executed": workers[-1]["package"] == str(replay / "package"),
            "input_hash_equal": expected["input_hash"] == actual["input_hash"],
            "artifacts_compared": 7, "strict_differences": differences,
            "strict_difference_paths": _difference_paths(left, right),
            "worker_pids": [worker["pid"] for worker in workers],
            "network_attempts": sum(worker["network_attempts"] for worker in workers),
            "reader_calls": workers[-1]["calls"], "execution_sync_status": actual["execution_sync"]["status"],
            "confirmation": {"requested": confirmation_tranche, "plan": actual["reentry"]["SOXL"],
                             "before": before_confirmations,
                             "latest": actual["execution_sync"].get("latest_confirmations", {}),
                             "reentry_state": actual["reentry_state"]["states"]["SOXL"],
                             "inserted_count": actual["execution_sync"].get("inserted_count", 0),
                             "score": {key: actual["scores"]["SOXL"][key] for key in
                                       ("status", "final_score", "module_scores", "hard_valve_hits")}},
            "normalization": {"contract": "existing strict comparator", "temporary_roots": 3,
                              "additional_ignored_fields": [], "scoring_clock": "2026-05-30T00:10:00+00:00"},
            "seed": seed_binding, "source_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
            "captured_source": comparator._tree_fingerprint(work / "code", relative_roots=("hermes_escape_top",)),
            "runtime_lock_sha256": _sha(work / "code/requirements.lock"),
            "source_manifest_sha256": record["input_binding"]["manifest_sha256"],
            "rehearsal_sha256": _sha(Path(__file__).resolve()),
            "comparator_sha256": _sha(REPO / "scripts/compare_pipeline_persistence.py"),
            "consumer_sha256": _sha(PACKAGE / "core/reporting/transaction_restore.py"),
            "committed_journal_sha256": journal_sha,
            "normalized_reference_sha256": comparator._hash(left), "normalized_replay_sha256": comparator._hash(right),
            "python": comparator._python_evidence(sys.executable), "deployment": "HOLD", "a2": "OPEN",
            "limitations": ["sandbox scheduled capture, not an official live run",
                            "broker returns and eligible-plan market fixtures are synthetic; no live evidence",
                            ("replay creates a new ON/v2 archive; archive bytes are not compared"
                             if capture_replay else "replay executes frozen source with capture OFF and the existing v1 writer"),
                            ("mixed SOXL default external legacy fixture inside private containers"
                             if external_legacy else "mixed SOXL legacy/other primary fixture; nested sandbox legacy path, not default external layout"
                             if selected_legacy else "primary-history fixture only"),
                            "soft builder return and full broker returns are replayed at read boundaries",
                            "same interpreter and installed dependencies; no hermetic runtime archive"],
        }
        if not all((wal_restored, result["nonempty_pre_state"], result["source_unchanged_during_restore_replay"],
                    result["captured_source_executed"], result["input_hash_equal"],
                    result["capture_transaction_status"] == result["replay_transaction_status"] == "COMMITTED",
                    result["network_attempts"] == 0, len(set(result["worker_pids"])) == 3)):
            result["status"] = "FAIL"
        if confirmation_tranche and not (
                actual["reentry"]["SOXL"]["eligible"]
                and actual["reentry"]["SOXL"]["tranche"] == confirmation_tranche
                and actual["execution_sync"]["status"] == "OK"
                and actual["execution_sync"]["inserted_count"] == 1):
            result["status"] = "FAIL"
        if capture_replay and not (
                actual["persistence"]["protocol"] == "recoverable-journal-v2"
                and recapture is not None
                and all(recapture[key] for key in (
                    "committed_inputs_restored", "capture_ids_distinct", "run_ids_distinct",
                    "runtime_lock_matches", "source_unchanged_during_restore"))):
            result["status"] = "FAIL"
        if history_selection is not None:
            result["history_selection"] = history_selection
            if not (history_selection["capture"].get("SOXL") == "legacy"
                    and history_selection["capture"] == history_selection["restored"]
                    and set(history_selection["capture"].values()) == {"primary", "legacy"}
                    and history_selection["legacy_bytes_match"] and history_selection["primary_absent"]
                    and history_selection["source_legacy_changed_after_capture"]
                    and (not capture_replay or history_selection["recaptured"] == history_selection["capture"])):
                result["status"] = "FAIL"
            if external_legacy and not (history_selection["config_bytes_unchanged"]
                                        and history_selection["legacy_inside_private_container"]):
                result["status"] = "FAIL"
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", nargs=3, required=True, metavar=("ROOT", "CONFIG", "MODE"))
    parser.add_argument("--probe-net-liq-change", action="store_true")
    parser.add_argument("--confirmation-tranche", choices=["T1", "T2"])
    parser.add_argument("--probe-execution-sell", action="store_true")
    parser.add_argument("--probe-input-change", choices=["history", "soft", "state"])
    parser.add_argument("--capture-replay", action="store_true")
    parser.add_argument("--external-legacy", action="store_true")
    args = parser.parse_args()
    root, config, mode = args.worker
    _worker(Path(root), Path(config), mode, probe_net_liq_change=args.probe_net_liq_change,
            confirmation_tranche=args.confirmation_tranche, probe_execution_sell=args.probe_execution_sell,
            probe_input_change=args.probe_input_change, capture_replay=args.capture_replay,
            external_legacy=args.external_legacy)
