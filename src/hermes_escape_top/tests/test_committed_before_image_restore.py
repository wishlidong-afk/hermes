from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
from contextlib import ExitStack, closing

import pytest

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data import run_transaction
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.core.safe_io import pipeline_lock

AS_OF = "2026-05-29"
CAPTURE = "e" * 32
DECISION = "offline-restore-fixture"
INPUT_HASH = "d" * 64
NAMES = (
    "hermes_state.sqlite", "reentry_state.sqlite", "mirror_reference.sqlite", "flow_reference.sqlite",
    "audit_log.jsonl", "signal_journal.jsonl", f"soft_adapter_snapshot_{AS_OF}.json",
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("network forbidden in restore"))


def _commit(tmp_path, *, missing=(), wal=False):
    config = load_config()
    root = tmp_path / "source/data"
    config["paths"] = {**config["paths"], "archive_dir": str(root / "archive"),
                       "history_dir": str(root / "history"), "legacy_history_dir": str(root / "legacy")}
    store = LocalStore(config)
    archive = store.archive_dir
    archive.mkdir(parents=True, exist_ok=True)
    business = [archive / name for name in NAMES]
    for path in business:
        if path.name in missing:
            continue
        if path.suffix == ".sqlite":
            with closing(sqlite3.connect(path)) as db:
                db.execute("CREATE TABLE old_state (value TEXT)")
                db.execute("INSERT INTO old_state VALUES ('before')")
                db.commit()
        else:
            path.write_bytes(b'{"value":"before"}\n')
    bundle = archive / "decision_inputs" / CAPTURE
    evidence = [bundle / "manifest.json", bundle / "pre_state.json"]
    evidence += [bundle / "pre_state/archive" / path.name for path in business if path.exists()]
    with ExitStack() as retained, pipeline_lock(path=archive / ".pipeline.lock") as lease:
        if wal:
            db = retained.enter_context(closing(sqlite3.connect(business[0])))
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA wal_autocheckpoint=0")
            db.execute("INSERT INTO old_state VALUES ('committed in WAL')")
            db.commit()
        with run_transaction.score_run_transaction(
            archive, business, metadata={"as_of": AS_OF, "run_type": "scheduled", "shadow": False},
            _lease=lease, capture_id=CAPTURE, evidence_artifacts=evidence,
        ) as txn:
            state = run_transaction.export_score_run_before_images(txn, _lease=lease)
            for path in business:
                if not path.exists():
                    path.write_bytes(b"post-run file, absent before")
                elif path.suffix == ".sqlite":
                    with closing(sqlite3.connect(path)) as db:
                        db.execute("UPDATE old_state SET value='after'")
                        db.commit()
                else:
                    path.write_bytes(b'{"value":"after"}\n')
            evidence[1].write_text(json.dumps(state))
            binding = {"run_id": txn.run_id, "capture_id": CAPTURE, "as_of": AS_OF,
                       "decision_id": DECISION, "input_hash": INPUT_HASH}
            evidence[0].write_text(json.dumps({
                "schema_version": "hermes-in-run-input-binding-v1", "capture_mode": "IN_RUN_CAPTURE",
                "binding": binding, "files": [
                    {"path": path.relative_to(root).as_posix(),
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in evidence[1:]],
            }))
            run_transaction.bind_score_run_inputs(
                txn, manifest_path=evidence[0], expected_manifest_sha256=_sha(evidence[0]),
                decision_id=DECISION, input_hash=INPUT_HASH, _lease=lease,
            )
    journal = archive / f".score_run_transactions/runs/{txn.run_id}/manifest.json"
    return store, txn, journal


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _restore(store, txn, journal, destination, **overrides):
    from hermes_escape_top.core.reporting.transaction_restore import restore_committed_before_images

    args = {"run_id": txn.run_id, "expected_journal_sha256": _sha(journal),
            "decision_id": DECISION, "input_hash": INPUT_HASH, "destination": destination}
    return restore_committed_before_images(store=store, **{**args, **overrides})


def test_restore_committed_export_uses_before_not_current_state(tmp_path):
    store, txn, journal = _commit(tmp_path)
    before = {path: path.read_bytes() for path in store.archive_dir.rglob("*") if path.is_file()}
    target = tmp_path / "restored"
    assert _restore(store, txn, journal, target) == target
    for name in NAMES:
        path = target / "archive" / name
        assert path.stat().st_mode & 0o777 == 0o600
        if path.suffix == ".sqlite":
            with closing(sqlite3.connect(path)) as db:
                assert db.execute("SELECT value FROM old_state").fetchall() == [("before",)]
        else:
            assert path.read_bytes() == b'{"value":"before"}\n'
    assert target.stat().st_mode & 0o777 == 0o700
    assert {path: path.read_bytes() for path in before} == before
    provenance = json.loads((target / "restoration.json").read_text())
    assert provenance["source_journal_sha256"] == _sha(journal)
    assert provenance["binding"]["run_id"] == txn.run_id
    assert provenance["evidence_role"] == "OFFLINE_BEFORE_STATE_NOT_FULL_REPLAY"


@pytest.mark.parametrize("case", ["digest", "decision", "input_hash", "run_id", "pending", "rolled_back", "v1"])
def test_restore_requires_external_committed_decision_anchor(tmp_path, case):
    store, txn, journal = _commit(tmp_path)
    target = tmp_path / "restored"
    overrides = {}
    if case == "digest":
        overrides["expected_journal_sha256"] = "0" * 64
    elif case == "decision":
        overrides["decision_id"] = "wrong-decision"
    elif case == "input_hash":
        overrides["input_hash"] = "0" * 64
    else:
        record = json.loads(journal.read_text())
        if case == "run_id":
            record["run_id"] = "f" * 32
        elif case == "v1":
            record["schema_version"] = run_transaction.SCHEMA_VERSION
        else:
            record["status"] = "PENDING" if case == "pending" else "ROLLED_BACK"
        journal.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        _restore(store, txn, journal, target, **overrides)
    assert not target.exists()
    assert not list(tmp_path.glob(".transaction-restore-*"))


def _rewrite_state(store, journal, change):
    record = json.loads(journal.read_text())
    bundle = store.archive_dir / "decision_inputs" / CAPTURE
    descriptor = bundle / "pre_state.json"
    state = json.loads(descriptor.read_text())
    change(state, record)
    descriptor.chmod(0o600)
    descriptor.write_text(json.dumps(state))
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for item in manifest["files"]:
        source = store.archive_dir.parent / item["path"]
        item["sha256"] = _sha(source)
    manifest_path.chmod(0o600)
    manifest_path.write_text(json.dumps(manifest))
    record["input_binding"]["manifest_sha256"] = _sha(manifest_path)
    for row in record["artifacts"]:
        if row["role"] == "DECISION_INPUT_EVIDENCE":
            row["after_sha256"] = _sha(store.archive_dir.parent / row["path"])
    journal.write_text(json.dumps(record))


@pytest.mark.parametrize("case", ["format", "mode", "availability", "extra", "missing", "binding", "path", "before_sha"])
def test_reanchored_malformed_descriptor_still_refused(tmp_path, case):
    store, txn, journal = _commit(tmp_path)

    def change(state, record):
        entry = state["artifacts"]["archive/hermes_state.sqlite"]
        if case == "extra":
            state["artifacts"]["archive/extra.json"] = dict(entry)
        elif case == "missing":
            state["artifacts"].pop("archive/hermes_state.sqlite")
        elif case == "binding":
            state["binding"]["run_id"] = "f" * 32
        elif case == "before_sha":
            record["artifacts"][0]["before_sha256"] = "0" * 64
        else:
            key, value = {"format": ("snapshot_format", "BYTES"), "mode": ("before_mode", True),
                          "availability": ("availability", "ABSENT"), "path": ("path", "/etc/passwd")}[case]
            entry[key] = value

    _rewrite_state(store, journal, change)
    with pytest.raises(ValueError):
        _restore(store, txn, journal, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
    assert not list(tmp_path.glob(".transaction-restore-*"))


@pytest.mark.parametrize("case", ["changed", "missing", "symlink", "bundle_symlink", "journal_symlink", "extra_file"])
def test_damaged_or_unregistered_evidence_produces_no_partial_restore(tmp_path, case):
    store, txn, journal = _commit(tmp_path)
    bundle = store.archive_dir / "decision_inputs" / CAPTURE
    source = bundle / "pre_state/archive" / NAMES[-1]
    anchor = _sha(journal)
    if case == "changed":
        source.chmod(0o600)
        source.write_bytes(b'{"tampered":true}')
    elif case == "missing":
        source.unlink()
    elif case == "symlink":
        twin = tmp_path / "same-bytes"
        twin.write_bytes(source.read_bytes())
        source.unlink()
        source.symlink_to(twin)
    elif case == "journal_symlink":
        twin = tmp_path / "same-journal"
        twin.write_bytes(journal.read_bytes())
        journal.unlink()
        journal.symlink_to(twin)
    elif case == "bundle_symlink":
        twin = tmp_path / "moved-bundle"
        bundle.rename(twin)
        bundle.symlink_to(twin, target_is_directory=True)
    else:
        (bundle / "unregistered.json").write_bytes(b"{}")
    with pytest.raises((ValueError, FileNotFoundError)):
        _restore(store, txn, journal, tmp_path / "restored", expected_journal_sha256=anchor)
    assert not (tmp_path / "restored").exists()
    assert not list(tmp_path.glob(".transaction-restore-*"))


@pytest.mark.parametrize("missing", [NAMES[:1], NAMES])
def test_restore_preserves_authenticated_absence(tmp_path, missing):
    store, txn, journal = _commit(tmp_path, missing=missing)
    target = _restore(store, txn, journal, tmp_path / "restored")
    for name in NAMES:
        assert (target / "archive" / name).exists() is (name not in missing)


@pytest.mark.parametrize("case", ["source", "history", "legacy", "existing", "dangling"])
def test_restore_refuses_source_and_occupied_destination(tmp_path, case):
    store, txn, journal = _commit(tmp_path)
    target = {"source": store.archive_dir.parent / "output", "history": store.history_dir / "output",
              "legacy": store.legacy_history_dir / "output"}.get(case, tmp_path / "restored")
    if case == "existing":
        target.mkdir()
        (target / "keep").write_bytes(b"unchanged")
    elif case == "dangling":
        target.symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError):
        _restore(store, txn, journal, target)
    if case == "existing":
        assert (target / "keep").read_bytes() == b"unchanged"
    elif case == "dangling":
        assert target.is_symlink()
    else:
        assert not target.exists()


def test_restore_publication_failure_cleans_stage_without_changing_source(tmp_path, monkeypatch):
    from hermes_escape_top.core.reporting import transaction_restore

    store, txn, journal = _commit(tmp_path)
    before = {path: path.read_bytes() for path in store.archive_dir.rglob("*") if path.is_file()}

    def fail_publish(*_args):
        raise OSError("publication interrupted")

    monkeypatch.setattr(transaction_restore.os, "rename", fail_publish)
    with pytest.raises(OSError, match="publication interrupted"):
        _restore(store, txn, journal, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
    assert not list(tmp_path.glob(".transaction-restore-*"))
    assert {path: path.read_bytes() for path in before} == before


def test_even_reanchored_corrupt_sqlite_is_rejected_not_restored_as_missing(tmp_path):
    store, txn, journal = _commit(tmp_path)
    source = store.archive_dir / "decision_inputs" / CAPTURE / "pre_state/archive/hermes_state.sqlite"
    source.chmod(0o600)
    source.write_bytes(b"this is not a database")

    def change(state, record):
        state["artifacts"]["archive/hermes_state.sqlite"]["sha256"] = _sha(source)
        for row in record["artifacts"]:
            if row["path"] == "archive/hermes_state.sqlite":
                row["before_sha256"] = _sha(source)

    _rewrite_state(store, journal, change)
    with pytest.raises(sqlite3.DatabaseError):
        _restore(store, txn, journal, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
    assert not list(tmp_path.glob(".transaction-restore-*"))


def test_restore_includes_committed_wal_rows_without_source_sidecars(tmp_path):
    store, txn, journal = _commit(tmp_path, wal=True)
    target = _restore(store, txn, journal, tmp_path / "restored")
    db_path = target / "archive/hermes_state.sqlite"
    with closing(sqlite3.connect(f"{db_path.as_uri()}?mode=ro&immutable=1", uri=True)) as db:
        assert db.execute("SELECT value FROM old_state ORDER BY value").fetchall() == [
            ("before",), ("committed in WAL",),
        ]
    assert not list((target / "archive").glob("*-wal"))
