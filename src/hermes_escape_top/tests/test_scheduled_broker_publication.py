"""Offline official-run selection without activating production capture."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from hermes_escape_top.core.safe_io import pipeline_lock
from hermes_escape_top.core.reporting.broker_publication_status import read_broker_publication_status
from hermes_escape_top.scripts import run_daily_package as rdp
from test_a2_production_capture import capture_root as capture_root
from test_broker_input_capture import broker_run as broker_run
from test_commit_observation_receipt import receipt_run as receipt_run
from test_broker_publication_status import publication_run as publication_run


@pytest.fixture
def official_run(tmp_path):
    archive = tmp_path / "data/archive"
    archive.mkdir(parents=True)
    receipt = {
        "status": "OK", "ok": True, "run_type": "scheduled", "as_of": "2026-05-29",
        "started_at": "2026-05-30T07:10:00+08:00", "finished_at": "2026-05-30T07:10:30+08:00",
    }
    payload = {
        "as_of": receipt["as_of"], "run_type": "scheduled", "run_ts": "2026-05-29T23:10:10+00:00",
        "input_hash": "b" * 64, "decision_evidence": {"decision_id": "synthetic-decision"},
        "persistence": {"protocol": "recoverable-journal-v1", "run_id": "a" * 32},
    }

    def write():
        (archive / "run_receipt.json").write_text(json.dumps(receipt))
        (archive / "audit_log.jsonl").write_text(json.dumps({"payload": payload}) + "\n")

    write()
    return archive, receipt, payload, write


def test_official_v1_is_not_applicable_without_any_journal_or_cache(official_run):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    archive, _, _, _ = official_run
    before = {p: p.read_bytes() for p in archive.rglob("*") if p.is_file()}
    report = read_scheduled_broker_publication(archive_dir=archive, acceptance_date=date(2026, 5, 30))
    assert report["status"] == "INFO"
    assert report["publication_status"] == "NOT_APPLICABLE"
    assert report["reason"] == "CAPTURE_DISABLED"
    assert report["strategy_blocking"] is False
    assert report["cache_contents_verified"] is False
    assert report["anchor_source"] is None
    assert {p: p.read_bytes() for p in archive.rglob("*") if p.is_file()} == before


def test_v2_without_an_observation_is_unknown_not_not_applicable(official_run):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    archive, _, payload, write = official_run
    payload["persistence"].update(protocol="recoverable-journal-v2", capture_id="c" * 32)
    write()
    report = read_scheduled_broker_publication(archive_dir=archive, acceptance_date=date(2026, 5, 30))
    assert report["status"] == "UNKNOWN"
    assert report["reason"] == "ANCHOR_UNAVAILABLE"
    assert report["anchor_source"] is None


@pytest.mark.parametrize("mixed", ["capture_id", "receipt_observation", "unknown_protocol"])
def test_mixed_or_unknown_v1_mode_cannot_be_declared_not_applicable(official_run, mixed):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    archive, receipt, payload, write = official_run
    if mixed == "capture_id":
        payload["persistence"]["capture_id"] = None
    elif mixed == "receipt_observation":
        receipt["commit_observation"] = {}
    else:
        payload["persistence"]["protocol"] = "future-protocol"
    write()
    report = read_scheduled_broker_publication(archive_dir=archive, acceptance_date=date(2026, 5, 30))
    assert report["status"] == "UNKNOWN"
    assert report["publication_status"] == "UNVERIFIED"


@pytest.mark.parametrize("location", ["receipt", "persistence", "payload"])
@pytest.mark.parametrize("field", ["capture_id", "capture_inputs", "capture_mode", "input_binding", "commit_observation"])
def test_known_capture_markers_at_any_off_boundary_are_unknown(official_run, location, field):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    archive, receipt, payload, write = official_run
    target = {"receipt": receipt, "persistence": payload["persistence"], "payload": payload}[location]
    target[field] = True
    write()
    report = read_scheduled_broker_publication(archive_dir=archive, acceptance_date=date(2026, 5, 30))
    assert report["status"] == "UNKNOWN"
    assert report["publication_status"] == "UNVERIFIED"


@pytest.mark.parametrize("field", ["finished_at", "run_ts"])
def test_timezone_overflow_is_unknown_not_an_uncaught_exception(official_run, field):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    archive, receipt, payload, write = official_run
    (payload if field == "run_ts" else receipt)[field] = "9999-12-31T23:59:59-12:00"
    write()
    report = read_scheduled_broker_publication(archive_dir=archive, acceptance_date=date(2026, 5, 30))
    assert report["status"] == "UNKNOWN"


def test_flat_receipt_protocol_cannot_contradict_the_selected_mode(official_run):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    archive, receipt, _, write = official_run
    receipt["protocol"] = "recoverable-journal-v2"
    write()
    report = read_scheduled_broker_publication(archive_dir=archive, acceptance_date=date(2026, 5, 30))
    assert report["status"] == "UNKNOWN"


def test_real_producer_receipt_is_used_by_the_unchanged_reader(receipt_run, broker_run):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    with pipeline_lock(path=receipt_run.archive / ".pipeline.lock") as lease:
        rdp._run_daily_with_receipt(receipt_run.args, _lease=lease, capture_inputs=True)
    receipt = json.loads((receipt_run.archive / "run_receipt.json").read_text())
    today = datetime.fromisoformat(receipt["finished_at"]).astimezone(ZoneInfo("Asia/Shanghai")).date()
    for cache in broker_run.caches.values():
        cache.unlink(missing_ok=True)
    before = {p: p.read_bytes() for p in receipt_run.archive.rglob("*") if p.is_file()}
    report = read_scheduled_broker_publication(archive_dir=receipt_run.archive, acceptance_date=today)
    assert report["status"] == "INFO"
    assert report["publication_status"] == "NOT_PUBLISHED"
    assert report["reason"] == "MATCHING_RECEIPT"
    assert report["anchor_source"] == "LOCAL_PRODUCER_RECEIPT"
    assert report["run_id"] == receipt["commit_observation"]["run_id"]
    assert report["journal_sha256"] == receipt["commit_observation"]["journal_sha256"]
    assert report["official_receipt_status"] == "OK"
    assert report["cache_contents_verified"] is False
    assert {p: p.read_bytes() for p in receipt_run.archive.rglob("*") if p.is_file()} == before


@pytest.fixture
def selected_run(publication_run):
    """Synthetic official selection around a real minimal committed transaction.

    These selection fixtures do not claim producer issuance; the end-to-end
    receipt test above separately exercises the actual producer receipt path.
    """
    def make(**kwargs):
        run = publication_run(**kwargs)
        record = json.loads(run.journal.read_text())
        observation = {
            "schema_version": "hermes-score-commit-observation-v1", "protocol": "recoverable-journal-v2",
            "run_id": record["run_id"], "capture_id": record["capture_id"],
            "as_of": record["metadata"]["as_of"], "decision_id": run.arguments["decision_id"],
            "input_hash": run.arguments["input_hash"], "journal_sha256": run.arguments["expected_journal_sha256"],
            "committed_at": record["committed_at"],
        }
        stamp = datetime.fromisoformat(record["committed_at"])
        receipt = {
            "status": "OK", "ok": True, "run_type": "scheduled", "as_of": observation["as_of"],
            "started_at": (stamp - timedelta(seconds=5)).isoformat(),
            "finished_at": (stamp + timedelta(seconds=5)).isoformat(), "commit_observation": observation,
        }
        audit = {
            "as_of": observation["as_of"], "run_type": "scheduled", "run_ts": stamp.isoformat(),
            "input_hash": observation["input_hash"],
            "decision_evidence": {"decision_id": observation["decision_id"]},
            "persistence": {key: observation[key] for key in ("protocol", "run_id", "capture_id")},
        }
        archive = run.arguments["archive_dir"]

        def write():
            (archive / "run_receipt.json").write_text(json.dumps(receipt))
            (archive / "audit_log.jsonl").write_text(json.dumps({"payload": audit}) + "\n")

        write()
        return run, receipt, audit, stamp.astimezone(ZoneInfo("Asia/Shanghai")).date(), write
    return make


@pytest.mark.parametrize(("sources", "fail"), [
    (("tws", "tws"), ()), (("tws", "tws"), ("positions",)), (("snapshot", "cache"), ()),
])
def test_child_status_is_passed_through_without_network_database_or_writes(selected_run, monkeypatch, sources, fail):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    run, _, _, today, _ = selected_run(sources=sources, fail=fail)
    expected = read_broker_publication_status(**run.arguments)
    archive = run.arguments["archive_dir"]
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode) for p in archive.rglob("*") if p.is_file()}

    def forbidden(*_args, **_kwargs):
        raise AssertionError("offline observer attempted network/database access")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    actual = read_scheduled_broker_publication(archive_dir=archive, acceptance_date=today)
    for key in ("status", "publication_status", "reason", "run_id", "capture_id", "caches", "receipt_sha256"):
        assert actual[key] == expected[key]
    assert actual["anchor_source"] == "LOCAL_PRODUCER_RECEIPT"
    assert actual["scope"] == "OPERATIONS" and actual["strategy_blocking"] is False
    assert actual["cache_contents_verified"] is False
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode) for p in archive.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("damage", [
    "missing_receipt", "missing_audit", "duplicate_audit", "malformed_audit", "duplicate_key",
    "receipt_schema", "payload_schema", "running", "unofficial", "wrong_ok", "old_receipt", "as_of",
    "naive_receipt", "naive_audit", "different_invocation", "run_id", "input_hash", "shadow",
    "capture_on_payload", "observation_on_payload", "envelope_as_of", "envelope_input",
])
def test_official_selection_never_guesses_a_run(official_run, damage):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    archive, receipt, payload, write = official_run
    if damage == "receipt_schema":
        receipt["schema_version"] = "future"
    elif damage == "payload_schema":
        payload["schema_version"] = "future"
    elif damage == "running":
        receipt["status"] = "RUNNING"
    elif damage == "unofficial":
        receipt["run_type"] = "manual_rerun"
    elif damage == "wrong_ok":
        receipt["ok"] = 1
    elif damage == "old_receipt":
        receipt["finished_at"] = "2026-05-29T07:10:30+08:00"
    elif damage == "as_of":
        payload["as_of"] = "2026-05-28"
    elif damage == "naive_receipt":
        receipt["started_at"] = "2026-05-30T07:10:00"
    elif damage == "naive_audit":
        payload["run_ts"] = "2026-05-30T07:10:10"
    elif damage == "different_invocation":
        payload["run_ts"] = "2026-05-30T08:10:10+08:00"
    elif damage == "run_id":
        payload["persistence"]["run_id"] = "../other"
    elif damage == "input_hash":
        payload["input_hash"] = None
    elif damage == "shadow":
        payload["shadow"] = True
    elif damage == "capture_on_payload":
        payload["capture_id"] = "a" * 32
    elif damage == "observation_on_payload":
        payload["commit_observation"] = {}
    write()
    audit_path = archive / "audit_log.jsonl"
    if damage.startswith("missing_"):
        (archive / ("run_receipt.json" if damage == "missing_receipt" else "audit_log.jsonl")).unlink()
    elif damage == "duplicate_audit":
        audit_path.write_text(audit_path.read_text() * 2)
    elif damage == "malformed_audit":
        audit_path.write_text(audit_path.read_text() + "{\n")
    elif damage == "duplicate_key":
        (archive / "run_receipt.json").write_text(json.dumps(receipt)[:-1] + ',"status":"OK"}')
    elif damage.startswith("envelope_"):
        key = "as_of" if damage == "envelope_as_of" else "input_hash"
        audit_path.write_text(json.dumps({"payload": payload, key: "different"}) + "\n")
    report = read_scheduled_broker_publication(archive_dir=archive, acceptance_date=date(2026, 5, 30))
    assert report["status"] == "UNKNOWN"
    assert report["anchor_source"] is None


@pytest.mark.parametrize("damage", [
    "schema_version", "protocol", "run_id", "capture_id", "decision_id", "input_hash", "as_of",
    "missing", "extra", "null", "journal_sha256", "old", "future", "naive",
])
def test_invalid_or_foreign_anchor_is_not_sent_to_the_reader(selected_run, damage):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    run, receipt, _, today, write = selected_run()
    value = receipt["commit_observation"]
    if damage == "missing":
        del value["input_hash"]
    elif damage == "extra":
        value["extra"] = True
    elif damage == "null":
        receipt["commit_observation"] = None
    elif damage in {"old", "future", "naive"}:
        stamp = datetime.fromisoformat(value["committed_at"])
        value["committed_at"] = (stamp.replace(tzinfo=None) if damage == "naive" else
                                 stamp + timedelta(days=1 if damage == "future" else -1)).isoformat()
    else:
        value[damage] = "wrong"
    write()
    report = read_scheduled_broker_publication(archive_dir=run.arguments["archive_dir"], acceptance_date=today)
    assert report["status"] == "UNKNOWN"
    assert report["reason"] == "ANCHOR_INVALID"
    assert report["anchor_source"] is None


def test_changed_journal_cannot_be_reanchored_by_the_observer(selected_run):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    run, receipt, _, today, _ = selected_run()
    record = json.loads(run.journal.read_text())
    record["extra_after_capture"] = "must not be trusted by computing a new digest"
    run.journal.write_text(json.dumps(record))
    assert hashlib.sha256(run.journal.read_bytes()).hexdigest() != receipt["commit_observation"]["journal_sha256"]
    before = (run.arguments["archive_dir"] / "run_receipt.json").read_bytes()
    report = read_scheduled_broker_publication(archive_dir=run.arguments["archive_dir"], acceptance_date=today)
    assert report["status"] == "UNKNOWN" and report["reason"] == "TRANSACTION_UNVERIFIED"
    assert (run.arguments["archive_dir"] / "run_receipt.json").read_bytes() == before


def test_same_date_same_decision_cannot_borrow_the_previous_runs_receipt(selected_run):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    first, previous, _, today, _ = selected_run()
    current, _, audit, _, _ = selected_run()
    assert first.payload["decision_evidence"]["decision_id"] == audit["decision_evidence"]["decision_id"]
    assert first.payload["persistence"]["run_id"] != current.payload["persistence"]["run_id"]
    (current.arguments["archive_dir"] / "run_receipt.json").write_text(json.dumps(previous))
    report = read_scheduled_broker_publication(archive_dir=current.arguments["archive_dir"], acceptance_date=today)
    assert report["status"] == "UNKNOWN"
    assert report["reason"] == "ANCHOR_INVALID"


@pytest.mark.parametrize("field", ["as_of", "capture_id", "committed_at"])
def test_reanchored_journal_cannot_replace_the_selected_official_identity(selected_run, field):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    run, receipt, _, today, write = selected_run()
    record = json.loads(run.journal.read_text())
    if field == "as_of":
        record["metadata"]["as_of"] = "2026-05-28"
    else:
        record[field] = "f" * 32 if field == "capture_id" else "2000-01-01T00:00:00+00:00"
    run.journal.write_text(json.dumps(record))
    receipt["commit_observation"]["journal_sha256"] = hashlib.sha256(run.journal.read_bytes()).hexdigest()
    write()
    report = read_scheduled_broker_publication(archive_dir=run.arguments["archive_dir"], acceptance_date=today)
    assert report["status"] == "UNKNOWN" and report["anchor_source"] is None


def test_missing_auxiliary_receipt_remains_unknown_after_a_valid_anchor(selected_run):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    run, _, _, today, _ = selected_run()
    run.receipt.unlink()
    report = read_scheduled_broker_publication(archive_dir=run.arguments["archive_dir"], acceptance_date=today)
    assert report["status"] == "UNKNOWN"
    assert report["reason"] == "RECEIPT_MISSING"
    assert report["anchor_source"] == "LOCAL_PRODUCER_RECEIPT"
    assert report["cache_contents_verified"] is False


@pytest.mark.parametrize("location", ["receipt", "persistence"])
def test_v2_cannot_accept_contradictory_flat_capture_flags(selected_run, location):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    run, receipt, audit, today, write = selected_run()
    (receipt if location == "receipt" else audit["persistence"])["capture_inputs"] = False
    write()
    report = read_scheduled_broker_publication(archive_dir=run.arguments["archive_dir"], acceptance_date=today)
    assert report["status"] == "UNKNOWN"


def test_publication_observation_cannot_rewrite_a_failed_official_receipt(selected_run):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    run, receipt, _, today, write = selected_run()
    receipt.update(status="FAILED", ok=False, error="synthetic post-commit failure")
    write()
    path = run.arguments["archive_dir"] / "run_receipt.json"
    before = path.read_bytes()
    report = read_scheduled_broker_publication(archive_dir=run.arguments["archive_dir"], acceptance_date=today)
    assert report["status"] == "OK"  # Only the auxiliary declaration, never overall acceptance.
    assert report["official_receipt_status"] == "FAILED"
    assert path.read_bytes() == before


@pytest.mark.parametrize("path_kind", ["receipt_symlink", "audit_directory", "receipt_fifo", "journal_parent_symlink"])
def test_evidence_paths_must_be_regular_and_not_redirected(selected_run, path_kind, tmp_path):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    run, _, _, today, _ = selected_run()
    archive = run.arguments["archive_dir"]
    if path_kind == "journal_parent_symlink":
        parent = run.journal.parent
        moved = tmp_path / "moved-journal"
        parent.rename(moved)
        parent.symlink_to(moved, target_is_directory=True)
    else:
        target = archive / ("audit_log.jsonl" if path_kind == "audit_directory" else "run_receipt.json")
        raw = target.read_bytes()
        target.unlink()
        if path_kind == "audit_directory":
            target.mkdir()
        elif path_kind == "receipt_fifo":
            os.mkfifo(target)
        else:
            moved = tmp_path / "identical-receipt.json"
            moved.write_bytes(raw)
            target.symlink_to(moved)
    report = read_scheduled_broker_publication(archive_dir=archive, acceptance_date=today)
    assert report["status"] == "UNKNOWN" and report["anchor_source"] is None


@pytest.mark.parametrize("schema", ["future-audit-v999", None, 0])
def test_unknown_outer_audit_schema_cannot_claim_off_mode(official_run, schema):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    archive, _, payload, _ = official_run
    (archive / "audit_log.jsonl").write_text(json.dumps({"schema_version": schema, "payload": payload}) + "\n")
    report = read_scheduled_broker_publication(archive_dir=archive, acceptance_date=date(2026, 5, 30))
    assert report["status"] == "UNKNOWN"


@pytest.mark.parametrize("schema", ["future-audit-v999", None, 0])
def test_unknown_outer_audit_schema_cannot_accept_a_valid_v2_chain(selected_run, schema):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    run, _, audit, today, _ = selected_run()
    archive = run.arguments["archive_dir"]
    (archive / "audit_log.jsonl").write_text(json.dumps({"schema_version": schema, "payload": audit}) + "\n")
    report = read_scheduled_broker_publication(archive_dir=archive, acceptance_date=today)
    assert report["status"] == "UNKNOWN" and report["anchor_source"] is None


@pytest.mark.parametrize("representation", ["known_envelope", "legacy_unwrapped"])
def test_supported_audit_representations_keep_the_valid_v2_path(selected_run, representation):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    run, _, audit, today, _ = selected_run()
    audit["schema_version"] = "escape-top-greenfield-phase3-score-v1"
    row = ({"schema_version": "escape-top-greenfield-audit-v1", "payload": audit}
           if representation == "known_envelope" else audit)
    archive = run.arguments["archive_dir"]
    (archive / "audit_log.jsonl").write_text(json.dumps(row) + "\n")
    report = read_scheduled_broker_publication(archive_dir=archive, acceptance_date=today)
    assert report["status"] == "OK" and report["publication_status"] == "PUBLISHED"


@pytest.mark.parametrize("target", ["receipt", "historical_audit_row"])
def test_excessive_json_nesting_is_unknown_without_mutating_evidence(official_run, target):
    from hermes_escape_top.core.reporting.scheduled_broker_publication import read_scheduled_broker_publication

    archive, receipt, _, _ = official_run
    depth = sys.getrecursionlimit() + 100
    nested = "[" * depth + "0" + "]" * depth
    if target == "receipt":
        path = archive / "run_receipt.json"
        path.write_text(json.dumps(receipt)[:-1] + ',"extra":' + nested + "}")
    else:
        path = archive / "audit_log.jsonl"
        path.write_text(path.read_text() + '{"extra":' + nested + "}\n")
    before = path.read_bytes()
    report = read_scheduled_broker_publication(archive_dir=archive, acceptance_date=date(2026, 5, 30))
    assert report["status"] == "UNKNOWN"
    assert path.read_bytes() == before
