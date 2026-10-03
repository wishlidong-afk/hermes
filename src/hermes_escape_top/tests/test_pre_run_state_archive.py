from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.core.data.run_transaction import (
    pending_score_run_transaction, recover_incomplete_score_run, score_run_transaction,
)
from hermes_escape_top.core.reporting import decision_inputs
from hermes_escape_top.core.safe_io import pipeline_lock

AS_OF = "2026-05-29"
DATABASES = (
    "hermes_state.sqlite", "reentry_state.sqlite", "mirror_reference.sqlite", "flow_reference.sqlite",
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("network forbidden in pre-state tests"))


def _store(tmp_path):
    config = load_config()
    data = tmp_path / "source/data"
    config["paths"] = {**config["paths"], "archive_dir": str(data / "archive"),
                       "history_dir": str(data / "history"),
                       "legacy_history_dir": str(data / "legacy")}
    store = LocalStore(config)
    store.ensure_dirs()
    return store


def _seed(store):
    for name in DATABASES:
        with closing(sqlite3.connect(store.archive_dir / name)) as connection:
            connection.execute("CREATE TABLE inputs (value TEXT)")
            connection.execute("INSERT INTO inputs VALUES (?)", (name,))
            connection.commit()
    for name in ("audit_log.jsonl", "signal_journal.jsonl", f"soft_adapter_snapshot_{AS_OF}.json"):
        (store.archive_dir / name).write_text(json.dumps({"as_of": AS_OF, "marker": name}) + "\n")


def _capture(store, destination, **kwargs):
    with pipeline_lock(path=store.archive_dir / ".pipeline.lock") as lease:
        return decision_inputs.capture_pre_run_state(
            AS_OF, store=store, destination=destination, _lease=lease, **kwargs,
        )


def _restore(result, store, destination, **kwargs):
    options = {"expected_manifest_sha256": result["manifest_sha256"],
               "capture_id": result["capture_id"], "as_of": AS_OF,
               "destination": destination, "store": store, **kwargs}
    return decision_inputs.restore_pre_run_state(Path(result["manifest_path"]), **options)


def test_capture_freezes_seven_pre_state_files_without_changing_sources(tmp_path):
    store = _store(tmp_path)
    _seed(store)
    before = {path.name: path.read_bytes() for path in store.archive_dir.iterdir() if path.is_file()}
    result = _capture(store, tmp_path / "capture")
    manifest_path = Path(result["manifest_path"])
    raw = manifest_path.read_bytes()
    assert result["manifest_sha256"] == hashlib.sha256(raw).hexdigest()
    manifest = json.loads(raw)
    assert manifest["capture_id"] == result["capture_id"]
    assert manifest["as_of"] == AS_OF
    assert manifest["evidence_role"] == "OFFLINE_PRE_STATE_NOT_DECISION_BOUND"
    assert not {"decision_id", "input_hash", "semantic_identity", "run_id"} & set(manifest)
    assert set(manifest["artifacts"]) == set(before)
    for name, entry in manifest["artifacts"].items():
        saved = manifest_path.parent / entry["path"]
        assert entry["availability"] == "PRESENT"
        assert entry["sha256"] == hashlib.sha256(saved.read_bytes()).hexdigest()
        if name in DATABASES:
            assert entry["format"] == "SQLITE_BACKUP"
            with closing(sqlite3.connect(f"{saved.as_uri()}?mode=ro&immutable=1", uri=True)) as connection:
                assert connection.execute("SELECT value FROM inputs").fetchall() == [(name,)]
        else:
            assert saved.read_bytes() == before[name]
        assert saved.stat().st_mode & 0o777 == 0o400
        assert (store.archive_dir / name).read_bytes() == before[name]
    assert manifest_path.parent.stat().st_mode & 0o777 == 0o700


