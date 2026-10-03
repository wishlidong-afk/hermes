from __future__ import annotations

import json
import hashlib
import sqlite3
import os
import select
import signal
import subprocess
import sys
from contextlib import closing

import pytest

from hermes_escape_top.core.data.run_transaction import (
    load_score_run_transaction, pending_score_run_transaction, recover_incomplete_score_run, score_run_transaction,
)
from hermes_escape_top.core.safe_io import pipeline_lock
from hermes_escape_top.core.data import run_transaction
from test_runtime_retention import _module as _retention_module

AS_OF = "2026-05-29"
CAPTURE_ID = "a" * 32
NAMES = (
    "hermes_state.sqlite", "reentry_state.sqlite", "mirror_reference.sqlite", "flow_reference.sqlite",
    "audit_log.jsonl", "signal_journal.jsonl", f"soft_adapter_snapshot_{AS_OF}.json",
)


def _paths(tmp_path):
    archive = tmp_path / "data/archive"
    archive.mkdir(parents=True)
    business = [archive / name for name in NAMES]
    bundle = archive / "decision_inputs" / CAPTURE_ID
    return archive, business, [bundle / "manifest.json", bundle / "pre_state.json"]


def _context(archive, business, evidence, lease):
    return score_run_transaction(
        archive, business, metadata={"as_of": AS_OF, "run_type": "scheduled", "shadow": False},
        _lease=lease, evidence_artifacts=evidence, capture_id=CAPTURE_ID,
    )


def test_v2_registers_exact_business_and_evidence_files_before_any_write(tmp_path):
    archive, business, evidence = _paths(tmp_path)
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with pytest.raises(RuntimeError, match="stop before writes"):
            with _context(archive, business, evidence, lease) as transaction:
                record = pending_score_run_transaction(archive)
                assert record["schema_version"] == "hermes-score-run-transaction-v2"
                assert record["capture_id"] == CAPTURE_ID
                assert {row["path"] for row in record["artifacts"] if row["role"] == "BUSINESS"} == {
                    f"archive/{name}" for name in NAMES
                }
                assert {row["path"] for row in record["artifacts"] if row["role"] == "DECISION_INPUT_EVIDENCE"} == {
                    path.relative_to(archive.parent).as_posix() for path in evidence
                }
                raise RuntimeError("stop before writes")
    assert load_score_run_transaction(archive, transaction.run_id)["status"] == "ROLLED_BACK"
    assert not (archive / ".score_run_transactions/active.json").exists()


def test_v2_missing_final_binding_rolls_back_instead_of_committing(tmp_path):
    archive, business, evidence = _paths(tmp_path)
    business[-2].write_bytes(b"old journal")
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with pytest.raises(ValueError, match="input binding missing"):
            with _context(archive, business, evidence, lease) as transaction:
                business[-2].write_bytes(b"partial journal")
                evidence[0].parent.mkdir(parents=True, exist_ok=True)
                evidence[0].write_text("{}")
    assert business[-2].read_bytes() == b"old journal"
    assert not evidence[0].exists()
    assert load_score_run_transaction(archive, transaction.run_id)["status"] == "ROLLED_BACK"


def _finalize(transaction, evidence, lease):
    evidence[0].parent.mkdir(parents=True, exist_ok=True)
    evidence[1].write_bytes(b"frozen pre-state fixture")
    binding = {"run_id": transaction.run_id, "capture_id": CAPTURE_ID,
               "as_of": AS_OF, "decision_id": "decision-fixture", "input_hash": "b" * 64}
    manifest = {"schema_version": "hermes-in-run-input-binding-v1", "capture_mode": "IN_RUN_CAPTURE",
                "binding": binding, "files": [{"path": evidence[1].relative_to(transaction.archive_dir.parent).as_posix(),
                                                 "sha256": hashlib.sha256(evidence[1].read_bytes()).hexdigest()}]}
    evidence[0].write_text(json.dumps(manifest))
    digest = hashlib.sha256(evidence[0].read_bytes()).hexdigest()
    run_transaction.bind_score_run_inputs(
        transaction, manifest_path=evidence[0], expected_manifest_sha256=digest,
        decision_id=binding["decision_id"], input_hash=binding["input_hash"], _lease=lease,
    )
    return digest


