"""Real runtime capture/replay must preserve mixed primary/legacy selection."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

from hermes_escape_top import pipeline
from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.core.reporting import transaction_restore
from test_a2_production_capture import capture_root as capture_root
from test_broker_input_capture import broker_run as broker_run
from test_committed_runtime_input_restore import _reanchor

REPO = Path(__file__).resolve().parents[3]


def _run(tmp_path, *arguments):
    output = tmp_path / "selected-legacy.json"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/verify_a2_isolated_replay.py"),
         "--runtime-capture", "--selected-legacy", *arguments, "--output", str(output)],
        cwd=REPO, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=180,
    )
    assert output.is_file(), result.stdout + result.stderr
    return result, json.loads(output.read_bytes())


def test_selected_legacy_on_replay_preserves_outputs_and_recaptures_selection(tmp_path):
    result, report = _run(tmp_path, "--capture-replay")
    assert result.returncode == 0, result.stdout + result.stderr
    assert report["status"] == "PASS"
    assert report["capture_protocol"] == report["replay_protocol"] == "recoverable-journal-v2"
    assert report["strict_differences"] == []
    assert report["artifacts_compared"] == 7
    assert report["input_hash_equal"] is True
    selection = report["history_selection"]
    assert selection["capture"]["SOXL"] == selection["restored"]["SOXL"] == "legacy"
    assert set(selection["capture"].values()) == {"primary", "legacy"}
    assert selection["capture"] == selection["restored"] == selection["recaptured"]
    assert selection["legacy_bytes_match"] is True
    assert selection["primary_absent"] is True
    assert selection["source_legacy_changed_after_capture"] is True
    assert report["recapture"]["committed_inputs_restored"] is True
    assert report["recapture"]["run_ids_distinct"] is True
    assert report["recapture"]["capture_ids_distinct"] is True
    assert report["recapture"]["source_unchanged_during_restore"] is True
    assert report["source_unchanged_during_restore_replay"] is True
    assert report["wal_before_row_restored"] is True
    assert report["nonempty_pre_state"] is True
    assert len(set(report["worker_pids"])) == 3
    assert report["network_attempts"] == 0
    assert report["reader_calls"] == {"positions": 1, "executions": 1, "soft_data": 1}
    assert report["natural_run_evidence"] is False
    assert report["deployment"] == "HOLD"


def test_selected_legacy_off_replay_preserves_outputs_and_source_selection(tmp_path):
    result, report = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert report["status"] == "PASS"
    assert report["replay_capture"] is False
    assert report["strict_differences"] == []
    assert report["artifacts_compared"] == 7
    assert report["input_hash_equal"] is True
    assert report["history_selection"]["capture"] == report["history_selection"]["restored"]
    assert report["history_selection"]["capture"]["SOXL"] == "legacy"
    assert report["history_selection"]["primary_absent"] is True
    assert report["history_selection"]["legacy_bytes_match"] is True
    assert report["history_selection"]["recaptured"] is None
    assert report["source_unchanged_during_restore_replay"] is True
    assert len(set(report["worker_pids"])) == 3
    assert report["network_attempts"] == 0


def test_changed_restored_legacy_ohlc_is_a_visible_on_replay_difference(tmp_path):
    result, report = _run(
        tmp_path, "--capture-replay", "--confirmation-tranche", "T1", "--probe-input-change", "history",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert report["status"] == "FAIL"
    assert report["replay_transaction_status"] == "COMMITTED"
    assert report["input_hash_equal"] is False
    assert report["input_change"]["path"] == "data/history_legacy/SOXL.csv"
    assert report["input_change"]["before"] != report["input_change"]["after"]
    assert "payload" in report["strict_differences"]
    assert report["strict_difference_paths"]
    assert report["recapture"]["committed_inputs_restored"] is True
    assert report["history_selection"]["capture"] == report["history_selection"]["recaptured"]
    assert report["source_unchanged_during_restore_replay"] is True
    assert len(set(report["worker_pids"])) == 3
    assert report["network_attempts"] == 0


@pytest.fixture
def legacy_capture(broker_run):
    config = load_config(broker_run.config_path)
    config["paths"]["legacy_history_dir"] = "data/history_legacy"
    broker_run.config_path.write_text(json.dumps(config))
    store = LocalStore(config)
    primary, legacy = store.history_path("SOXL"), store.history_path("SOXL", legacy=True)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    primary.rename(legacy)
    payload = pipeline.score_pipeline(
        "2026-05-29", config_path=broker_run.config_path, include_ibkr=True,
        run_type="scheduled", capture_inputs=True,
    )
    journal = broker_run.archive / f".score_run_transactions/runs/{payload['persistence']['run_id']}/manifest.json"
    bundle = broker_run.archive / "decision_inputs" / payload["persistence"]["capture_id"]
    assert json.loads((bundle / "manifest.json").read_bytes())["histories"]["SOXL"]["selected"] == "legacy"
    return payload, journal, bundle


def test_selected_legacy_missing_material_is_rejected_without_output(broker_run, legacy_capture, tmp_path):
    payload, journal, bundle = legacy_capture
    (bundle / "market/legacy/SOXL.csv").unlink()
    destination = tmp_path / "missing-material"
    with pytest.raises(ValueError):
        transaction_restore.restore_committed_runtime_inputs(
            store=LocalStore(load_config(broker_run.config_path)), run_id=payload["persistence"]["run_id"],
            expected_journal_sha256=hashlib.sha256(journal.read_bytes()).hexdigest(),
            decision_id=payload["decision_evidence"]["decision_id"], input_hash=payload["input_hash"],
            destination=destination,
        )
    assert not destination.exists()
    assert not list(tmp_path.glob(".runtime-input-restore-*"))


def test_selected_legacy_selection_conflict_is_rejected_after_outer_reanchor(
    broker_run, legacy_capture, tmp_path,
):
    payload, journal, bundle = legacy_capture
    path = bundle / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["histories"]["SOXL"]["selected"] = "primary"
    path.chmod(0o600)
    path.write_text(json.dumps(manifest))
    expected = _reanchor(journal, bundle)
    destination = tmp_path / "conflicting-selection"
    with pytest.raises(ValueError, match="restore runtime history selection mismatch"):
        transaction_restore.restore_committed_runtime_inputs(
            store=LocalStore(load_config(broker_run.config_path)), run_id=payload["persistence"]["run_id"],
            expected_journal_sha256=expected,
            decision_id=payload["decision_evidence"]["decision_id"], input_hash=payload["input_hash"],
            destination=destination,
        )
    assert not destination.exists()
    assert not list(tmp_path.glob(".runtime-input-restore-*"))


@pytest.mark.parametrize("arguments", [
    ["--selected-legacy"],
    ["--runtime-capture", "--selected-legacy", "--worker", "root", "config", "seed", "tape"],
])
def test_selected_legacy_cli_rejects_non_runtime_modes_without_report(tmp_path, arguments):
    output = tmp_path / "invalid.json"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/verify_a2_isolated_replay.py"),
         *arguments, "--output", str(output)],
        cwd=REPO, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 2
    assert "selected legacy requires runtime rehearsal" in result.stderr
    assert not output.exists()
