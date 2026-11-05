"""Restore real in-run captures; synthetic broker, isolated data, no network."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from hermes_escape_top import pipeline
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.config import load_config
from hermes_escape_top.core.reporting import transaction_restore
from test_a2_production_capture import capture_root as capture_root
from test_broker_input_capture import broker_run as broker_run


def test_restore_real_committed_producer_inputs_and_before_state(broker_run, tmp_path):
    pipeline.score_pipeline("2026-05-28", config_path=broker_run.config_path, include_ibkr=False)
    payload = pipeline.score_pipeline(
        "2026-05-29", config_path=broker_run.config_path, include_ibkr=True,
        run_type="scheduled", capture_inputs=True,
    )
    run_id = payload["persistence"]["run_id"]
    journal = broker_run.archive / f".score_run_transactions/runs/{run_id}/manifest.json"
    original = broker_run.archive / "decision_inputs" / payload["persistence"]["capture_id"]
    destination = tmp_path / "restored-run"
    result = transaction_restore.restore_committed_runtime_inputs(
        store=LocalStore(load_config(broker_run.config_path)), run_id=run_id,
        expected_journal_sha256=hashlib.sha256(journal.read_bytes()).hexdigest(),
        decision_id=payload["decision_evidence"]["decision_id"], input_hash=payload["input_hash"],
        destination=destination,
    )
    assert result == destination
    assert (result / "inputs/broker.json").read_bytes() == (original / "broker.json").read_bytes()
    assert (result / "inputs/payload.json").read_bytes() == (original / "payload.json").read_bytes()
    assert (result / "config.json").read_bytes() == broker_run.config_path.read_bytes()
    assert (result / "package/pipeline.py").read_bytes() == (original / "source/package/pipeline.py").read_bytes()
    assert (result / "data/history/MSTR.csv").read_bytes() == (original / "market/primary/MSTR.csv").read_bytes()
    assert (result / "data/archive/hermes_state.sqlite").is_file()
    assert json.loads((result / "restoration.json").read_bytes())["evidence_role"] == "OFFLINE_RUNTIME_INPUTS_NOT_FULL_REPLAY"


def _reanchor(journal, bundle):
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    data = bundle.parents[2]
    for row in manifest["files"]:
        row["sha256"] = hashlib.sha256((data / row["path"]).read_bytes()).hexdigest()
    manifest_path.chmod(0o600)
    manifest_path.write_text(json.dumps(manifest))
    record = json.loads(journal.read_bytes())
    record["input_binding"]["manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    for row in record["artifacts"]:
        if row["role"] == "DECISION_INPUT_EVIDENCE":
            row["after_sha256"] = hashlib.sha256((data / row["path"]).read_bytes()).hexdigest()
    journal.write_text(json.dumps(record))
    return hashlib.sha256(journal.read_bytes()).hexdigest()


def test_restore_rejects_self_inconsistent_certification_after_outer_reanchor(broker_run, tmp_path):
    payload = pipeline.score_pipeline(
        "2026-05-29", config_path=broker_run.config_path, include_ibkr=True,
        run_type="scheduled", capture_inputs=True,
    )
    run_id = payload["persistence"]["run_id"]
    journal = broker_run.archive / f".score_run_transactions/runs/{run_id}/manifest.json"
    bundle = broker_run.archive / "decision_inputs" / payload["persistence"]["capture_id"]
    source = bundle / "certification/approved_live_config.json"
    source.chmod(0o600)
    source.write_bytes(source.read_bytes() + b"\n")
    expected = _reanchor(journal, bundle)
    destination = tmp_path / "rejected-run"
    with pytest.raises(ValueError, match="restore.*source.*binding|restore.*certification"):
        transaction_restore.restore_committed_runtime_inputs(
            store=LocalStore(load_config(broker_run.config_path)), run_id=run_id,
            expected_journal_sha256=expected, decision_id=payload["decision_evidence"]["decision_id"],
            input_hash=payload["input_hash"], destination=destination,
        )
    assert not destination.exists()
    assert not list(tmp_path.glob(".runtime-input-restore-*"))


@pytest.fixture
def committed_capture(broker_run):
    payload = pipeline.score_pipeline(
        "2026-05-29", config_path=broker_run.config_path, include_ibkr=True,
        run_type="scheduled", capture_inputs=True,
    )
    journal = broker_run.archive / f".score_run_transactions/runs/{payload['persistence']['run_id']}/manifest.json"
    bundle = broker_run.archive / "decision_inputs" / payload["persistence"]["capture_id"]
    return payload, journal, bundle


def _restore(broker_run, capture, destination, **overrides):
    payload, journal, _bundle = capture
    arguments = {
        "store": LocalStore(load_config(broker_run.config_path)),
        "run_id": payload["persistence"]["run_id"],
        "expected_journal_sha256": hashlib.sha256(journal.read_bytes()).hexdigest(),
        "decision_id": payload["decision_evidence"]["decision_id"], "input_hash": payload["input_hash"],
        "destination": destination,
    }
    return transaction_restore.restore_committed_runtime_inputs(**{**arguments, **overrides})


@pytest.mark.parametrize("damage", [
    "journal_digest", "decision_id", "input_hash", "not_committed", "wrong_mode", "wrong_role",
    "missing", "extra", "symlink", "config", "broker", "broker_snapshot", "history", "certification_time",
    "soft_field_order", "soft_field_order_null",
])
def test_runtime_restore_rejects_invalid_evidence_without_partial_output(
    broker_run, committed_capture, tmp_path, damage,
):
    _payload, journal, bundle = committed_capture
    overrides = {}
    if damage in {"journal_digest", "decision_id", "input_hash"}:
        key = "expected_journal_sha256" if damage == "journal_digest" else damage
        overrides[key] = "0" * 64
    elif damage in {"not_committed", "wrong_mode", "wrong_role"}:
        record = json.loads(journal.read_bytes())
        if damage == "not_committed":
            record["status"] = "PREPARED"
        elif damage == "wrong_mode":
            record["metadata"]["shadow"] = True
        else:
            record["artifacts"][0]["role"] = "UNKNOWN"
        journal.write_text(json.dumps(record))
    elif damage in {"missing", "extra", "symlink"}:
        path = bundle / "broker.json"
        if damage == "missing":
            path.unlink()
        elif damage == "extra":
            (bundle / "unregistered.json").write_text("{}")
        else:
            replacement = tmp_path / "same-broker-bytes.json"
            replacement.write_bytes(path.read_bytes())
            path.unlink()
            path.symlink_to(replacement)
    else:
        names = {"config": "configuration.raw.json", "broker": "broker.json", "broker_snapshot": "broker.json",
                 "history": "histories.json", "certification_time": "certification.json",
                 "soft_field_order": "soft.json", "soft_field_order_null": "soft.json"}
        path = bundle / names[damage]
        value = json.loads(path.read_bytes())
        if damage == "config":
            value["version"] = "changed"
        elif damage == "broker":
            value["reads"]["executions"]["status"] = "PENDING"
        elif damage == "broker_snapshot":
            value["reads"]["positions"]["snapshot"] = None
        elif damage == "history":
            frame = value["MSTR"]
            frame["data"][-1][frame["columns"].index("Close")] += 1
        elif damage == "soft_field_order":
            value["record_field_order"]["dollar"].append(value["record_field_order"]["dollar"][0])
        elif damage == "soft_field_order_null":
            value["record_field_order"] = None
        else:
            value["certified_at"] = "2026-05-29T00:00:00+00:00"
        path.chmod(0o600)
        path.write_text(json.dumps(value))
        _reanchor(journal, bundle)
    destination = tmp_path / "must-not-exist"
    with pytest.raises((ValueError, FileNotFoundError)):
        _restore(broker_run, committed_capture, destination, **overrides)
    assert not destination.exists()
    assert not list(tmp_path.glob(".runtime-input-restore-*"))


@pytest.mark.parametrize("destination_kind", ["existing", "dangling_symlink", "canonical", "bundle"])
def test_runtime_restore_refuses_target_boundaries(
    broker_run, committed_capture, tmp_path, destination_kind,
):
    destination = tmp_path / "blocked-destination"
    if destination_kind == "existing":
        destination.mkdir()
        (destination / "untouched").write_text("old")
    elif destination_kind == "dangling_symlink":
        destination.symlink_to(tmp_path / "nonexistent")
    elif destination_kind == "canonical":
        destination = broker_run.archive.parent / "history/restore"
    else:
        destination = committed_capture[2] / "restore"
    with pytest.raises(ValueError, match="already exists|overlaps"):
        _restore(broker_run, committed_capture, destination)
    if destination_kind == "existing":
        assert (destination / "untouched").read_text() == "old"
    elif destination_kind == "dangling_symlink":
        assert destination.is_symlink()
    else:
        assert not destination.exists()


def test_runtime_restore_uses_archived_bytes_after_canonical_changes_and_keeps_source_unchanged(
    broker_run, committed_capture, tmp_path,
):
    _payload, _journal, bundle = committed_capture
    history = broker_run.archive.parent / "history/MSTR.csv"
    history.write_bytes(b"Date,Close\n2026-05-29,1\n")
    soft = broker_run.archive.parent / "soft_history/dollar.csv"
    soft.write_bytes(b"date,value\n2026-05-29,999\n")
    source = broker_run.archive.parent
    before = {path.relative_to(source).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
              for path in source.rglob("*") if path.is_file()}
    restored = _restore(broker_run, committed_capture, tmp_path / "frozen-inputs")
    assert (restored / "data/history/MSTR.csv").read_bytes() == (bundle / "market/primary/MSTR.csv").read_bytes()
    assert (restored / "data/soft_history/dollar.csv").read_bytes() == (bundle / "soft_sources/dollar.csv").read_bytes()
    after = {path.relative_to(source).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
             for path in source.rglob("*") if path.is_file()}
    assert after == before
    assert restored.stat().st_mode & 0o777 == 0o700
    for path in (restored / "inputs").rglob("*"):
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o400)


def test_legacy_capture_without_field_order_still_restores_but_does_not_prove_replay(
    broker_run, committed_capture, tmp_path,
):
    _payload, journal, bundle = committed_capture
    path = bundle / "soft.json"
    soft = json.loads(path.read_bytes())
    del soft["record_field_order"]
    path.chmod(0o600)
    path.write_text(json.dumps(soft))
    _reanchor(journal, bundle)
    restored = _restore(broker_run, committed_capture, tmp_path / "legacy-orderless-restore")
    assert "record_field_order" not in json.loads((restored / "inputs/soft.json").read_bytes())
    assert json.loads((restored / "restoration.json").read_bytes())["evidence_role"] == "OFFLINE_RUNTIME_INPUTS_NOT_FULL_REPLAY"


def test_runtime_restore_recovers_real_wal_before_image(broker_run, tmp_path):
    pipeline.score_pipeline("2026-05-28", config_path=broker_run.config_path, include_ibkr=False)
    database = broker_run.archive / "hermes_state.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE capture_wal_probe (value TEXT)")
        connection.execute("INSERT INTO capture_wal_probe VALUES ('committed WAL row')")
        connection.commit()
        assert Path(str(database) + "-wal").stat().st_size > 0
        payload = pipeline.score_pipeline(
            "2026-05-29", config_path=broker_run.config_path, include_ibkr=True,
            run_type="scheduled", capture_inputs=True,
        )
        journal = broker_run.archive / f".score_run_transactions/runs/{payload['persistence']['run_id']}/manifest.json"
        bundle = broker_run.archive / "decision_inputs" / payload["persistence"]["capture_id"]
        restored = _restore(broker_run, (payload, journal, bundle), tmp_path / "wal-restored")
    with closing(sqlite3.connect(restored / "data/archive/hermes_state.sqlite")) as recovered:
        assert recovered.execute("SELECT value FROM capture_wal_probe").fetchall() == [("committed WAL row",)]
    assert not list((restored / "data/archive").glob("*-wal"))


def test_runtime_restore_protects_original_roots_after_data_root_switch(
    broker_run, committed_capture, tmp_path, monkeypatch,
):
    moved = tmp_path / "moved-root"
    shutil.copytree(broker_run.archive.parent, moved / "data")
    monkeypatch.setenv("HERMES_DATA_DIR", str(moved))
    destination = broker_run.archive.parent / "history/new-parent/restore-into-old-canonical"
    with pytest.raises(ValueError, match="overlaps"):
        _restore(broker_run, committed_capture, destination)
    assert not destination.exists()
    assert not destination.parent.exists()
    assert not list(destination.parent.glob(".runtime-input-restore-*"))


def test_runtime_restore_cleans_staging_on_materialization_failure(
    broker_run, committed_capture, tmp_path, monkeypatch,
):
    original = transaction_restore._write

    def fail(root, relative, content):
        if relative == "inputs/broker.json":
            raise OSError("synthetic input materialization failure")
        return original(root, relative, content)

    monkeypatch.setattr(transaction_restore, "_write", fail)
    destination = tmp_path / "failed-publication"
    with pytest.raises(OSError, match="synthetic input materialization failure"):
        _restore(broker_run, committed_capture, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".runtime-input-restore-*"))


def test_runtime_restore_preserves_legacy_selection_and_disabled_broker(broker_run, tmp_path):
    data = broker_run.archive.parent
    legacy = LocalStore(load_config(broker_run.config_path)).history_path("MSTR", legacy=True)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    (data / "history/MSTR.csv").rename(legacy)
    payload = pipeline.score_pipeline(
        "2026-05-29", config_path=broker_run.config_path, include_ibkr=False,
        run_type="scheduled", capture_inputs=True,
    )
    journal = broker_run.archive / f".score_run_transactions/runs/{payload['persistence']['run_id']}/manifest.json"
    bundle = broker_run.archive / "decision_inputs" / payload["persistence"]["capture_id"]
    restored = _restore(broker_run, (payload, journal, bundle), tmp_path / "legacy-restored")
    assert not (restored / "data/history/MSTR.csv").exists()
    assert (restored / "data/history_legacy/MSTR.csv").read_bytes() == legacy.read_bytes()
    tape = json.loads((restored / "inputs/broker.json").read_bytes())
    assert all(row["status"] == "NOT_READ" for row in tape["reads"].values())


def test_runtime_restore_rejects_raw_history_disagreeing_with_consumed_frame_after_reanchor(
    broker_run, committed_capture, tmp_path,
):
    import pandas as pd

    _payload, journal, bundle = committed_capture
    path = bundle / "market/primary/MSTR.csv"
    frame = pd.read_csv(path)
    columns = {column.lower(): column for column in frame.columns}
    selected = pd.to_datetime(frame[columns["date"]]) == pd.Timestamp("2026-05-29")
    assert selected.any()
    frame.loc[selected, columns["close"]] += 10
    path.chmod(0o600)
    path.write_text(frame.to_csv(index=False))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    entry = manifest["histories"]["MSTR"]["primary"]
    entry["sha256"] = digest
    manifest["source_inventory"][entry["source"]]["sha256"] = digest
    manifest_path.chmod(0o600)
    manifest_path.write_text(json.dumps(manifest))
    _reanchor(journal, bundle)
    destination = tmp_path / "raw-history-rejected"
    with pytest.raises(ValueError, match="restore raw history consumption mismatch"):
        _restore(broker_run, committed_capture, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".runtime-input-restore-*"))