def test_v2_committed_record_is_the_external_anchor_for_exact_evidence(tmp_path):
    archive, business, evidence = _paths(tmp_path)
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with _context(archive, business, evidence, lease) as transaction:
            for path in business:
                path.write_bytes(b"business fixture")
            digest = _finalize(transaction, evidence, lease)
    record = load_score_run_transaction(archive, transaction.run_id)
    assert record["status"] == "COMMITTED"
    assert record["input_binding"]["manifest_sha256"] == digest
    assert record["input_binding"]["decision_id"] == "decision-fixture"
    assert record["input_binding"]["input_hash"] == "b" * 64
    assert all(row.get("after_sha256") for row in record["artifacts"] if row["role"] == "DECISION_INPUT_EVIDENCE")


def test_v2_rollback_restores_committed_wal_rows_not_only_the_old_main_file(tmp_path):
    archive, business, evidence = _paths(tmp_path)
    state = business[0]
    connection = sqlite3.connect(state)
    connection.execute("CREATE TABLE old_state (value TEXT)")
    connection.commit()
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute("INSERT INTO old_state VALUES ('committed in WAL')")
    connection.commit()
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with pytest.raises(RuntimeError, match="fail after state"):
            with _context(archive, business, evidence, lease):
                connection.execute("UPDATE old_state SET value='partial new state'")
                connection.commit()
                connection.close()
                raise RuntimeError("fail after state")
    with closing(sqlite3.connect(state)) as restored:
        assert restored.execute("SELECT value FROM old_state").fetchall() == [("committed in WAL",)]


@pytest.mark.parametrize("case", ["missing_business", "extra_business", "duplicate", "outside", "existing_evidence", "symlink"])
def test_v2_registration_refuses_ambiguous_inventory_before_writer_enters(tmp_path, case):
    archive, business, evidence = _paths(tmp_path)
    if case == "missing_business":
        business.pop()
    elif case == "extra_business":
        business.append(archive / "extra.json")
    elif case == "duplicate":
        evidence.append(evidence[-1])
    elif case == "outside":
        evidence[-1] = tmp_path / "outside.json"
    elif case == "existing_evidence":
        evidence[0].parent.mkdir(parents=True)
        evidence[-1].write_bytes(b"existing evidence")
    else:
        evidence[0].parent.mkdir(parents=True)
        evidence[-1].symlink_to(tmp_path / "missing")
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with pytest.raises(ValueError):
            with _context(archive, business, evidence, lease):
                pytest.fail("writer must not enter")
    assert pending_score_run_transaction(archive) is None


@pytest.mark.parametrize("case", ["manifest", "evidence", "extra", "missing_business"])
def test_v2_rechecks_bound_files_at_commit_and_removes_failed_capture(tmp_path, case):
    archive, business, evidence = _paths(tmp_path)
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with pytest.raises(ValueError):
            with _context(archive, business, evidence, lease) as transaction:
                for path in business:
                    path.write_bytes(b"business fixture")
                _finalize(transaction, evidence, lease)
                if case == "manifest":
                    evidence[0].write_text("{}")
                elif case == "evidence":
                    evidence[-1].write_bytes(b"changed evidence")
                elif case == "extra":
                    (evidence[0].parent / "unexpected.json").write_text("{}")
                else:
                    business[0].unlink()
    assert load_score_run_transaction(archive, transaction.run_id)["status"] == "ROLLED_BACK"
    assert not any(path.is_file() for path in evidence[0].parent.rglob("*"))


def test_v2_committed_capture_and_backups_have_private_permissions(tmp_path):
    archive, business, evidence = _paths(tmp_path)
    business[-2].write_bytes(b"old journal")
    business[-2].chmod(0o640)
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with _context(archive, business, evidence, lease) as transaction:
            backup_root = archive / f".score_run_transactions/runs/{transaction.run_id}"
            assert backup_root.stat().st_mode & 0o777 == 0o700
            for path in business:
                path.write_bytes(b"business fixture")
            _finalize(transaction, evidence, lease)
    assert evidence[0].parent.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o400 for path in evidence)
    assert business[-2].stat().st_mode & 0o777 == 0o640