def test_restore_uses_archived_state_not_newer_or_corrupt_current_sources(tmp_path):
    store = _store(tmp_path)
    _seed(store)
    result = _capture(store, tmp_path / "capture")
    bound_files = {path.relative_to(tmp_path / "capture"): path.read_bytes()
                   for path in (tmp_path / "capture").rglob("*") if path.is_file()}
    (store.archive_dir / "hermes_state.sqlite").write_bytes(b"corrupt current state")
    (store.archive_dir / "signal_journal.jsonl").write_bytes(b"corrupt current journal")
    restored = _restore(result, store, tmp_path / "restored")
    for name in DATABASES:
        with closing(sqlite3.connect(restored / "archive" / name)) as connection:
            assert connection.execute("SELECT value FROM inputs").fetchall() == [(name,)]
    assert json.loads((restored / "archive/signal_journal.jsonl").read_bytes())["marker"] == "signal_journal.jsonl"
    assert (store.archive_dir / "hermes_state.sqlite").read_bytes() == b"corrupt current state"
    assert (store.archive_dir / "signal_journal.jsonl").read_bytes() == b"corrupt current journal"
    assert {path.relative_to(tmp_path / "capture"): path.read_bytes()
            for path in (tmp_path / "capture").rglob("*") if path.is_file()} == bound_files
    assert (restored / "archive/hermes_state.sqlite").stat().st_mode & 0o777 == 0o600
    assert restored.stat().st_mode & 0o777 == 0o700


def test_first_run_absence_is_explicit_and_does_not_create_empty_state_files(tmp_path):
    store = _store(tmp_path)
    result = _capture(store, tmp_path / "capture")
    manifest = json.loads(Path(result["manifest_path"]).read_bytes())
    assert len(manifest["artifacts"]) == 7
    for name, entry in manifest["artifacts"].items():
        assert entry["availability"] == "ABSENT"
        assert entry["path"] is None
        assert entry["sha256"] is None
        assert not (store.archive_dir / name).exists()
    restored = _restore(result, store, tmp_path / "restored")
    assert not (restored / "archive").exists()
    assert (restored / "original_manifest.json").is_file()


def test_required_prior_state_cannot_be_recorded_as_first_run_absence(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="required pre-state artifact missing"):
        _capture(store, tmp_path / "capture", required_artifacts=("hermes_state.sqlite",))
    assert not (tmp_path / "capture").exists()
    assert not list(tmp_path.glob(".pre-run-state-*"))


