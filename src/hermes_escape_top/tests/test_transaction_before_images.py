from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
from contextlib import closing

import pytest

from hermes_escape_top.core.data import run_transaction
from hermes_escape_top.core.safe_io import pipeline_lock

AS_OF = "2026-05-29"
CAPTURE_ID = "c" * 32
NAMES = (
    "hermes_state.sqlite", "reentry_state.sqlite", "mirror_reference.sqlite", "flow_reference.sqlite",
    "audit_log.jsonl", "signal_journal.jsonl", f"soft_adapter_snapshot_{AS_OF}.json",
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("network forbidden in before-image tests"))


def _seed(tmp_path):
    archive = tmp_path / "data/archive"
    archive.mkdir(parents=True)
    business = [archive / name for name in NAMES]
    for path in business:
        if path.suffix == ".sqlite":
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("CREATE TABLE old_state (value TEXT)")
                connection.execute("INSERT INTO old_state VALUES ('before run')")
                connection.commit()
        else:
            path.write_bytes(b'{"value":"before run"}\n')
    bundle = archive / "decision_inputs" / CAPTURE_ID
    evidence = [bundle / "manifest.json", bundle / "pre_state.json"]
    evidence.extend(bundle / "pre_state/archive" / path.name for path in business if path.exists())
    return archive, business, evidence


def _context(archive, business, evidence, lease):
    return run_transaction.score_run_transaction(
        archive, business, metadata={"as_of": AS_OF, "run_type": "scheduled", "shadow": False},
        _lease=lease, evidence_artifacts=evidence, capture_id=CAPTURE_ID,
    )


