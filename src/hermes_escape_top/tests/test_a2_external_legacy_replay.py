"""Default external legacy history must stay inside an offline restore container."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from hermes_escape_top import pipeline
from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.manifest import write_manifest
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.core.reporting.transaction_restore import restore_committed_runtime_inputs
from test_a2_production_capture import capture_root as capture_root
from test_broker_input_capture import broker_run as broker_run
from test_committed_runtime_input_restore import _reanchor

REPO = Path(__file__).resolve().parents[3]


def _run(tmp_path, *arguments):
    output = tmp_path / "external-legacy.json"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/verify_a2_isolated_replay.py"),
         "--runtime-capture", "--external-legacy", *arguments, "--output", str(output)],
        cwd=REPO, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=180,
    )
    assert output.is_file(), result.stdout + result.stderr
    return result, json.loads(output.read_bytes())


def test_default_external_legacy_restores_without_rewriting_config(broker_run, tmp_path, monkeypatch):
    config_bytes = broker_run.config_path.read_bytes()
    store = LocalStore(load_config(broker_run.config_path))
    assert store.config["paths"]["legacy_history_dir"] == "../data/history"
    primary, legacy = store.history_path("SOXL"), store.history_path("SOXL", legacy=True)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    primary.rename(legacy)
    history_bytes = legacy.read_bytes()
    payload = pipeline.score_pipeline(
        "2026-05-29", config_path=broker_run.config_path, include_ibkr=True,
        run_type="scheduled", capture_inputs=True,
    )
    journal = broker_run.archive / f".score_run_transactions/runs/{payload['persistence']['run_id']}/manifest.json"
    legacy.write_text("Date,Close\n2026-05-29,1\n")
    destination = tmp_path / "external-restored"
    result = restore_committed_runtime_inputs(
        store=store, run_id=payload["persistence"]["run_id"],
        expected_journal_sha256=hashlib.sha256(journal.read_bytes()).hexdigest(),
        decision_id=payload["decision_evidence"]["decision_id"], input_hash=payload["input_hash"],
        destination=destination, external_legacy_layout=True,
    )
    assert result == destination / "runtime"
    assert (result / "config.json").read_bytes() == config_bytes
    assert json.loads((result / "inputs/payload.json").read_bytes()) == payload
    monkeypatch.setenv("HERMES_DATA_DIR", str(result))
    restored = LocalStore(load_config(result / "config.json"))
    assert restored.history_path("SOXL", legacy=True) == destination / "data/history/SOXL.csv"
    assert restored.history_path("SOXL", legacy=True).read_bytes() == history_bytes
    assert not restored.history_path("SOXL").exists()
    assert restored.load_history("SOXL").iloc[-1]["Close"] != 1
    assert legacy.read_text() == "Date,Close\n2026-05-29,1\n"


def test_default_external_legacy_on_replay_keeps_config_and_outputs(tmp_path):
    result, report = _run(tmp_path, "--capture-replay")
    assert result.returncode == 0, (report["strict_difference_paths"], result.stderr)
    assert report["status"] == "PASS"
    assert report["capture_protocol"] == report["replay_protocol"] == "recoverable-journal-v2"
    assert report["input_hash_equal"] is True
    assert report["strict_differences"] == []
    assert report["artifacts_compared"] == 7
    selection = report["history_selection"]
    assert selection["capture"] == selection["restored"] == selection["recaptured"]
    assert selection["capture"]["SOXL"] == "legacy"
    assert selection["sandbox_legacy_history_dir"] == "../data/history"
    assert selection["config_bytes_unchanged"] is True
    assert selection["legacy_inside_private_container"] is True
    assert selection["legacy_bytes_match"] and selection["primary_absent"]
    assert selection["source_legacy_changed_after_capture"]
    assert report["source_unchanged_during_restore_replay"] is True
    assert report["recapture"]["committed_inputs_restored"] is True
    assert report["recapture"]["source_unchanged_during_restore"] is True
    assert report["recapture"]["restore_changed_paths"] == []
    assert report["wal_before_row_restored"] is True
    assert report["network_attempts"] == 0
    assert len(set(report["worker_pids"])) == 3


def test_default_external_legacy_off_replay_keeps_selection_and_outputs(tmp_path):
    result, report = _run(tmp_path)
    assert result.returncode == 0, (report["strict_difference_paths"], result.stderr)
    assert report["status"] == "PASS"
    assert report["capture_protocol"] == "recoverable-journal-v2"
    assert report["replay_protocol"] == "recoverable-journal-v1"
    assert report["input_hash_equal"] is True
    assert report["strict_differences"] == []
    assert report["artifacts_compared"] == 7
    selection = report["history_selection"]
    assert selection["capture"] == selection["restored"]
    assert selection["capture"]["SOXL"] == "legacy"
    assert selection["recaptured"] is None
    assert report["recapture"] is None
    assert selection["config_bytes_unchanged"] and selection["legacy_inside_private_container"]
    assert selection["legacy_bytes_match"] and selection["primary_absent"]
    assert selection["source_legacy_changed_after_capture"]
    assert report["source_unchanged_during_restore_replay"] is True
    assert report["network_attempts"] == 0
    assert len(set(report["worker_pids"])) == 3


def test_changed_default_external_legacy_ohlc_is_a_visible_on_replay_difference(tmp_path):
    result, report = _run(
        tmp_path, "--capture-replay", "--confirmation-tranche", "T1", "--probe-input-change", "history",
    )
    assert result.returncode == 1, (report["strict_difference_paths"], result.stderr)
    assert report["status"] == "FAIL"
    assert report["replay_transaction_status"] == "COMMITTED"
    assert report["input_hash_equal"] is False
    assert report["input_change"]["path"] == "data/history/SOXL.csv"
    assert report["input_change"]["before"] != report["input_change"]["after"]
    assert "payload" in report["strict_differences"]
    assert report["strict_difference_paths"]
    selection = report["history_selection"]
    assert selection["capture"] == selection["restored"] == selection["recaptured"]
    assert selection["capture"]["SOXL"] == "legacy"
    assert selection["config_bytes_unchanged"] and selection["legacy_inside_private_container"]
    assert report["recapture"]["committed_inputs_restored"] is True
    assert report["source_unchanged_during_restore_replay"] is True
    assert len(set(report["worker_pids"])) == 3
    assert report["network_attempts"] == 0


def _restore(broker_run, capture, destination):
    payload, journal, _bundle = capture
    return restore_committed_runtime_inputs(
        store=LocalStore(load_config(broker_run.config_path)),
        run_id=payload["persistence"]["run_id"],
        expected_journal_sha256=hashlib.sha256(journal.read_bytes()).hexdigest(),
        decision_id=payload["decision_evidence"]["decision_id"], input_hash=payload["input_hash"],
        destination=destination, external_legacy_layout=True,
    )


@pytest.mark.parametrize("legacy_layout", ["nested", "absolute", "other_relative", "nondefault_primary"])
def test_external_restore_rejects_other_frozen_layouts_before_creating_output(
    broker_run, tmp_path, legacy_layout,
):
    config = load_config(broker_run.config_path)
    if legacy_layout == "nondefault_primary":
        original = LocalStore(config).history_dir
        config["paths"]["history_dir"] = "data/other_history"
        original.rename(LocalStore(config).history_dir)
        write_manifest(LocalStore(config).history_dir, broker_run.archive / "data_manifest_latest.json")
    else:
        config["paths"]["legacy_history_dir"] = {
            "nested": "data/history_legacy", "absolute": str(tmp_path / "custom-legacy"),
            "other_relative": "../../custom-legacy",
        }[legacy_layout]
    broker_run.config_path.write_text(json.dumps(config))
    payload = pipeline.score_pipeline(
        "2026-05-29", config_path=broker_run.config_path, include_ibkr=True,
        run_type="scheduled", capture_inputs=True,
    )
    journal = broker_run.archive / f".score_run_transactions/runs/{payload['persistence']['run_id']}/manifest.json"
    bundle = broker_run.archive / "decision_inputs" / payload["persistence"]["capture_id"]
    destination = tmp_path / "nondefault-layout"
    with pytest.raises(ValueError, match="external legacy restore requires the default history paths"):
        _restore(broker_run, (payload, journal, bundle), destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".runtime-input-restore-*"))


@pytest.fixture
def external_capture(broker_run):
    store = LocalStore(load_config(broker_run.config_path))
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


@pytest.mark.parametrize("damage", ["missing", "symlink", "selection_conflict"])
def test_external_restore_rejects_bad_legacy_evidence_without_output(
    broker_run, external_capture, tmp_path, damage,
):
    _payload, journal, bundle = external_capture
    legacy = bundle / "market/legacy/SOXL.csv"
    expected_message = None
    if damage == "missing":
        legacy.unlink()
    elif damage == "symlink":
        replacement = tmp_path / "same-legacy-bytes.csv"
        replacement.write_bytes(legacy.read_bytes())
        legacy.unlink()
        legacy.symlink_to(replacement)
    else:
        path = bundle / "manifest.json"
        manifest = json.loads(path.read_bytes())
        manifest["histories"]["SOXL"]["selected"] = "primary"
        path.chmod(0o600)
        path.write_text(json.dumps(manifest))
        _reanchor(journal, bundle)
        expected_message = "restore runtime history selection mismatch"
    destination = tmp_path / "rejected-external-material"
    with pytest.raises(ValueError, match=expected_message):
        _restore(broker_run, external_capture, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".runtime-input-restore-*"))


@pytest.mark.parametrize("kind", ["existing", "dangling_symlink", "old_external_root"])
def test_external_restore_keeps_destination_boundaries(
    broker_run, external_capture, tmp_path, kind,
):
    destination = tmp_path / "refused-container"
    if kind == "existing":
        destination.mkdir()
        (destination / "untouched").write_text("old")
    elif kind == "dangling_symlink":
        destination.symlink_to(tmp_path / "missing-container")
    else:
        config = load_config(broker_run.config_path)
        destination = LocalStore(config).legacy_history_dir / "restore"
        config["paths"]["legacy_history_dir"] = str(tmp_path / "different-legacy")
        broker_run.config_path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="already exists|overlaps"):
        _restore(broker_run, external_capture, destination)
    if kind == "existing":
        assert (destination / "untouched").read_text() == "old"
    elif kind == "dangling_symlink":
        assert destination.is_symlink()
    else:
        assert not destination.exists()
    assert not list(tmp_path.glob(".runtime-input-restore-*"))


def test_external_container_publish_failure_cleans_stage_and_keeps_source(
    broker_run, external_capture, tmp_path, monkeypatch,
):
    destination = tmp_path / "unpublished-container"

    def files():
        return {path.relative_to(tmp_path).as_posix():
                (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mode, path.stat().st_mtime_ns)
                for path in tmp_path.rglob("*") if path.is_file()}

    before = files()
    rename = os.rename

    def fail_publish(source, target):
        if Path(target) == destination:
            raise OSError("injected external container publish failure")
        return rename(source, target)

    monkeypatch.setattr(os, "rename", fail_publish)
    with pytest.raises(OSError, match="injected external container publish failure"):
        _restore(broker_run, external_capture, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".runtime-input-restore-*"))
    assert files() == before


@pytest.mark.parametrize("arguments", [
    ["--external-legacy"],
    ["--runtime-capture", "--external-legacy", "--selected-legacy"],
    ["--runtime-capture", "--external-legacy", "--worker", "root", "config", "seed", "tape"],
])
def test_external_legacy_cli_rejects_conflicting_modes_without_report(tmp_path, arguments):
    output = tmp_path / "invalid.json"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/verify_a2_isolated_replay.py"),
         *arguments, "--output", str(output)],
        cwd=REPO, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 2
    assert "external legacy requires runtime rehearsal" in result.stderr
    assert not output.exists()


def test_external_legacy_worker_refuses_arbitrary_root_before_creating_data(tmp_path):
    root = tmp_path / "untrusted/runtime"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/verify_a2_runtime_replay.py"),
         "--worker", str(root), str(tmp_path / "config.json"), "capture", "--external-legacy"],
        cwd=REPO, env={**os.environ, "HERMES_DATA_DIR": str(root)},
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 1
    assert "worker requires the explicitly created runtime rehearsal root" in result.stderr
    assert not root.parent.exists()