def test_capture_includes_committed_wal_rows_and_preserves_typed_values(tmp_path):
    store = _store(tmp_path)
    state = store.archive_dir / "hermes_state.sqlite"
    with closing(sqlite3.connect(state)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("PRAGMA user_version=9")
        writer.execute("PRAGMA application_id=42")
        writer.execute("CREATE TABLE inputs (value)")
        writer.execute("INSERT INTO inputs VALUES (1)")
        writer.commit()
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        writer.executemany("INSERT INTO inputs VALUES (?)", [(2,), (None,), (b"blob",), ("text",), (1.5,)])
        writer.commit()
        before = state.read_bytes()
        wal = Path(f"{state}-wal")
        before_wal = wal.read_bytes()
        result = _capture(store, tmp_path / "capture", required_artifacts=(state.name,))
        assert state.read_bytes() == before
        assert wal.read_bytes() == before_wal
    restored = _restore(result, store, tmp_path / "restored")
    with closing(sqlite3.connect(restored / "archive/hermes_state.sqlite")) as connection:
        assert connection.execute("SELECT value FROM inputs ORDER BY rowid").fetchall() == [
            (1,), (2,), (None,), (b"blob",), ("text",), (1.5,),
        ]
        assert connection.execute("PRAGMA user_version").fetchone() == (9,)
        assert connection.execute("PRAGMA application_id").fetchone() == (42,)


@pytest.mark.parametrize("case", ["sqlite", "jsonl_syntax", "jsonl_scalar", "json_syntax"])
def test_corrupt_existing_state_is_not_recorded_as_absent(tmp_path, case):
    store = _store(tmp_path)
    _seed(store)
    name, content = {
        "sqlite": ("hermes_state.sqlite", b"not a database"),
        "jsonl_syntax": ("audit_log.jsonl", b'{"partial":'),
        "jsonl_scalar": ("signal_journal.jsonl", b'[]\n'),
        "json_syntax": (f"soft_adapter_snapshot_{AS_OF}.json", b'bad JSON'),
    }[case]
    (store.archive_dir / name).write_bytes(content)
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        _capture(store, tmp_path / "capture")
    assert (store.archive_dir / name).read_bytes() == content
    assert not (tmp_path / "capture").exists()
    assert not list(tmp_path.glob(".pre-run-state-*"))


def test_sqlite_exclusive_lock_refuses_capture_without_retry_or_partial_output(tmp_path):
    store = _store(tmp_path)
    _seed(store)
    with closing(sqlite3.connect(store.archive_dir / "hermes_state.sqlite")) as writer:
        writer.execute("BEGIN EXCLUSIVE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            _capture(store, tmp_path / "capture")
    assert not (tmp_path / "capture").exists()
    assert not list(tmp_path.glob(".pre-run-state-*"))


def test_empty_capture_still_rejects_a_symlink_bundle_root(tmp_path):
    store = _store(tmp_path)
    result = _capture(store, tmp_path / "capture")
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path / "capture", target_is_directory=True)
    result = {**result, "manifest_path": str(alias / "manifest.json")}
    with pytest.raises(ValueError, match="symlink"):
        _restore(result, store, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


@pytest.mark.parametrize("case", ["missing", "wrong_root", "expired"])
def test_capture_requires_the_current_data_root_active_lease(tmp_path, case):
    store = _store(tmp_path)
    path = store.archive_dir / ".pipeline.lock" if case == "expired" else tmp_path / "wrong/.pipeline.lock"
    with pipeline_lock(path=path) as lease:
        if case != "expired":
            with pytest.raises(RuntimeError):
                decision_inputs.capture_pre_run_state(
                    AS_OF, store=store, destination=tmp_path / "capture",
                    _lease=None if case == "missing" else lease,
                )
    if case == "expired":
        with pytest.raises(RuntimeError):
            decision_inputs.capture_pre_run_state(
                AS_OF, store=store, destination=tmp_path / "capture", _lease=lease,
            )
    assert not (tmp_path / "capture").exists()
    assert not list(tmp_path.glob(".pre-run-state-*"))


def test_capture_refuses_pending_transaction_without_recovering_it(tmp_path):
    store = _store(tmp_path)
    _seed(store)
    state = store.archive_dir / "hermes_state.sqlite"
    with pipeline_lock(path=store.archive_dir / ".pipeline.lock") as lease:
        context = score_run_transaction(store.archive_dir, [state], metadata={}, _lease=lease)
        context.__enter__()
        state.write_bytes(b"partial uncommitted state")
        before = pending_score_run_transaction(store.archive_dir)
        try:
            with pytest.raises(ValueError, match="pending score run"):
                decision_inputs.capture_pre_run_state(
                    AS_OF, store=store, destination=tmp_path / "capture", _lease=lease,
                )
            assert pending_score_run_transaction(store.archive_dir) == before
            assert state.read_bytes() == b"partial uncommitted state"
        finally:
            recover_incomplete_score_run(store.archive_dir, _lease=lease)
    assert not (tmp_path / "capture").exists()
    assert not list(tmp_path.glob(".pre-run-state-*"))


def _reanchor(result, mutate):
    path = Path(result["manifest_path"])
    manifest = json.loads(path.read_bytes())
    mutate(manifest)
    path.chmod(0o600)
    content = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    path.write_bytes(content)
    return {**result, "manifest_sha256": hashlib.sha256(content).hexdigest()}


def test_restore_does_not_accept_an_empty_capture_identity_even_with_a_matching_digest(tmp_path):
    store = _store(tmp_path)
    result = _capture(store, tmp_path / "capture")
    result = _reanchor(result, lambda manifest: manifest.update(capture_id=""))
    with pytest.raises(ValueError):
        _restore(result, store, tmp_path / "restored", capture_id="")
    assert not (tmp_path / "restored").exists()


@pytest.mark.parametrize("case", ["file_symlink", "dangling_symlink", "directory", "sidecar_symlink", "orphan_wal"])
def test_capture_rejects_ambiguous_or_orphan_sources(tmp_path, case):
    store = _store(tmp_path)
    _seed(store)
    state = store.archive_dir / "hermes_state.sqlite"
    if case == "sidecar_symlink":
        Path(f"{state}-wal").symlink_to(tmp_path / "outside")
    else:
        original = state.read_bytes()
        state.unlink()
        if case == "file_symlink":
            outside = tmp_path / "outside.sqlite"
            outside.write_bytes(original)
            state.symlink_to(outside)
        elif case == "dangling_symlink":
            state.symlink_to(tmp_path / "missing.sqlite")
        elif case == "directory":
            state.mkdir()
        else:
            Path(f"{state}-wal").write_bytes(b"orphan WAL")
    with pytest.raises(ValueError):
        _capture(store, tmp_path / "capture")
    assert not (tmp_path / "capture").exists()
    assert not list(tmp_path.glob(".pre-run-state-*"))


def test_unreadable_existing_file_is_an_error_not_absence(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _seed(store)
    source = store.archive_dir / "audit_log.jsonl"
    original_read = Path.read_bytes

    def unreadable(path):
        if path == source:
            raise PermissionError("fixture unreadable source")
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", unreadable)
    with pytest.raises(PermissionError):
        _capture(store, tmp_path / "capture")
    assert not (tmp_path / "capture").exists()
    assert not list(tmp_path.glob(".pre-run-state-*"))


@pytest.mark.parametrize("case", ["wrong_digest", "wrong_id", "wrong_date", "missing_file", "corrupt_file"])
def test_restore_rejects_unmatched_or_damaged_evidence_without_output(tmp_path, case):
    store = _store(tmp_path)
    _seed(store)
    result = _capture(store, tmp_path / "capture")
    options = {}
    if case == "wrong_digest":
        options["expected_manifest_sha256"] = "0" * 64
    elif case == "wrong_id":
        options["capture_id"] = "0" * 32
    elif case == "wrong_date":
        options["as_of"] = "2026-05-28"
    else:
        saved = tmp_path / "capture/archive/signal_journal.jsonl"
        if case == "missing_file":
            saved.unlink()
        else:
            saved.chmod(0o600)
            saved.write_bytes(b"changed archive")
    with pytest.raises((ValueError, FileNotFoundError)):
        _restore(result, store, tmp_path / "restored", **options)
    assert not (tmp_path / "restored").exists()
    assert not list(tmp_path.glob(".pre-run-state-*"))


def test_sqlite_logical_digest_does_not_truncate_text_at_embedded_nul(tmp_path):
    store = _store(tmp_path)
    _seed(store)
    state = store.archive_dir / "hermes_state.sqlite"
    with closing(sqlite3.connect(state)) as connection:
        connection.execute("UPDATE inputs SET value=?", ("same\x00first",))
        connection.commit()
    first = _capture(store, tmp_path / "first")
    with closing(sqlite3.connect(state)) as connection:
        connection.execute("UPDATE inputs SET value=?", ("same\x00second",))
        connection.commit()
    second = _capture(store, tmp_path / "second")
    def digest(result):
        return json.loads(Path(result["manifest_path"]).read_bytes())["artifacts"][state.name]["logical_sha256"]
    assert digest(first) != digest(second)
    restored = _restore(first, store, tmp_path / "restored")
    with closing(sqlite3.connect(restored / "archive" / state.name)) as connection:
        assert connection.execute("SELECT value FROM inputs").fetchall() == [("same\x00first",)]


@pytest.mark.parametrize("case", ["existing", "symlink", "data", "archive", "history", "legacy"])
def test_capture_destination_cannot_overwrite_or_pollute_source_roots(tmp_path, case):
    store = _store(tmp_path)
    _seed(store)
    if case in {"existing", "symlink"}:
        destination = tmp_path / "target"
        if case == "existing":
            destination.mkdir()
        else:
            destination.symlink_to(tmp_path / "absent", target_is_directory=True)
    else:
        roots = {"data": store.archive_dir.parent, "archive": store.archive_dir,
                 "history": store.history_dir, "legacy": store.legacy_history_dir}
        destination = roots[case] / "target"
    with pytest.raises(ValueError):
        _capture(store, destination)
    assert not list(tmp_path.glob(".pre-run-state-*"))


@pytest.mark.parametrize("case", ["old_data", "old_archive", "old_history", "old_legacy", "new_data", "new_archive"])
def test_restore_protects_original_roots_after_current_data_root_switch(tmp_path, case):
    original = _store(tmp_path)
    _seed(original)
    result = _capture(original, tmp_path / "capture")
    current = _store(tmp_path / "new")
    roots = {"old_data": original.archive_dir.parent, "old_archive": original.archive_dir,
             "old_history": original.history_dir, "old_legacy": original.legacy_history_dir,
             "new_data": current.archive_dir.parent, "new_archive": current.archive_dir}
    destination = roots[case] / "restored"
    with pytest.raises(ValueError, match="overlaps a source root"):
        _restore(result, current, destination)
    assert not destination.exists()
    assert not list(destination.parent.glob(".pre-run-state-*"))


@pytest.mark.parametrize("case", ["path", "extra", "missing", "logical_digest", "required_absent", "roots", "format"])
def test_even_reanchored_manifest_must_obey_the_exact_state_contract(tmp_path, case):
    store = _store(tmp_path)
    _seed(store)
    result = _capture(store, tmp_path / "capture", required_artifacts=("hermes_state.sqlite",))

    def mutate(manifest):
        entry = manifest["artifacts"]["hermes_state.sqlite"]
        if case == "path":
            entry["path"] = "archive/../../outside.sqlite"
        elif case == "extra":
            manifest["artifacts"]["unexpected.sqlite"] = entry
        elif case == "missing":
            manifest["artifacts"].pop("hermes_state.sqlite")
        elif case == "logical_digest":
            entry["logical_sha256"] = "0" * 64
        elif case == "required_absent":
            manifest["artifacts"]["hermes_state.sqlite"] = {
                "availability": "ABSENT", "format": "SQLITE_BACKUP", "path": None,
                "sha256": None, "logical_sha256": None,
            }
        elif case == "roots":
            manifest["source_roots_at_capture"] = {}
        else:
            entry["format"] = "UNKNOWN"
    result = _reanchor(result, mutate)
    with pytest.raises(ValueError):
        _restore(result, store, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
    assert not list(tmp_path.glob(".pre-run-state-*"))


@pytest.mark.parametrize("phase", ["capture", "restore"])
def test_publish_failure_cleans_stage_and_never_changes_source_state(tmp_path, monkeypatch, phase):
    store = _store(tmp_path)
    _seed(store)
    result = _capture(store, tmp_path / "capture") if phase == "restore" else None
    before = {path.name: path.read_bytes() for path in store.archive_dir.iterdir()
              if path.is_file() and path.name != ".pipeline.lock"}

    def fail_publish(*_args):
        raise OSError("injected publish failure")

    monkeypatch.setattr(os, "rename", fail_publish)
    destination = tmp_path / "restored" if phase == "restore" else tmp_path / "capture"
    with pytest.raises(OSError, match="publish failure"):
        if phase == "restore":
            _restore(result, store, destination)
        else:
            _capture(store, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".pre-run-state-*"))
    assert {path.name: path.read_bytes() for path in store.archive_dir.iterdir()
            if path.is_file() and path.name != ".pipeline.lock"} == before


@pytest.mark.parametrize("case", ["manifest", "archive_directory", "file"])
def test_restore_rejects_symlink_evidence_even_when_bytes_match(tmp_path, case):
    store = _store(tmp_path)
    _seed(store)
    result = _capture(store, tmp_path / "capture")
    if case == "archive_directory":
        source = tmp_path / "capture/archive"
        target = tmp_path / "archive_copy"
    elif case == "manifest":
        source = Path(result["manifest_path"])
        target = tmp_path / "manifest_copy.json"
    else:
        source = tmp_path / "capture/archive/hermes_state.sqlite"
        target = tmp_path / "state_copy.sqlite"
    source.rename(target)
    source.symlink_to(target, target_is_directory=case == "archive_directory")
    with pytest.raises(ValueError, match="symlink"):
        _restore(result, store, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
    assert not list(tmp_path.glob(".pre-run-state-*"))


def test_restored_state_replays_prior_confirmation_and_sell_cooldown(tmp_path):
    from hermes_escape_top.core.data.state_store import latest_execution_confirmations, record_execution_confirmation
    from hermes_escape_top.core.decision.signal_journal import trading_days_since_last_sell

    store = _store(tmp_path)
    _seed(store)
    state = store.archive_dir / "hermes_state.sqlite"
    journal = store.archive_dir / "signal_journal.jsonl"
    journal.write_text(json.dumps({"as_of": "2026-05-27", "symbol": "MSTR", "status": "EXIT"}) + "\n")
    record_execution_confirmation(state, symbol="MSTR", tranche="T1", confirmed_at="2026-05-27T12:00:00+00:00")
    confirmation = latest_execution_confirmations(state)
    cooldown = trading_days_since_last_sell(journal, "MSTR", AS_OF)
    result = _capture(store, tmp_path / "capture")
    record_execution_confirmation(state, symbol="MSTR", tranche="T2", confirmed_at="2026-05-28T12:00:00+00:00")
    journal.write_text(json.dumps({"as_of": "2026-05-28", "symbol": "MSTR", "status": "EXIT"}) + "\n")
    restored = _restore(result, store, tmp_path / "restored")
    assert latest_execution_confirmations(restored / "archive/hermes_state.sqlite") == confirmation
    assert trading_days_since_last_sell(restored / "archive/signal_journal.jsonl", "MSTR", AS_OF) == cooldown
    assert latest_execution_confirmations(state)["MSTR"]["tranche"] == "T2"
    assert trading_days_since_last_sell(journal, "MSTR", AS_OF) != cooldown


@pytest.mark.parametrize("case", ["existing", "symlink"])
def test_restore_never_overwrites_existing_or_dangling_target(tmp_path, case):
    store = _store(tmp_path)
    result = _capture(store, tmp_path / "capture")
    destination = tmp_path / "restored"
    if case == "existing":
        destination.mkdir()
        (destination / "keep").write_bytes(b"keep")
    else:
        destination.symlink_to(tmp_path / "absent", target_is_directory=True)
    with pytest.raises(ValueError, match="already exists"):
        _restore(result, store, destination)
    if case == "existing":
        assert (destination / "keep").read_bytes() == b"keep"
    else:
        assert destination.is_symlink()
    assert not list(tmp_path.glob(".pre-run-state-*"))


def test_sqlite_backup_preserves_without_rowid_tables_and_quoted_identifiers(tmp_path):
    store = _store(tmp_path)
    state = store.archive_dir / "hermes_state.sqlite"
    with closing(sqlite3.connect(state)) as connection:
        connection.execute('CREATE TABLE "quoted "" table" (key TEXT PRIMARY KEY, value BLOB) WITHOUT ROWID')
        connection.execute('INSERT INTO "quoted "" table" VALUES (?, ?)', ("key", b"value"))
        connection.commit()
    result = _capture(store, tmp_path / "capture")
    restored = _restore(result, store, tmp_path / "restored")
    with closing(sqlite3.connect(restored / "archive" / state.name)) as connection:
        assert connection.execute('SELECT * FROM "quoted "" table"').fetchall() == [("key", b"value")]


def test_sqlite_logical_digest_includes_implicit_rowids(tmp_path):
    store = _store(tmp_path)
    _seed(store)
    state = store.archive_dir / "hermes_state.sqlite"
    first = _capture(store, tmp_path / "first")
    with closing(sqlite3.connect(state)) as connection:
        connection.execute("UPDATE inputs SET rowid=10")
        connection.commit()
    second = _capture(store, tmp_path / "second")
    before = json.loads(Path(first["manifest_path"]).read_bytes())["artifacts"][state.name]
    after = json.loads(Path(second["manifest_path"]).read_bytes())["artifacts"][state.name]
    assert before["logical_sha256"] != after["logical_sha256"]


def test_sqlite_with_no_accessible_implicit_rowid_is_refused_not_partially_hashed(tmp_path):
    store = _store(tmp_path)
    state = store.archive_dir / "hermes_state.sqlite"
    with closing(sqlite3.connect(state)) as connection:
        connection.execute("CREATE TABLE inputs (rowid, _rowid_, oid, value)")
        connection.commit()
    with pytest.raises(ValueError, match="implicit rowid cannot be inspected"):
        _capture(store, tmp_path / "capture")
    assert not (tmp_path / "capture").exists()
    assert not list(tmp_path.glob(".pre-run-state-*"))