def test_cleanup_failure_after_committed_never_rewinds_business_or_evidence(tmp_path, monkeypatch):
    archive, business, evidence = _paths(tmp_path)
    business[-2].write_bytes(b"old journal")
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with monkeypatch.context() as fault:
            fault.setattr(run_transaction, "_clear_active", lambda *_: (_ for _ in ()).throw(OSError("cleanup failed")))
            with pytest.raises(OSError, match="cleanup failed"):
                with _context(archive, business, evidence, lease) as transaction:
                    for path in business:
                        path.write_bytes(b"committed business")
                    _finalize(transaction, evidence, lease)
        assert load_score_run_transaction(archive, transaction.run_id)["status"] == "COMMITTED"
        plan = _retention_module().build_prune_plan(
            live_root=tmp_path / "unused-live", backup_root=tmp_path / "unused-backups",
            archive_dir=archive, keep_transactions=0, max_transaction_bytes=0,
        )
        assert plan["summary"]["score_transaction"]["protected"] == [
            str(archive / f".score_run_transactions/runs/{transaction.run_id}"),
        ]
        assert not plan["delete"]
        before = {path: path.read_bytes() for path in business + evidence}
        assert recover_incomplete_score_run(archive, _lease=lease) is None
    assert {path: path.read_bytes() for path in business + evidence} == before
    assert pending_score_run_transaction(archive) is None


_KILLED_WRITER = '''
import hashlib, json, os, socket, sqlite3, sys
from pathlib import Path
from hermes_escape_top.core.data import run_transaction as module
from hermes_escape_top.core.safe_io import pipeline_lock
socket.socket.connect = lambda *_: (_ for _ in ()).throw(RuntimeError("network forbidden"))
archive, phase = Path(sys.argv[1]), sys.argv[2]
names = ("hermes_state.sqlite", "reentry_state.sqlite", "mirror_reference.sqlite", "flow_reference.sqlite",
         "audit_log.jsonl", "signal_journal.jsonl", "soft_adapter_snapshot_2026-05-29.json")
business = [archive / name for name in names]
capture_id = "a" * 32
bundle = archive / "decision_inputs" / capture_id
evidence = [bundle / "manifest.json", bundle / "pre_state.json"]
connection = sqlite3.connect(business[0])
connection.execute("PRAGMA journal_mode=WAL")
connection.execute("PRAGMA wal_autocheckpoint=0")
connection.execute("INSERT INTO old_state VALUES ('pre-run WAL')")
connection.commit()

def checkpoint(transaction):
    record = module.load_score_run_transaction(archive, transaction.run_id)
    print(json.dumps({"pid": os.getpid(), "run_id": transaction.run_id, "status": record["status"]}), flush=True)
    sys.stdin.readline()
    raise RuntimeError("parent must kill child")

with pipeline_lock(path=archive / ".pipeline.lock") as lease:
    with module.score_run_transaction(archive, business,
        metadata={"as_of": "2026-05-29", "run_type": "scheduled", "shadow": False},
        _lease=lease, evidence_artifacts=evidence, capture_id=capture_id) as transaction:
        connection.execute("UPDATE old_state SET value='new state'")
        connection.commit()
        evidence[1].write_bytes(b"partial capture")
        if phase == "during_write":
            checkpoint(transaction)
        binding = {"run_id": transaction.run_id, "capture_id": capture_id, "as_of": "2026-05-29",
                   "decision_id": "decision-fixture", "input_hash": "b" * 64}
        evidence[0].write_text(json.dumps({"schema_version": "hermes-in-run-input-binding-v1",
            "capture_mode": "IN_RUN_CAPTURE", "binding": binding,
            "files": [{"path": evidence[1].relative_to(archive.parent).as_posix(),
                       "sha256": hashlib.sha256(evidence[1].read_bytes()).hexdigest()}]}))
        module.bind_score_run_inputs(transaction, manifest_path=evidence[0],
            expected_manifest_sha256=hashlib.sha256(evidence[0].read_bytes()).hexdigest(),
            decision_id="decision-fixture", input_hash="b" * 64, _lease=lease)
        if phase == "after_binding":
            checkpoint(transaction)
        module._clear_active = lambda *_: checkpoint(transaction)
'''

