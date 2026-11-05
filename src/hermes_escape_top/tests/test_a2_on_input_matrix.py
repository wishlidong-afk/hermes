"""Changed ON replay inputs must remain visible in outputs and the new archive."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[3]


def _run(tmp_path, kind):
    output = tmp_path / f"on-{kind}.json"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/verify_a2_isolated_replay.py"),
         "--runtime-capture", "--capture-replay", "--confirmation-tranche", "T1",
         "--probe-input-change", kind, "--output", str(output)],
        cwd=REPO, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert output.is_file(), result.stdout + result.stderr
    return json.loads(output.read_bytes())


def _assert_changed_capture(report, kind):
    assert report["status"] == "FAIL"
    assert report["input_change"]["kind"] == kind
    assert report["capture_protocol"] == report["replay_protocol"] == "recoverable-journal-v2"
    assert report["capture_transaction_status"] == report["replay_transaction_status"] == "COMMITTED"
    assert report["replay_capture"] is True
    recapture = report["recapture"]
    for key in ("committed_inputs_restored", "capture_ids_distinct", "run_ids_distinct",
                "runtime_lock_matches", "source_unchanged_during_restore"):
        assert recapture[key] is True, recapture
    assert recapture["restore_changed_paths"] == []
    assert report["source_unchanged_during_restore_replay"] is True
    assert report["captured_source_executed"] is True
    assert report["nonempty_pre_state"] is True
    assert report["wal_before_row_restored"] is True
    assert report["artifacts_compared"] == 7
    assert len(set(report["worker_pids"])) == 3
    assert report["network_attempts"] == 0
    assert report["reader_calls"] == {"positions": 1, "executions": 1, "soft_data": 1}
    assert report["normalization"]["additional_ignored_fields"] == []
    assert report["strict_difference_paths"]
    assert {"payload", "artifact:audit_log.jsonl", "artifact:hermes_state.sqlite"}.issubset(
        report["strict_differences"]
    )
    assert report["natural_run_evidence"] is False
    assert report["deployment"] == "HOLD"
    assert report["a2"] == "OPEN"
    change = recapture["input_change"]
    assert change["kind"] == kind
    assert change["matches_expected"] is True
    assert change["differs_from_original"] is True
    assert change["restored_value"] == change["expected_value"]
    assert change["restored_value"] != change["original_value"]
    return change


def test_on_primary_history_change_is_compared_and_saved_in_the_new_capture(tmp_path):
    report = _run(tmp_path, "history")
    change = _assert_changed_capture(report, "history")
    assert report["negative_probe"] == "RESTORED_HISTORY_OHLC_CHANGED"
    assert report["input_change"]["path"] == "data/history/SOXL.csv"
    assert report["input_change"]["after"]["Close"] == pytest.approx(
        report["input_change"]["before"]["Close"] * 1.15
    )
    assert report["input_hash_equal"] is False
    assert change["history_selected"] == "primary"
    assert change["original_value"] == report["input_change"]["before_sha256"]
    assert change["restored_value"] == report["input_change"]["after_sha256"]


def test_on_soft_return_change_is_compared_and_saved_in_the_new_capture(tmp_path):
    report = _run(tmp_path, "soft")
    change = _assert_changed_capture(report, "soft")
    assert report["negative_probe"] == "FROZEN_SOFT_RETURN_CHANGED"
    assert report["input_change"]["field"] == "dollar.fields.dollar_broad_pctl"
    assert report["input_change"]["before"] < 50
    assert report["input_change"]["after"] == 99.0
    assert report["input_hash_equal"] is False
    assert "artifact:soft_adapter_snapshot_2026-05-29.json" in report["strict_differences"]
    assert change["original_value"] == report["input_change"]["before"]
    assert change["restored_value"] == 99.0


def test_on_pre_state_change_is_compared_and_saved_even_with_equal_input_hash(tmp_path):
    report = _run(tmp_path, "state")
    change = _assert_changed_capture(report, "state")
    assert report["negative_probe"] == "RESTORED_REENTRY_STATE_CHANGED"
    assert report["input_change"]["field"] == "reentry_state.SOXL.t1_active"
    assert report["input_change"]["before"] is False
    assert report["input_change"]["after"] is True
    assert report["input_hash_equal"] is True
    assert report["confirmation"]["plan"]["tranche"] == "T2"
    assert report["confirmation"]["latest"]["SOXL"]["tranche"] == "T2"
    assert "artifact:reentry_state.sqlite" in report["strict_differences"]
    assert change["original_value"] is False
    assert change["restored_value"] is True