def _finalize(transaction, evidence, state, lease):
    evidence[1].write_text(json.dumps(state))
    manifest = {
        "schema_version": "hermes-in-run-input-binding-v1", "capture_mode": "IN_RUN_CAPTURE",
        "binding": {"run_id": transaction.run_id, "capture_id": CAPTURE_ID, "as_of": AS_OF,
                    "decision_id": "isolated-before-images-fixture", "input_hash": "d" * 64},
        "files": [{"path": path.relative_to(transaction.archive_dir.parent).as_posix(),
                   "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in evidence[1:]],
    }
    evidence[0].write_text(json.dumps(manifest))
    run_transaction.bind_score_run_inputs(
        transaction, manifest_path=evidence[0],
        expected_manifest_sha256=hashlib.sha256(evidence[0].read_bytes()).hexdigest(),
        decision_id=manifest["binding"]["decision_id"], input_hash=manifest["binding"]["input_hash"], _lease=lease,
    )


def test_export_uses_prepared_before_images_even_after_business_writes(tmp_path):
    archive, business, evidence = _seed(tmp_path)
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with _context(archive, business, evidence, lease) as transaction:
            for path in business:
                if path.suffix == ".sqlite":
                    with closing(sqlite3.connect(path)) as connection:
                        connection.execute("UPDATE old_state SET value='after run'")
                        connection.commit()
                else:
                    path.write_bytes(b'{"value":"after run"}\n')
            state = run_transaction.export_score_run_before_images(transaction, _lease=lease)
            assert state["capture_mode"] == "V2_PREPARED_BEFORE_IMAGES"
            assert state["binding"] == {"run_id": transaction.run_id, "capture_id": CAPTURE_ID, "as_of": AS_OF}
            assert set(state["artifacts"]) == {f"archive/{name}" for name in NAMES}
            for source, entry in state["artifacts"].items():
                frozen = archive.parent / entry["path"]
                assert entry["availability"] == "PRESENT"
                assert hashlib.sha256(frozen.read_bytes()).hexdigest() == entry["sha256"]
                assert frozen.stat().st_mode & 0o777 == 0o400
                if source.endswith(".sqlite"):
                    assert entry["snapshot_format"] == "SQLITE_BACKUP"
                    with closing(sqlite3.connect(f"{frozen.as_uri()}?immutable=1", uri=True)) as connection:
                        assert connection.execute("SELECT value FROM old_state").fetchall() == [("before run",)]
                else:
                    assert frozen.read_bytes() == b'{"value":"before run"}\n'
            _finalize(transaction, evidence, state, lease)
    assert run_transaction.load_score_run_transaction(archive, transaction.run_id)["status"] == "COMMITTED"
    assert all(path.is_file() for path in evidence)
    assert not (archive / f".score_run_transactions/runs/{transaction.run_id}/backups").exists()


@pytest.mark.parametrize("key,value", [("snapshot_format", "BYTES"), ("before_mode", None),
                                     ("before_mode", -1), ("before_mode", True)])
def test_export_rejects_mislabeled_backup_before_copying_any_file(tmp_path, key, value):
    archive, business, evidence = _seed(tmp_path)
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with pytest.raises(RuntimeError, match="end probe"):
            with _context(archive, business, evidence, lease) as transaction:
                manifest = archive / f".score_run_transactions/runs/{transaction.run_id}/manifest.json"
                original = manifest.read_bytes()
                changed = json.loads(original)
                changed["artifacts"][0][key] = value
                manifest.write_text(json.dumps(changed))
                try:
                    with pytest.raises(ValueError, match="backup metadata"):
                        run_transaction.export_score_run_before_images(transaction, _lease=lease)
                    assert not any(path.exists() for path in evidence)
                finally:
                    manifest.write_bytes(original)
                raise RuntimeError("end probe")


def test_export_includes_committed_wal_rows_without_rereading_changed_state(tmp_path):
    archive, business, evidence = _seed(tmp_path)
    with closing(sqlite3.connect(business[0])) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("INSERT INTO old_state VALUES ('committed in WAL')")
        connection.commit()
        main_before = business[0].read_bytes()
        wal = business[0].with_name(business[0].name + "-wal")
        wal_before = wal.read_bytes()
        with pipeline_lock(path=archive / ".pipeline.lock") as lease:
            with _context(archive, business, evidence, lease) as transaction:
                assert business[0].read_bytes() == main_before
                assert wal.read_bytes() == wal_before
                connection.execute("DELETE FROM old_state")
                connection.execute("INSERT INTO old_state VALUES ('only new state')")
                connection.commit()
                source_bytes = {path: path.read_bytes() for path in business + [wal]}
                state = run_transaction.export_score_run_before_images(transaction, _lease=lease)
                assert {path: path.read_bytes() for path in source_bytes} == source_bytes
                frozen = archive.parent / state["artifacts"]["archive/hermes_state.sqlite"]["path"]
                with closing(sqlite3.connect(f"{frozen.as_uri()}?immutable=1", uri=True)) as old:
                    assert old.execute("SELECT value FROM old_state ORDER BY value").fetchall() == [
                        ("before run",), ("committed in WAL",),
                    ]
                _finalize(transaction, evidence, state, lease)


@pytest.mark.parametrize("missing", [NAMES[:1], NAMES])
def test_export_preserves_explicit_absence_without_creating_empty_database(tmp_path, missing):
    archive, business, evidence = _seed(tmp_path)
    for path in business:
        if path.name in missing:
            path.unlink()
    evidence = [path for path in evidence if path.name not in missing]
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with _context(archive, business, evidence, lease) as transaction:
            state = run_transaction.export_score_run_before_images(transaction, _lease=lease)
            for name in missing:
                entry = state["artifacts"][f"archive/{name}"]
                assert entry == {"availability": "ABSENT", "path": None, "sha256": None,
                                 "snapshot_format": "SQLITE_BACKUP" if name.endswith(".sqlite") else "BYTES",
                                 "before_mode": None}
                assert not (business[0].parent / name).exists()
                assert not (evidence[0].parent / "pre_state/archive" / name).exists()
            for path in business:
                if path.name in missing:
                    path.write_bytes(b"new business fixture, not a pre-state database")
            _finalize(transaction, evidence, state, lease)


def test_export_copy_failure_cleans_partial_files_and_can_be_retried_in_same_transaction(tmp_path, monkeypatch):
    archive, business, evidence = _seed(tmp_path)
    original_copy = run_transaction.shutil.copyfileobj
    calls = 0

    def fail_second(original, output):
        nonlocal calls
        calls += 1
        original_copy(original, output)
        if calls == 2:
            raise OSError("copy interrupted")

    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with _context(archive, business, evidence, lease) as transaction:
            with monkeypatch.context() as fault:
                fault.setattr(run_transaction.shutil, "copyfileobj", fail_second)
                with pytest.raises(OSError, match="copy interrupted"):
                    run_transaction.export_score_run_before_images(transaction, _lease=lease)
            assert not any(path.exists() for path in evidence)
            state = run_transaction.export_score_run_before_images(transaction, _lease=lease)
            _finalize(transaction, evidence, state, lease)


def test_transaction_failure_removes_export_and_restores_business_files(tmp_path):
    archive, business, evidence = _seed(tmp_path)
    before = {path: path.read_bytes() for path in business if path.suffix != ".sqlite"}
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with pytest.raises(RuntimeError, match="run failed"):
            with _context(archive, business, evidence, lease) as transaction:
                run_transaction.export_score_run_before_images(transaction, _lease=lease)
                business[-1].write_bytes(b"failed new state")
                raise RuntimeError("run failed")
    assert {path: path.read_bytes() for path in before} == before
    for path in business:
        if path.suffix == ".sqlite":
            with closing(sqlite3.connect(path)) as connection:
                assert connection.execute("SELECT value FROM old_state").fetchall() == [("before run",)]
    assert not evidence[0].parent.exists()
    assert run_transaction.load_score_run_transaction(archive, transaction.run_id)["status"] == "ROLLED_BACK"


@pytest.mark.parametrize("case", ["missing_registration", "extra_registration", "existing_target", "target_symlink"])
def test_export_refuses_unregistered_or_occupied_targets_before_any_copy(tmp_path, case):
    archive, business, evidence = _seed(tmp_path)
    if case == "missing_registration":
        evidence.pop()
    elif case == "extra_registration":
        evidence.append(evidence[0].parent / "pre_state/unexpected.json")
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with pytest.raises(RuntimeError, match="end probe"):
            with _context(archive, business, evidence, lease) as transaction:
                target = evidence[-1]
                if case in {"existing_target", "target_symlink"}:
                    target.parent.mkdir(parents=True)
                    if case == "existing_target":
                        target.write_bytes(b"do not overwrite")
                    else:
                        target.symlink_to(tmp_path / "missing-target")
                try:
                    with pytest.raises(ValueError):
                        run_transaction.export_score_run_before_images(transaction, _lease=lease)
                    assert not any(path.exists() for path in evidence[:-1])
                    if case == "existing_target":
                        assert target.read_bytes() == b"do not overwrite"
                    elif case == "target_symlink":
                        assert target.is_symlink()
                finally:
                    if target.is_symlink():
                        target.unlink()
                raise RuntimeError("end probe")


@pytest.mark.parametrize("case", ["changed", "missing", "symlink"])
def test_export_rejects_damaged_last_backup_before_copying_earlier_files(tmp_path, case):
    archive, business, evidence = _seed(tmp_path)
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with pytest.raises(RuntimeError, match="end probe"):
            with _context(archive, business, evidence, lease) as transaction:
                backup = archive / f".score_run_transactions/runs/{transaction.run_id}/backups/archive/{NAMES[-1]}"
                original = backup.read_bytes()
                backup.chmod(0o600)
                if case == "changed":
                    backup.write_bytes(b"corrupted backup")
                elif case == "missing":
                    backup.unlink()
                else:
                    backup.unlink()
                    backup.symlink_to(business[-1])
                try:
                    with pytest.raises((ValueError, FileNotFoundError, run_transaction.PersistenceRecoveryError)):
                        run_transaction.export_score_run_before_images(transaction, _lease=lease)
                    assert not any(path.exists() for path in evidence)
                finally:
                    if backup.is_symlink():
                        backup.unlink()
                    backup.write_bytes(original)
                    backup.chmod(0o400)
                raise RuntimeError("end probe")


@pytest.mark.parametrize("case", ["wrong_run", "wrong_capture", "no_lease", "wrong_root", "inactive_lease"])
def test_export_requires_matching_transaction_and_current_lease(tmp_path, case):
    archive, business, evidence = _seed(tmp_path)
    with pipeline_lock(path=tmp_path / "expired.pipeline.lock") as expired_lease:
        pass
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with pytest.raises(RuntimeError, match="end probe"):
            with _context(archive, business, evidence, lease) as transaction:
                candidate = transaction
                candidate_lease = lease
                if case == "wrong_run":
                    candidate = run_transaction.ScoreRunTransaction("wrong-run", archive, CAPTURE_ID)
                elif case == "wrong_capture":
                    candidate = run_transaction.ScoreRunTransaction(transaction.run_id, archive, "e" * 32)
                elif case == "no_lease":
                    candidate_lease = None
                elif case == "inactive_lease":
                    candidate_lease = expired_lease
                if case == "wrong_root":
                    with pipeline_lock(path=tmp_path / "other.pipeline.lock") as other_lease:
                        with pytest.raises(RuntimeError, match="path mismatch"):
                            run_transaction.export_score_run_before_images(candidate, _lease=other_lease)
                else:
                    with pytest.raises((ValueError, RuntimeError)):
                        run_transaction.export_score_run_before_images(candidate, _lease=candidate_lease)
                assert not any(path.exists() for path in evidence)
                raise RuntimeError("end probe")


def test_export_refuses_v1_and_already_committed_transaction(tmp_path):
    archive, business, evidence = _seed(tmp_path)
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with run_transaction.score_run_transaction(archive, business, metadata={}, _lease=lease) as legacy:
            with pytest.raises(ValueError, match="matching pending v2"):
                run_transaction.export_score_run_before_images(legacy, _lease=lease)
        with _context(archive, business, evidence, lease) as transaction:
            state = run_transaction.export_score_run_before_images(transaction, _lease=lease)
            _finalize(transaction, evidence, state, lease)
        before = {path: path.read_bytes() for path in evidence}
        with pytest.raises(ValueError, match="matching pending v2"):
            run_transaction.export_score_run_before_images(transaction, _lease=lease)
        assert {path: path.read_bytes() for path in evidence} == before


def test_offline_capture_still_refuses_pending_transaction(tmp_path):
    from hermes_escape_top.config import load_config
    from hermes_escape_top.core.data.store import LocalStore
    from hermes_escape_top.core.reporting.decision_inputs import capture_pre_run_state

    archive, business, evidence = _seed(tmp_path)
    config = load_config()
    config["paths"] = {**config["paths"], "history_dir": str(tmp_path / "data/history"),
                       "legacy_history_dir": str(tmp_path / "data/legacy"), "archive_dir": str(archive)}
    store = LocalStore(config)
    destination = tmp_path / "must-not-exist"
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with pytest.raises(RuntimeError, match="end probe"):
            with _context(archive, business, evidence, lease):
                with pytest.raises(ValueError, match="recovery of the pending score run"):
                    capture_pre_run_state(AS_OF, store=store, destination=destination, _lease=lease)
                assert not destination.exists()
                raise RuntimeError("end probe")