_NEXT_RECOVERY = '''
import json, os, socket, sys
from pathlib import Path
from hermes_escape_top.core.data.run_transaction import recover_incomplete_score_run
from hermes_escape_top.core.safe_io import pipeline_lock
socket.socket.connect = lambda *_: (_ for _ in ()).throw(RuntimeError("network forbidden"))
archive = Path(sys.argv[1])
with pipeline_lock(path=archive / ".pipeline.lock") as lease:
    recovered = recover_incomplete_score_run(archive, _lease=lease)
print(json.dumps({"pid": os.getpid(), "recovered": recovered}))
'''


@pytest.mark.parametrize("phase", ["during_write", "after_binding", "after_commit"])
def test_sigkill_then_a_different_process_recovers_or_preserves_committed_v2(tmp_path, phase):
    archive, business, evidence = _paths(tmp_path)
    for path in business:
        if path.suffix == ".sqlite":
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("CREATE TABLE old_state (value TEXT)")
                connection.execute("INSERT INTO old_state VALUES ('before')")
                connection.commit()
        else:
            path.write_bytes(b"before")
    child = subprocess.Popen([sys.executable, "-c", _KILLED_WRITER, str(archive), phase],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([child.stdout], [], [], 20)[0], "child did not reach kill checkpoint"
        line = child.stdout.readline()
        assert line, child.stderr.read()
        observed = json.loads(line)
        assert observed["status"] == ("COMMITTED" if phase == "after_commit" else "PENDING")
        os.kill(child.pid, signal.SIGKILL)
        child.wait(timeout=10)
        assert child.returncode == -signal.SIGKILL
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=10)
    result = subprocess.run([sys.executable, "-c", _NEXT_RECOVERY, str(archive)],
                            capture_output=True, text=True, check=True, timeout=20)
    recovered = json.loads(result.stdout)
    assert recovered["pid"] not in {observed["pid"], os.getpid()}
    assert pending_score_run_transaction(archive) is None
    with closing(sqlite3.connect(business[0])) as connection:
        values = connection.execute("SELECT value FROM old_state ORDER BY rowid").fetchall()
    if phase == "after_commit":
        assert recovered["recovered"] is None
        assert values == [("new state",), ("new state",)]
        assert all(path.exists() for path in evidence)
        assert load_score_run_transaction(archive, observed["run_id"])["status"] == "COMMITTED"
    else:
        assert values == [("before",), ("pre-run WAL",)]
        assert recovered["recovered"]["status"] == "RECOVERED_ROLLBACK"
        assert not evidence[0].parent.exists()


def test_recovery_verifies_all_backups_before_restoring_the_first_file(tmp_path):
    archive, business, evidence = _paths(tmp_path)
    business[-3].write_bytes(b"old audit")
    business[-2].write_bytes(b"old journal")
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        context = _context(archive, business, evidence, lease)
        transaction = context.__enter__()
        business[-3].write_bytes(b"partial audit")
        business[-2].write_bytes(b"partial journal")
        backup = archive / f".score_run_transactions/runs/{transaction.run_id}/backups/archive/signal_journal.jsonl"
        backup.chmod(0o600)
        backup.write_bytes(b"bad backup")
        with pytest.raises(run_transaction.PersistenceRecoveryError, match="digest mismatch"):
            recover_incomplete_score_run(archive, _lease=lease)
        assert business[-3].read_bytes() == b"partial audit"
        assert business[-2].read_bytes() == b"partial journal"
        assert pending_score_run_transaction(archive)["status"] == "PENDING"
        backup.write_bytes(b"old journal")
        recover_incomplete_score_run(archive, _lease=lease)
    assert business[-3].read_bytes() == b"old audit"
    assert business[-2].read_bytes() == b"old journal"


