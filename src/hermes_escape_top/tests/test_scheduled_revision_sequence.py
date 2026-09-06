"""Real scheduled transactions in separate processes; no network or live roots."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from test_pipeline_transaction import BUSINESS_ARTIFACTS


def test_scheduled_weekend_sequence_and_real_conflict_restore_seven_artifacts(tmp_path):
    from conftest import PACKAGE_DATA, TEST_DATA, _tracked_package_files

    root = tmp_path / "isolated"
    for src in _tracked_package_files():
        if src.name == "audit_log.jsonl":
            continue
        dst = root / "data" / src.relative_to(PACKAGE_DATA)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    shutil.copytree(TEST_DATA, root / "data", dirs_exist_ok=True)
    archive = root / "data" / "archive"
    env = {**os.environ, "HERMES_DATA_DIR": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    results = []
    for day in (30, 31, 1, 2):
        result = subprocess.run(
            [sys.executable, __file__, str(root), str(day), "normal"],
            env=env, capture_output=True, text=True, timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        results.append(json.loads((root / f"result-{day}.json").read_text()))
    evidence = [row["decision_evidence"] for row in results]
    assert [row["decision_revision"] for row in evidence] == [1, 2, 2, 2]
    assert len({row["semantic_hash"] for row in evidence}) == 1
    assert len({row["market_admission_operation_id"] for row in evidence}) == 4
    assert len({row["canonical_market_evidence_hash"] for row in evidence}) == 4
    assert results[1]["decision_evidence"]["decision_id"] == evidence[-1]["decision_id"]
    assert all(row["transaction_status"] == "COMMITTED" for row in results)
    assert all(row["transaction_artifacts"] == 7 for row in results)
    assert all(row["state_matches_audit"] for row in results)
    assert len({row["pid"] for row in results}) == 4
    before = {name: hashlib.sha256((archive / name).read_bytes()).hexdigest()
              for name in BUSINESS_ARTIFACTS}
    result = subprocess.run(
        [sys.executable, __file__, str(root), "3", "material"],
        env=env, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode != 0
    assert "revision budget exhausted" in result.stderr
    after = {name: hashlib.sha256((archive / name).read_bytes()).hexdigest()
             for name in BUSINESS_ARTIFACTS}
    assert after == before
    assert len((archive / "audit_log.jsonl").read_text().splitlines()) == 4


def _worker(root: Path, day: int, mode: str) -> None:
    import socket
    import sqlite3
    from datetime import datetime
    from unittest.mock import patch
    from zoneinfo import ZoneInfo

    import pandas as pd

    from hermes_escape_top import pipeline
    from hermes_escape_top.config import load_config, resolve_path
    from hermes_escape_top.core.data.manifest import write_manifest
    from hermes_escape_top.core.data.market_admission import MarketAdmissionSession

    instant = datetime(2026, 5 if day >= 30 else 6, day, 7, 10, tzinfo=ZoneInfo("Asia/Shanghai"))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    config = load_config()
    archive = resolve_path(config, "archive_dir")
    history = resolve_path(config, "history_dir")
    assert root.resolve() in archive.resolve().parents
    btc = history / "BTC_USD.csv"
    frame = pd.read_csv(btc)
    date_column = "date" if "date" in frame else "Date"
    if mode != "hold":
        next_row = frame.iloc[-1].copy()
        next_row[date_column] = (pd.to_datetime(frame[date_column]).max() + pd.Timedelta(days=1)).date().isoformat()
        frame.loc[len(frame)] = next_row
    if mode == "material":
        # A real historical input edit, not a fake certification exception.
        close = "close" if "close" in frame else "Close"
        frame.loc[pd.to_datetime(frame[date_column]) <= pd.Timestamp("2026-05-29"), close] *= 1.01
    if mode != "hold":
        frame.to_csv(btc, index=False)
    write_manifest(history, archive / "data_manifest_latest.json")
    session = MarketAdmissionSession(enabled=True, witness_bars={})
    admission = {"operation_id": session.operation_id, "completed_through": "2026-05-29"}
    with patch.object(pipeline, "datetime", Clock), patch.object(
        socket.socket, "connect", side_effect=AssertionError("network forbidden in scheduled regression")
    ):
        payload = pipeline.score_pipeline("2026-05-29", include_ibkr=False,
                                          run_type="scheduled", market_admission_status=admission)
    record = json.loads((archive / "audit_log.jsonl").read_text().splitlines()[-1])
    with sqlite3.connect(archive / "hermes_state.sqlite") as conn:
        stored = json.loads(conn.execute("SELECT payload_json FROM score_runs ORDER BY id DESC LIMIT 1").fetchone()[0])
    transaction = json.loads((archive / ".score_run_transactions" / "runs" /
                              payload["persistence"]["run_id"] / "manifest.json").read_text())
    summary = {
        "run_type": payload["run_type"], "as_of": payload["as_of"], "run_ts": payload["run_ts"],
        "decision_evidence": payload["decision_evidence"], "pid": os.getpid(),
        "transaction_status": transaction["status"],
        "transaction_artifacts": len(transaction["artifacts"]),
        "state_matches_audit": stored["decision_evidence"] == record["payload"]["decision_evidence"],
        "network_used": False, "include_ibkr": False, "data_root": str(root),
    }
    (root / f"result-{day}.json").write_text(json.dumps(summary, sort_keys=True, indent=2))


if __name__ == "__main__":
    _worker(Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3])
