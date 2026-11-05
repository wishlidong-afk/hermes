"""Default-off production capture transaction boundary, before input binding."""
from __future__ import annotations

import shutil
import sqlite3
import json
import hashlib
from contextlib import closing

import pytest

from hermes_escape_top import pipeline
from hermes_escape_top.config import load_config, resolve_path
from hermes_escape_top.core.data.run_transaction import (
    load_score_run_transaction,
    pending_score_run_transaction,
    score_run_transaction,
)
from hermes_escape_top.core.data.manifest import write_manifest
from hermes_escape_top.core.data.sqlite_snapshot import sqlite_state_hash
from hermes_escape_top.core.data.transaction_evidence import business_paths
from hermes_escape_top.core.safe_io import pipeline_lock


@pytest.fixture
def capture_root(tmp_path, isolated_data_dir, monkeypatch):
    root = tmp_path / "capture-root"
    data = root / "data"
    data.mkdir(parents=True)
    for name in ("history", "soft_history", "history_legacy"):
        source = isolated_data_dir / "data" / name
        if source.exists():
            shutil.copytree(source, data / name)
    monkeypatch.setenv("HERMES_DATA_DIR", str(root))

    def forbid(*_args, **_kwargs):
        pytest.fail("capture boundary test attempted a network connection")

    monkeypatch.setattr("socket.socket.connect", forbid)
    monkeypatch.setattr("socket.create_connection", forbid)
    return resolve_path(load_config(), "archive_dir")


def _business_state(archive):
    result = {}
    for relative in sorted(business_paths("2026-05-29")):
        path = archive.parent / relative
        if not path.exists():
            result[relative] = None
        elif path.suffix == ".sqlite":
            with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as connection:
                result[relative] = sqlite_state_hash(connection)
        else:
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


@pytest.mark.parametrize("run_type,shadow,include_ibkr", [
    ("manual_rerun", False, False),
    ("scheduled", True, False),
    ("manual_rerun", False, True),
])
def test_capture_rejects_invalid_mode_before_decision_date_or_state_reads(
    capture_root, monkeypatch, run_type, shadow, include_ibkr,
):
    def forbid(*_args, **_kwargs):
        pytest.fail("invalid capture mode reached decision-date resolution")

    monkeypatch.setattr(pipeline, "resolve_decision_as_of", forbid)

    with pytest.raises(ValueError, match="capture requires non-shadow scheduled mode"):
        pipeline.score_pipeline(
            "2026-05-29", include_ibkr=include_ibkr, shadow=shadow, run_type=run_type, capture_inputs=True,
        )

    assert not (capture_root / ".score_run_transactions").exists()


@pytest.mark.parametrize("reader_name,state_name,feature", [
    ("read_reentry_states", "reentry_state.sqlite", None),
    ("latest_decision_statuses", "hermes_state.sqlite", "use_status_hysteresis"),
    ("latest_score_payload_before", "hermes_state.sqlite", "use_route_set_transition_buffer"),
    ("latest_execution_confirmations", "hermes_state.sqlite", None),
])
def test_capture_restores_old_schema_when_state_reader_then_fails(
    capture_root, monkeypatch, reader_name, state_name, feature,
):
    capture_root.mkdir(parents=True)
    state = capture_root / state_name
    with sqlite3.connect(state) as connection:
        connection.execute("CREATE TABLE seed (value TEXT)")
        connection.execute("INSERT INTO seed VALUES ('old state')")
    if feature:
        config = load_config()
        config["features"][feature] = True
        config_path = capture_root.parent / "config.json"
        config_path.write_text(json.dumps(config))
    else:
        config_path = pipeline.CONFIG_PATH
    reader = getattr(pipeline, reader_name)
    observed = {}

    def read_then_fail(path, *args, **kwargs):
        result = reader(path, *args, **kwargs)
        assert result in ({}, None)
        with sqlite3.connect(path) as connection:
            assert connection.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'",
            ).fetchone()[0] > 1
        observed["transaction"] = pending_score_run_transaction(capture_root)
        raise RuntimeError("failure after schema mutation")

    monkeypatch.setattr(pipeline, reader_name, read_then_fail)

    with pytest.raises(RuntimeError, match="failure after schema mutation"):
        pipeline.score_pipeline(
            "2026-05-29", config_path=config_path, include_ibkr=False, run_type="scheduled", capture_inputs=True,
        )

    with sqlite3.connect(state) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("seed",)]
        assert connection.execute("SELECT value FROM seed").fetchall() == [("old state",)]
    assert observed["transaction"]["schema_version"] == "hermes-score-run-transaction-v2"
    assert pending_score_run_transaction(capture_root) is None


def test_unbound_capture_cannot_commit_even_after_real_scoring_and_business_writes(capture_root, monkeypatch):
    write_manifest(resolve_path(load_config(), "history_dir"), capture_root / "data_manifest_latest.json")
    observed = {}

    def observe(checkpoint):
        if checkpoint == "signal_journal":
            observed["pending"] = pending_score_run_transaction(capture_root)
            observed["audit"] = json.loads((capture_root / "audit_log.jsonl").read_text().splitlines()[-1])

    monkeypatch.setattr(pipeline, "_persistence_checkpoint", observe)
    monkeypatch.setattr(pipeline.RuntimeCapture, "finish", lambda *_args, **_kwargs: None)

    with pytest.raises(ValueError, match="transaction input binding missing"):
        pipeline.score_pipeline(
            "2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True,
        )

    assert observed["audit"]["payload"]["persistence"]["protocol"] == "recoverable-journal-v2"
    assert observed["audit"]["payload"]["persistence"]["run_id"] == observed["pending"]["run_id"]
    assert observed["audit"]["payload"]["persistence"]["capture_id"] == observed["pending"]["capture_id"]
    assert all(not (capture_root.parent / path).exists() for path in business_paths("2026-05-29"))
    assert pending_score_run_transaction(capture_root) is None
    assert not any(path.is_file() for path in (capture_root / "decision_inputs").rglob("*"))