def test_active_pointer_cannot_escape_the_run_directory(tmp_path):
    archive, _business, _evidence = _paths(tmp_path)
    root = archive / ".score_run_transactions"
    root.mkdir()
    (root / "runs").mkdir()
    (root / "active.json").write_text(json.dumps({"run_id": "../../outside"}))
    outside = archive / "outside"
    outside.mkdir()
    (outside / "manifest.json").write_text(json.dumps({"run_id": "../../outside", "status": "COMMITTED"}))
    with pytest.raises(run_transaction.PersistenceRecoveryError, match="invalid.*run_id"):
        pending_score_run_transaction(archive)


def test_v2_accepts_release_data_alias_but_keeps_physical_inventory(tmp_path):
    archive, business, evidence = _paths(tmp_path)
    release = tmp_path / "release"
    release.mkdir()
    (release / "data").symlink_to(archive.parent, target_is_directory=True)
    alias_archive = release / "data/archive"
    alias_business = [alias_archive / path.name for path in business]
    alias_evidence = [alias_archive / "decision_inputs" / CAPTURE_ID / path.name for path in evidence]
    with pipeline_lock(path=alias_archive / ".pipeline.lock") as lease:
        with _context(alias_archive, alias_business, alias_evidence, lease) as transaction:
            for path in alias_business:
                path.write_bytes(b"business fixture")
            _finalize(transaction, evidence, lease)
    record = load_score_run_transaction(archive, transaction.run_id)
    assert record["status"] == "COMMITTED"
    assert {row["path"] for row in record["artifacts"] if row["role"] == "BUSINESS"} == {
        f"archive/{name}" for name in NAMES
    }


def test_v2_recovery_rejects_incorrect_backup_format_before_any_restore(tmp_path):
    archive, business, evidence = _paths(tmp_path)
    with closing(sqlite3.connect(business[0])) as connection:
        connection.execute("CREATE TABLE old_state (value TEXT)")
        connection.commit()
    business[-2].write_bytes(b"old journal")
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        context = _context(archive, business, evidence, lease)
        transaction = context.__enter__()
        business[-2].write_bytes(b"partial journal")
        manifest = archive / f".score_run_transactions/runs/{transaction.run_id}/manifest.json"
        record = json.loads(manifest.read_bytes())
        record["artifacts"][0]["snapshot_format"] = "BYTES"
        manifest.write_text(json.dumps(record))
        with pytest.raises(run_transaction.PersistenceRecoveryError, match="backup metadata"):
            recover_incomplete_score_run(archive, _lease=lease)
        assert business[-2].read_bytes() == b"partial journal"
        record["artifacts"][0]["snapshot_format"] = "SQLITE_BACKUP"
        manifest.write_text(json.dumps(record))
        recover_incomplete_score_run(archive, _lease=lease)
    assert business[-2].read_bytes() == b"old journal"


def test_v2_active_pointer_refuses_a_legacy_writer_instead_of_silent_v1_recovery(tmp_path):
    archive, business, evidence = _paths(tmp_path)
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        context = _context(archive, business, evidence, lease)
        transaction = context.__enter__()
        pointer = json.loads((archive / ".score_run_transactions/active.json").read_bytes())
        assert pointer["schema_version"] == "hermes-score-run-transaction-v2"
        assert pointer["v2_run_id"] == transaction.run_id
        legacy_manifest = archive / ".score_run_transactions/runs" / pointer["run_id"] / "manifest.json"
        assert not legacy_manifest.exists()
        assert pending_score_run_transaction(archive)["run_id"] == transaction.run_id
        recover_incomplete_score_run(archive, _lease=lease)


