"""A restored producer must support a second, real ON/v2 capture."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPO = Path(__file__).resolve().parents[3]


def _run(tmp_path, *arguments):
    output = tmp_path / "on-replay.json"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/verify_a2_isolated_replay.py"),
         "--runtime-capture", "--capture-replay", *arguments, "--output", str(output)],
        cwd=REPO, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=180,
    )
    assert output.is_file(), result.stdout + result.stderr
    return result, json.loads(output.read_bytes())


def _assert_recapture(report):
    assert report["capture_protocol"] == report["replay_protocol"] == "recoverable-journal-v2"
    assert report["capture_transaction_status"] == report["replay_transaction_status"] == "COMMITTED"
    assert report["replay_capture"] is True
    assert report["recapture"]["committed_inputs_restored"] is True
    assert report["recapture"]["capture_ids_distinct"] is True
    assert report["recapture"]["run_ids_distinct"] is True
    assert report["recapture"]["runtime_lock_matches"] is True
    assert report["recapture"]["source_unchanged_during_restore"] is True, report["recapture"]
    assert len(set(report["worker_pids"])) == 3
    assert report["network_attempts"] == 0
    assert report["natural_run_evidence"] is False
    assert report["deployment"] == "HOLD"


def test_restored_pipeline_recaptures_without_changing_seven_business_outputs(tmp_path):
    result, report = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert report["status"] == "PASS"
    _assert_recapture(report)
    assert report["artifacts_compared"] == 7
    assert report["strict_differences"] == []
    assert report["input_hash_equal"] is True
    assert report["reader_calls"] == {"positions": 1, "executions": 1, "soft_data": 1}
    assert report["wal_before_row_restored"] is True
    assert report["source_unchanged_during_restore_replay"] is True
    assert report["captured_source_executed"] is True


def test_changed_sell_execution_remains_a_visible_difference_with_capture_on(tmp_path):
    result, report = _run(tmp_path, "--confirmation-tranche", "T1", "--probe-execution-sell")
    assert result.returncode == 1, result.stdout + result.stderr
    assert report["status"] == "FAIL"
    _assert_recapture(report)
    assert report["input_hash_equal"] is True
    assert report["execution_sync_status"] == "NO_MATCH"
    assert report["confirmation"]["inserted_count"] == 0
    assert report["confirmation"]["latest"] == report["confirmation"]["before"]
    assert {"payload", "artifact:hermes_state.sqlite", "artifact:audit_log.jsonl"}.issubset(
        report["strict_differences"]
    )
    assert report["source_unchanged_during_restore_replay"] is True


@pytest.mark.parametrize("tranche", ["T1", "T2"])
def test_on_replay_preserves_real_confirmation_and_recaptures_its_inputs(tmp_path, tranche):
    result, report = _run(tmp_path, "--confirmation-tranche", tranche)
    assert result.returncode == 0, result.stdout + result.stderr
    assert report["status"] == "PASS"
    _assert_recapture(report)
    assert report["strict_differences"] == []
    assert report["execution_sync_status"] == "OK"
    assert report["confirmation"]["plan"]["eligible"] is True
    assert report["confirmation"]["plan"]["tranche"] == tranche
    assert report["confirmation"]["inserted_count"] == 1
    assert report["confirmation"]["latest"]["SOXL"]["tranche"] == tranche
    assert report["input_hash_equal"] is True
    assert report["reader_calls"] == {"positions": 1, "executions": 1, "soft_data": 1}
    if tranche == "T2":
        assert report["confirmation"]["before"]["SOXL"]["tranche"] == "T1"
        assert report["confirmation"]["before"]["SOXL"]["source"] == "offline_seed_manual_confirmation"
    else:
        assert "SOXL" not in report["confirmation"]["before"]


def test_changed_net_liq_is_not_hidden_by_a_new_capture(tmp_path):
    result, report = _run(tmp_path, "--probe-net-liq-change")
    assert result.returncode == 1, result.stdout + result.stderr
    assert report["status"] == "FAIL"
    _assert_recapture(report)
    assert report["input_hash_equal"] is True
    assert {"payload", "artifact:hermes_state.sqlite"}.issubset(report["strict_differences"])
    assert report["source_unchanged_during_restore_replay"] is True


@pytest.mark.parametrize("arguments", [
    ["--capture-replay"],
    ["--runtime-capture", "--capture-replay", "--worker", "root", "config", "seed", "tape"],
])
def test_capture_replay_cli_rejects_non_runtime_modes_before_any_report(tmp_path, arguments):
    output = tmp_path / "invalid.json"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/verify_a2_isolated_replay.py"),
         *arguments, "--output", str(output)],
        cwd=REPO, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 2
    assert "capture replay requires runtime rehearsal" in result.stderr
    assert not output.exists()