@pytest.mark.parametrize("checkpoint", pipeline.PERSISTENCE_CHECKPOINTS)
def test_capture_persistence_fault_restores_all_old_business_state(capture_root, monkeypatch, checkpoint):
    pipeline.score_pipeline("2026-05-28", include_ibkr=False)
    write_manifest(resolve_path(load_config(), "history_dir"), capture_root / "data_manifest_latest.json")
    before = _business_state(capture_root)
    observed = {}

    def fail(stage):
        if stage == checkpoint:
            observed["pending"] = pending_score_run_transaction(capture_root)
            raise RuntimeError(f"capture failure after {stage}")

    monkeypatch.setattr(pipeline, "_persistence_checkpoint", fail)

    with pytest.raises(RuntimeError, match=f"capture failure after {checkpoint}"):
        pipeline.score_pipeline(
            "2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True,
        )

    assert _business_state(capture_root) == before
    record = load_score_run_transaction(capture_root, observed["pending"]["run_id"])
    assert record["status"] == "ROLLED_BACK"
    assert record["schema_version"] == "hermes-score-run-transaction-v2"
    assert {row["path"] for row in record["artifacts"] if row["role"] == "BUSINESS"} == business_paths("2026-05-29")
    assert pending_score_run_transaction(capture_root) is None
    assert not any(path.is_file() for path in (capture_root / "decision_inputs").rglob("*"))


@pytest.mark.parametrize("lease_kind", ["missing", "wrong_root", "expired"])
def test_capture_refuses_invalid_lease_before_state_read(capture_root, tmp_path, monkeypatch, lease_kind):
    with pipeline_lock(path=capture_root / ".pipeline.lock") as lease:
        expired = lease
    with pipeline_lock(path=tmp_path / "other/.pipeline.lock") as wrong:
        selected = {"missing": None, "wrong_root": wrong, "expired": expired}[lease_kind]
        with pytest.raises(RuntimeError, match="pipeline lease"):
            pipeline._score_pipeline_locked(
                "2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True, _lease=selected,
            )
    assert not (capture_root / ".score_run_transactions").exists()


def test_capture_recovers_prior_pending_run_before_export_or_state_read(capture_root, monkeypatch):
    capture_root.mkdir(parents=True)
    state = capture_root / "reentry_state.sqlite"
    with closing(sqlite3.connect(state)) as connection:
        connection.execute("CREATE TABLE seed (value TEXT)")
        connection.execute("INSERT INTO seed VALUES ('before old pending run')")
        connection.commit()
    with pipeline_lock(path=capture_root / ".pipeline.lock") as lease:
        interrupted = score_run_transaction(capture_root, [state], metadata={}, _lease=lease)
        previous = interrupted.__enter__()
        with closing(sqlite3.connect(state)) as connection:
            connection.execute("UPDATE seed SET value='partial old pending run'")
            connection.commit()
    observed = {}

    def inspect_then_fail(path):
        with closing(sqlite3.connect(path)) as connection:
            observed["value"] = connection.execute("SELECT value FROM seed").fetchall()
        observed["pending"] = pending_score_run_transaction(capture_root)
        raise RuntimeError("stop after recovered state read")

    monkeypatch.setattr(pipeline, "read_reentry_states", inspect_then_fail)

    with pytest.raises(RuntimeError, match="stop after recovered state read"):
        pipeline.score_pipeline(
            "2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True,
        )

    assert observed["value"] == [("before old pending run",)]
    assert observed["pending"]["run_id"] != previous.run_id
    assert load_score_run_transaction(capture_root, previous.run_id)["status"] == "RECOVERED_ROLLBACK"
    assert pending_score_run_transaction(capture_root) is None


def test_capture_exports_and_restores_committed_wal_rows_before_schema_mutation(capture_root, monkeypatch):
    capture_root.mkdir(parents=True)
    state = capture_root / "reentry_state.sqlite"
    writer = sqlite3.connect(state)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE seed (value INTEGER)")
        writer.execute("INSERT INTO seed VALUES (1)")
        writer.commit()
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        writer.execute("INSERT INTO seed VALUES (2)")
        writer.commit()
        main_only = capture_root.parent / "main_only.sqlite"
        main_only.write_bytes(state.read_bytes())
        with closing(sqlite3.connect(main_only)) as connection:
            assert connection.execute("SELECT value FROM seed").fetchall() == [(1,)]
        reader = pipeline.read_reentry_states

        def read_then_fail(path):
            pending = pending_score_run_transaction(capture_root)
            frozen = capture_root / "decision_inputs" / pending["capture_id"] / "pre_state/archive/reentry_state.sqlite"
            with closing(sqlite3.connect(f"{frozen.as_uri()}?immutable=1", uri=True)) as connection:
                assert connection.execute("SELECT value FROM seed").fetchall() == [(1,), (2,)]
            reader(path)
            writer.close()
            raise RuntimeError("failure after WAL-backed schema read")

        monkeypatch.setattr(pipeline, "read_reentry_states", read_then_fail)

        with pytest.raises(RuntimeError, match="failure after WAL-backed schema read"):
            pipeline.score_pipeline(
                "2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True,
            )

        with closing(sqlite3.connect(state)) as connection:
            assert connection.execute("SELECT value FROM seed").fetchall() == [(1,), (2,)]
            assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("seed",)]
        assert pending_score_run_transaction(capture_root) is None
    finally:
        writer.close()