@pytest.mark.parametrize("phase", ["before_commit", "after_commit"])
def test_commit_publish_failure_respects_the_durable_commit_boundary(tmp_path, monkeypatch, phase):
    archive, business, evidence = _paths(tmp_path)
    business[-2].write_bytes(b"before journal")
    write_manifest = run_transaction._write_manifest

    def fail_commit(path, record):
        if record["status"] == "COMMITTED":
            if phase == "after_commit":
                write_manifest(path, record)
            raise OSError("commit publish failed")
        return write_manifest(path, record)

    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with monkeypatch.context() as fault:
            fault.setattr(run_transaction, "_write_manifest", fail_commit)
            with pytest.raises(OSError, match="commit publish failed"):
                with _context(archive, business, evidence, lease) as transaction:
                    for path in business:
                        path.write_bytes(b"after business")
                    _finalize(transaction, evidence, lease)
        if phase == "before_commit":
            assert business[-2].read_bytes() == b"before journal"
            assert not evidence[0].parent.exists()
            assert load_score_run_transaction(archive, transaction.run_id)["status"] == "ROLLED_BACK"
        else:
            assert business[-2].read_bytes() == b"after business"
            assert load_score_run_transaction(archive, transaction.run_id)["status"] == "COMMITTED"
            recover_incomplete_score_run(archive, _lease=lease)
            assert all(path.exists() for path in evidence)


def test_v2_syncs_committed_wal_before_publishing_commit(tmp_path, monkeypatch):
    archive, business, evidence = _paths(tmp_path)
    synced = []
    sync_file = run_transaction._sync_file

    def trace_sync(path):
        synced.append(path)
        sync_file(path)

    monkeypatch.setattr(run_transaction, "_sync_file", trace_sync)
    with closing(sqlite3.connect(business[0])) as connection:
        connection.execute("CREATE TABLE old_state (value TEXT)")
        connection.execute("INSERT INTO old_state VALUES ('before')")
        connection.commit()
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        with pipeline_lock(path=archive / ".pipeline.lock") as lease:
            with _context(archive, business, evidence, lease) as transaction:
                connection.execute("UPDATE old_state SET value='after'")
                connection.commit()
                wal = business[0].with_name(business[0].name + "-wal")
                assert wal.is_file()
                for path in business[1:]:
                    path.write_bytes(b"business fixture")
                _finalize(transaction, evidence, lease)
        assert wal in synced
        assert load_score_run_transaction(archive, transaction.run_id)["status"] == "COMMITTED"


@pytest.mark.parametrize("release_alias", [False, True])
def test_v2_refuses_internal_self_alias_even_under_release_alias(tmp_path, release_alias):
    archive, business, evidence = _paths(tmp_path)
    (archive.parent / "loop").symlink_to(archive.parent, target_is_directory=True)
    root = archive.parent
    if release_alias:
        release = tmp_path / "release"
        release.mkdir()
        (release / "data").symlink_to(root, target_is_directory=True)
        root = release / "data"
    alias_archive = root / "loop/archive"
    aliases = [alias_archive / path.name for path in business]
    alias_evidence = [alias_archive / "decision_inputs" / CAPTURE_ID / path.name for path in evidence]
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with pytest.raises(ValueError, match="symlink"):
            with _context(archive, aliases, alias_evidence, lease):
                pytest.fail("internal alias must not enter the writer")


@pytest.mark.parametrize("linked_part", ["root", "runs"])
def test_v2_refuses_linked_journal_before_any_external_write(tmp_path, linked_part):
    archive, business, evidence = _paths(tmp_path)
    outside = tmp_path / "outside-journal"
    outside.mkdir()
    journal = archive / ".score_run_transactions"
    if linked_part == "runs":
        journal.mkdir()
        journal = journal / "runs"
    journal.symlink_to(outside, target_is_directory=True)
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with pytest.raises(run_transaction.PersistenceRecoveryError, match="journal.*symlink"):
            with _context(archive, business, evidence, lease):
                pytest.fail("external journal must not enter the writer")
    assert not list(outside.iterdir())


@pytest.mark.parametrize("reader", ["pending", "recover"])
def test_transaction_readers_refuse_dangling_active_pointer(tmp_path, reader):
    archive, _business, _evidence = _paths(tmp_path)
    journal = archive / ".score_run_transactions"
    journal.mkdir()
    (journal / "active.json").symlink_to(tmp_path / "missing-active")
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with pytest.raises(run_transaction.PersistenceRecoveryError, match="journal.*symlink"):
            if reader == "pending":
                pending_score_run_transaction(archive)
            else:
                recover_incomplete_score_run(archive, _lease=lease)
