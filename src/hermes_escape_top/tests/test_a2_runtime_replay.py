"""Full pipeline replay from a real, explicitly enabled sandbox capture."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def test_real_capture_replays_frozen_inputs_and_wal_state_in_three_processes(tmp_path):
    report = tmp_path / "runtime-replay.json"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/verify_a2_isolated_replay.py"),
         "--runtime-capture", "--output", str(report)],
        cwd=REPO, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(report.read_text())
    assert evidence["status"] == "PASS"
    assert evidence["scope"] == "REAL_CAPTURE_ISOLATED_FULL_PIPELINE_REPLAY"
    assert evidence["production_capture"] is True
    assert evidence["natural_run_evidence"] is False
    assert evidence["capture_protocol"] == "recoverable-journal-v2"
    assert evidence["capture_transaction_status"] == "COMMITTED"
    assert evidence["replay_transaction_status"] == "COMMITTED"
    assert evidence["nonempty_pre_state"] is True
    assert evidence["wal_before_row_restored"] is True
    assert evidence["canonical_changed_after_capture"] is True
    assert evidence["source_unchanged_during_restore_replay"] is True
    assert evidence["captured_source_executed"] is True
    assert evidence["input_hash_equal"] is True
    assert evidence["artifacts_compared"] == 7
    assert evidence["strict_differences"] == []
    assert len(set(evidence["worker_pids"])) == 3
    assert evidence["network_attempts"] == 0
    assert evidence["execution_sync_status"] == "NO_MATCH"
    assert evidence["normalization"]["additional_ignored_fields"] == []
    assert evidence["deployment"] == "HOLD"


def test_real_capture_changed_net_liq_is_a_visible_full_pipeline_difference(tmp_path):
    report = tmp_path / "changed-net-liq.json"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/verify_a2_isolated_replay.py"),
         "--runtime-capture", "--probe-net-liq-change", "--output", str(report)],
        cwd=REPO, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert report.is_file(), result.stdout + result.stderr
    evidence = json.loads(report.read_text())
    assert evidence["status"] == "FAIL"
    assert evidence["negative_probe"] == "NET_LIQ_CHANGED_BY_1000"
    assert evidence["input_hash_equal"] is True
    assert "payload" in evidence["strict_differences"]
    assert "artifact:hermes_state.sqlite" in evidence["strict_differences"]
    assert evidence["source_unchanged_during_restore_replay"] is True
    assert evidence["network_attempts"] == 0


@pytest.mark.parametrize("tranche", ["T1", "T2"])
def test_real_capture_replays_confirmation_from_an_unmocked_plan(tmp_path, tranche):
    report = tmp_path / f"{tranche}-replay.json"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/verify_a2_isolated_replay.py"),
         "--runtime-capture", "--confirmation-tranche", tranche, "--output", str(report)],
        cwd=REPO, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(report.read_text())
    assert evidence["status"] == "PASS"
    assert evidence["execution_sync_status"] == "OK"
    assert evidence["confirmation"]["plan"]["eligible"] is True
    assert evidence["confirmation"]["plan"]["tranche"] == tranche
    assert evidence["confirmation"]["inserted_count"] == 1
    assert evidence["confirmation"]["latest"]["SOXL"]["tranche"] == tranche
    assert evidence["confirmation"]["latest"]["SOXL"]["source"] == "ibkr_executions"
    assert evidence["confirmation"]["latest"]["SOXL"]["payload"]["shares"] == 2.0
    assert evidence["confirmation"]["latest"]["SOXL"]["payload"]["external_key"] == "OFFLINE-FILL"
    if tranche == "T2":
        assert evidence["confirmation"]["before"]["SOXL"]["tranche"] == "T1"
        assert evidence["confirmation"]["before"]["SOXL"]["source"] == "offline_seed_manual_confirmation"
        assert evidence["confirmation"]["reentry_state"]["t1_active"] is True
    else:
        assert "SOXL" not in evidence["confirmation"]["before"]
        assert evidence["confirmation"]["reentry_state"]["t1_active"] is False
    assert evidence["confirmation"]["reentry_state"]["t2_active"] is False
    assert all(row["passed"] for row in evidence["confirmation"]["plan"]["locks"].values())
    assert evidence["strict_differences"] == []
    assert evidence["artifacts_compared"] == 7
    assert len(set(evidence["worker_pids"])) == 3
    assert evidence["reader_calls"] == {"positions": 1, "executions": 1, "soft_data": 1}
    assert evidence["network_attempts"] == 0


@pytest.mark.parametrize("tranche", ["T1", "T2"])
def test_sell_execution_cannot_reproduce_buy_confirmation(tmp_path, tranche):
    report = tmp_path / f"{tranche}-sell.json"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/verify_a2_isolated_replay.py"),
         "--runtime-capture", "--confirmation-tranche", tranche, "--probe-execution-sell",
         "--output", str(report)],
        cwd=REPO, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    evidence = json.loads(report.read_text())
    assert evidence["status"] == "FAIL"
    assert evidence["negative_probe"] == "EXECUTION_BUY_CHANGED_TO_SELL"
    assert evidence["execution_sync_status"] == "NO_MATCH"
    assert evidence["confirmation"]["inserted_count"] == 0
    assert evidence["confirmation"]["latest"] == evidence["confirmation"]["before"]
    assert evidence["input_hash_equal"] is True
    assert {"payload", "artifact:hermes_state.sqlite", "artifact:audit_log.jsonl"}.issubset(
        evidence["strict_differences"]
    )
    assert evidence["source_unchanged_during_restore_replay"] is True
    assert evidence["network_attempts"] == 0


def test_changed_restored_history_is_a_full_pipeline_difference(tmp_path):
    report = tmp_path / "changed-history.json"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/verify_a2_isolated_replay.py"),
         "--runtime-capture", "--confirmation-tranche", "T1", "--probe-input-change", "history",
         "--output", str(report)], cwd=REPO,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert report.is_file(), result.stdout + result.stderr
    evidence = json.loads(report.read_text())
    assert evidence["status"] == "FAIL"
    assert evidence["negative_probe"] == "RESTORED_HISTORY_OHLC_CHANGED"
    assert evidence["input_change"]["kind"] == "history"
    assert evidence["input_change"]["path"] == "data/history/SOXL.csv"
    assert evidence["input_change"]["before_sha256"] != evidence["input_change"]["after_sha256"]
    assert evidence["input_change"]["after"]["Close"] == pytest.approx(
        evidence["input_change"]["before"]["Close"] * 1.15
    )
    assert evidence["input_hash_equal"] is False
    assert evidence["artifacts_compared"] == 7
    assert evidence["capture_transaction_status"] == evidence["replay_transaction_status"] == "COMMITTED"
    assert evidence["wal_before_row_restored"] is True
    assert len(set(evidence["worker_pids"])) == 3
    assert {"payload", "artifact:hermes_state.sqlite", "artifact:audit_log.jsonl"}.issubset(
        evidence["strict_differences"]
    )
    assert evidence["source_unchanged_during_restore_replay"] is True
    assert evidence["network_attempts"] == 0


def test_changed_soft_return_is_a_full_pipeline_difference(tmp_path):
    report = tmp_path / "changed-soft.json"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/verify_a2_isolated_replay.py"),
         "--runtime-capture", "--confirmation-tranche", "T1", "--probe-input-change", "soft",
         "--output", str(report)], cwd=REPO,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert report.is_file(), result.stdout + result.stderr
    evidence = json.loads(report.read_text())
    assert evidence["status"] == "FAIL"
    assert evidence["negative_probe"] == "FROZEN_SOFT_RETURN_CHANGED"
    assert evidence["input_change"]["kind"] == "soft"
    assert evidence["input_change"]["field"] == "dollar.fields.dollar_broad_pctl"
    assert evidence["input_change"]["before"] < 50
    assert evidence["input_change"]["after"] == 99.0
    assert evidence["input_hash_equal"] is False
    assert evidence["artifacts_compared"] == 7
    assert evidence["capture_transaction_status"] == evidence["replay_transaction_status"] == "COMMITTED"
    assert evidence["wal_before_row_restored"] is True
    assert len(set(evidence["worker_pids"])) == 3
    assert {"payload", "artifact:hermes_state.sqlite", "artifact:audit_log.jsonl",
            "artifact:soft_adapter_snapshot_2026-05-29.json"}.issubset(evidence["strict_differences"])
    assert evidence["reader_calls"] == {"positions": 1, "executions": 1, "soft_data": 1}
    assert evidence["source_unchanged_during_restore_replay"] is True
    assert evidence["network_attempts"] == 0


def test_changed_reentry_pre_state_is_visible_even_with_equal_input_hash(tmp_path):
    report = tmp_path / "changed-state.json"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/verify_a2_isolated_replay.py"),
         "--runtime-capture", "--confirmation-tranche", "T1", "--probe-input-change", "state",
         "--output", str(report)], cwd=REPO,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert report.is_file(), result.stdout + result.stderr
    evidence = json.loads(report.read_text())
    assert evidence["status"] == "FAIL"
    assert evidence["negative_probe"] == "RESTORED_REENTRY_STATE_CHANGED"
    assert evidence["input_change"]["kind"] == "state"
    assert evidence["input_change"]["field"] == "reentry_state.SOXL.t1_active"
    assert evidence["input_change"]["before"] is False
    assert evidence["input_change"]["after"] is True
    assert evidence["confirmation"]["plan"]["tranche"] == "T2"
    assert evidence["confirmation"]["latest"]["SOXL"]["tranche"] == "T2"
    assert evidence["input_hash_equal"] is True
    assert evidence["artifacts_compared"] == 7
    assert evidence["capture_transaction_status"] == evidence["replay_transaction_status"] == "COMMITTED"
    assert evidence["wal_before_row_restored"] is True
    assert {"payload", "artifact:hermes_state.sqlite", "artifact:audit_log.jsonl",
            "artifact:reentry_state.sqlite"}.issubset(evidence["strict_differences"])
    assert len(set(evidence["worker_pids"])) == 3
    assert evidence["source_unchanged_during_restore_replay"] is True
    assert evidence["network_attempts"] == 0


@pytest.mark.parametrize("arguments,message", [
    (["--confirmation-tranche", "T1"], "confirmation tranche requires"),
    (["--runtime-capture", "--probe-execution-sell"], "execution probe requires"),
    (["--runtime-capture", "--confirmation-tranche", "T1", "--probe-execution-sell",
      "--probe-net-liq-change"], "one negative probe at a time"),
    (["--probe-input-change", "history"], "input probe requires"),
    (["--runtime-capture", "--probe-input-change", "soft", "--probe-net-liq-change"],
     "one negative probe at a time"),
    (["--runtime-capture", "--confirmation-tranche", "T1", "--probe-input-change", "state",
      "--probe-execution-sell"], "one negative probe at a time"),
])
def test_confirmation_cli_rejects_ambiguous_mode_before_rehearsing(tmp_path, arguments, message):
    report = tmp_path / "invalid.json"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/verify_a2_isolated_replay.py"), *arguments,
         "--output", str(report)], cwd=REPO, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 2
    assert message in result.stderr
    assert not report.exists()


@pytest.mark.parametrize("mode", ["seed", "capture", "replay"])
def test_runtime_worker_refuses_arbitrary_root_before_creating_state(tmp_path, mode):
    root = tmp_path / mode
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/verify_a2_runtime_replay.py"), "--worker",
         str(root), str(tmp_path / "config.json"), mode],
        cwd=REPO, env={**os.environ, "HERMES_DATA_DIR": str(root), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode != 0
    assert "explicitly created runtime rehearsal root" in result.stderr
    assert not root.exists()
