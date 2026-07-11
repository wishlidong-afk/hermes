from __future__ import annotations

from pathlib import Path

import pytest

from hermes_escape_top.core.data.run_transaction import (
    load_score_run_transaction,
    pending_score_run_transaction,
    recover_incomplete_score_run,
    score_run_transaction,
)
from hermes_escape_top.core.safe_io import pipeline_lock


def test_score_run_transaction_commits_all_changes(tmp_path: Path) -> None:
    archive = tmp_path / "data" / "archive"
    existing = archive / "state.sqlite"
    created = archive / "audit.jsonl"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"before")

    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with score_run_transaction(
            archive,
            [existing, created],
            metadata={"as_of": "2026-07-10", "run_type": "scheduled"},
            _lease=lease,
        ) as transaction:
            existing.write_bytes(b"after")
            created.write_bytes(b"new")
            pending = pending_score_run_transaction(archive)
            assert pending is not None
            assert pending["run_id"] == transaction.run_id
            assert load_score_run_transaction(archive, transaction.run_id)["status"] == "PENDING"

    assert existing.read_bytes() == b"after"
    assert created.read_bytes() == b"new"
    assert pending_score_run_transaction(archive) is None
    assert load_score_run_transaction(archive, transaction.run_id)["status"] == "COMMITTED"


def test_score_run_transaction_rolls_back_existing_and_new_files(tmp_path: Path) -> None:
    archive = tmp_path / "data" / "archive"
    existing = archive / "state.sqlite"
    created = archive / "audit.jsonl"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"before")

    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with pytest.raises(RuntimeError, match="fault after state"):
            with score_run_transaction(
                archive,
                [existing, created],
                metadata={"as_of": "2026-07-10"},
                _lease=lease,
            ) as transaction:
                existing.write_bytes(b"partial")
                created.write_bytes(b"partial")
                raise RuntimeError("fault after state")

    assert existing.read_bytes() == b"before"
    assert not created.exists()
    assert pending_score_run_transaction(archive) is None
    record = load_score_run_transaction(archive, transaction.run_id)
    assert record["status"] == "ROLLED_BACK"
    assert record["failure_type"] == "RuntimeError"


def test_next_run_recovers_a_process_killed_during_persistence(tmp_path: Path) -> None:
    archive = tmp_path / "data" / "archive"
    existing = archive / "state.sqlite"
    created = archive / "audit.jsonl"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"before")

    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        context = score_run_transaction(
            archive,
            [existing, created],
            metadata={"as_of": "2026-07-10"},
            _lease=lease,
        )
        transaction = context.__enter__()
        existing.write_bytes(b"partial")
        created.write_bytes(b"partial")

        recovered = recover_incomplete_score_run(archive, _lease=lease)

    assert recovered is not None
    assert recovered["run_id"] == transaction.run_id
    assert recovered["status"] == "RECOVERED_ROLLBACK"
    assert existing.read_bytes() == b"before"
    assert not created.exists()
    assert pending_score_run_transaction(archive) is None
    assert load_score_run_transaction(archive, transaction.run_id)["status"] == "RECOVERED_ROLLBACK"


def test_committed_run_is_not_recovered_again(tmp_path: Path) -> None:
    archive = tmp_path / "data" / "archive"
    artifact = archive / "state.sqlite"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"before")

    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with score_run_transaction(archive, [artifact], metadata={}, _lease=lease) as transaction:
            artifact.write_bytes(b"committed")

        assert recover_incomplete_score_run(archive, _lease=lease) is None
    assert artifact.read_bytes() == b"committed"
    assert load_score_run_transaction(archive, transaction.run_id)["status"] == "COMMITTED"


def test_recovery_and_transaction_reject_calls_without_the_pipeline_lease(tmp_path: Path) -> None:
    archive = tmp_path / "data" / "archive"
    archive.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="invalid pipeline lease"):
        recover_incomplete_score_run(archive, _lease=None)
    with pytest.raises(RuntimeError, match="invalid pipeline lease"):
        with score_run_transaction(archive, [], metadata={}, _lease=None):
            pass
