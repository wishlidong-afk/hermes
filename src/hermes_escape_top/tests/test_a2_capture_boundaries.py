"""A2 wiring preflight: existing boundaries, not an automatic capture feature."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from hermes_escape_top.core.data.decision_identity import scoring_logic_hash
from hermes_escape_top.core.data.run_transaction import (
    load_score_run_transaction,
    pending_score_run_transaction,
    recover_incomplete_score_run,
    score_run_transaction,
)
from hermes_escape_top.core.data.state_store import (
    latest_decision_statuses,
    latest_execution_confirmations,
    latest_score_payload_before,
    record_execution_confirmation,
)
from hermes_escape_top.core.reentry.store import read_reentry_states
from hermes_escape_top.core.safe_io import pipeline_lock


@pytest.mark.parametrize("reader", [
    latest_decision_statuses,
    latest_execution_confirmations,
    latest_score_payload_before,
    read_reentry_states,
])
def test_state_readers_can_change_existing_schema_before_scoring(tmp_path, reader):
    state = tmp_path / "state.sqlite"
    with sqlite3.connect(state) as connection:
        connection.execute("CREATE TABLE seed (value INTEGER)")
    before = state.read_bytes()

    if reader is latest_score_payload_before:
        assert reader(state, "2026-05-29") is None
    else:
        assert reader(state) == {}

    assert state.read_bytes() != before
    with sqlite3.connect(state) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'",
        )}
    assert tables - {"seed"}


@pytest.mark.parametrize("failure", ["exception", "interrupted"])
def test_registered_capture_files_share_business_rollback(tmp_path, failure):
    archive = tmp_path / "data/archive"
    archive.mkdir(parents=True)
    business = archive / "hermes_state.sqlite"
    business.write_bytes(b"previous business state")
    manifest = archive / "decision_inputs/capture/manifest.json"
    pre_state = manifest.parent / "pre_state/hermes_state.sqlite"

    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        context = score_run_transaction(
            archive, [business, manifest, pre_state], metadata={}, _lease=lease,
        )
        if failure == "exception":
            with pytest.raises(RuntimeError, match="capture fault"):
                with context as transaction:
                    pre_state.parent.mkdir(parents=True)
                    pre_state.write_bytes(b"captured pre-state")
                    manifest.write_bytes(b"binding")
                    business.write_bytes(b"partial business state")
                    raise RuntimeError("capture fault")
            expected = "ROLLED_BACK"
        else:
            # Leave the context open to exercise the same journal as crash recovery.
            transaction = context.__enter__()
            pre_state.parent.mkdir(parents=True)
            pre_state.write_bytes(b"captured pre-state")
            manifest.write_bytes(b"binding")
            business.write_bytes(b"partial business state")
            recovered = recover_incomplete_score_run(archive, _lease=lease)
            assert recovered["run_id"] == transaction.run_id
            expected = "RECOVERED_ROLLBACK"

    assert business.read_bytes() == b"previous business state"
    assert not manifest.exists()
    assert not pre_state.exists()
    assert pending_score_run_transaction(archive) is None
    assert load_score_run_transaction(archive, transaction.run_id)["status"] == expected


def test_registered_capture_survives_commit_but_temporary_backup_does_not(tmp_path):
    archive = tmp_path / "data/archive"
    archive.mkdir(parents=True)
    business = archive / "hermes_state.sqlite"
    before = b"previous business state"
    business.write_bytes(before)
    capture = archive / "decision_inputs/capture/pre_state/hermes_state.sqlite"
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with score_run_transaction(
            archive, [business, capture], metadata={}, _lease=lease,
        ) as transaction:
            capture.parent.mkdir(parents=True)
            capture.write_bytes(before)
            business.write_bytes(b"new business state")

    assert capture.read_bytes() == before
    assert business.read_bytes() == b"new business state"
    assert load_score_run_transaction(archive, transaction.run_id)["status"] == "COMMITTED"
    backups = archive / f".score_run_transactions/runs/{transaction.run_id}/backups"
    assert not backups.exists()


@pytest.mark.parametrize("case", ["directory", "outside_data_root"])
def test_capture_targets_must_be_registered_files_inside_data_root(tmp_path, case):
    archive = tmp_path / "data/archive"
    archive.mkdir(parents=True)
    if case == "directory":
        target = archive / "decision_inputs"
        target.mkdir()
        message = "not a regular file"
    else:
        target = tmp_path / "outside/manifest.json"
        message = "outside data root"
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with pytest.raises(ValueError, match=message):
            with score_run_transaction(archive, [target], metadata={}, _lease=lease):
                pytest.fail("invalid capture target entered transaction")
    assert pending_score_run_transaction(archive) is None


@pytest.mark.parametrize("case", ["missing", "wrong_root"])
def test_capture_transaction_requires_the_data_root_lease(tmp_path, case):
    archive = tmp_path / "data/archive"
    with pipeline_lock(path=tmp_path / "wrong/.pipeline.lock") as wrong_lease:
        lease = wrong_lease if case == "wrong_root" else None
        message = "path mismatch" if case == "wrong_root" else "invalid pipeline lease"
        with pytest.raises(RuntimeError, match=message):
            with score_run_transaction(
                archive, [archive / "capture.json"], metadata={}, _lease=lease,
            ):
                pytest.fail("capture entered without the correct lease")
    assert not (archive / "capture.json").exists()


def test_sqlite_logical_backup_contains_committed_wal_rows_missing_from_main_file(tmp_path):
    state = tmp_path / "state.sqlite"
    writer = sqlite3.connect(state)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE inputs (value INTEGER)")
        writer.execute("INSERT INTO inputs VALUES (1)")
        writer.commit()
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        writer.execute("INSERT INTO inputs VALUES (2)")
        writer.commit()
        before = state.read_bytes()
        wal = Path(f"{state}-wal")
        before_wal = wal.read_bytes()
        raw_copy = tmp_path / "raw.sqlite"
        raw_copy.write_bytes(before)
        with sqlite3.connect(raw_copy) as connection:
            assert connection.execute("SELECT value FROM inputs").fetchall() == [(1,)]

        logical = tmp_path / "logical.sqlite"
        with sqlite3.connect(f"{state.as_uri()}?mode=ro", uri=True) as source:
            with sqlite3.connect(logical) as destination:
                source.backup(destination)
        with sqlite3.connect(logical) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            assert connection.execute("SELECT value FROM inputs ORDER BY value").fetchall() == [(1,), (2,)]
        assert state.read_bytes() == before
        assert wal.read_bytes() == before_wal
    finally:
        writer.close()


def test_post_run_confirmation_is_not_the_consumed_pre_run_state(tmp_path):
    state = tmp_path / "state.sqlite"
    record_execution_confirmation(
        state, symbol="MSTR", tranche="T1", confirmed_at="2026-05-28T12:00:00+00:00",
    )
    before = latest_execution_confirmations(state)
    frozen = tmp_path / "pre_state.sqlite"
    with sqlite3.connect(f"{state.as_uri()}?mode=ro", uri=True) as source:
        with sqlite3.connect(frozen) as destination:
            source.backup(destination)
    record_execution_confirmation(
        state, symbol="MSTR", tranche="T2", confirmed_at="2026-05-29T12:00:00+00:00",
    )
    assert latest_execution_confirmations(state)["MSTR"]["tranche"] == "T2"
    assert latest_execution_confirmations(frozen) == before
    assert before["MSTR"]["tranche"] == "T1"


def test_pipeline_wiring_changes_identity_fingerprint_even_without_scoring_changes(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    pipeline = package / "pipeline.py"
    pipeline.write_text("SCORE = 1\n")
    before = scoring_logic_hash(package)
    reporting = package / "core/reporting"
    reporting.mkdir(parents=True)
    (reporting / "capture.py").write_text("CAPTURE = True\n")
    assert scoring_logic_hash(package) == before
    pipeline.write_text("# Automatic archive wiring would change these source bytes.\nSCORE = 1\n")
    assert scoring_logic_hash(package) != before
