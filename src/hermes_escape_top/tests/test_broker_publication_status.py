"""Read auxiliary publication evidence without claiming current cache validity."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from hermes_escape_top import pipeline
from hermes_escape_top.core.data.run_transaction import bind_score_run_inputs, score_run_transaction
from hermes_escape_top.core.data.transaction_evidence import business_paths
from hermes_escape_top.core.reporting.broker_capture import BrokerCapture
from hermes_escape_top.core.reporting.broker_publication_status import read_broker_publication_status
from hermes_escape_top.core.safe_io import pipeline_lock
from test_a2_production_capture import capture_root as capture_root
from test_broker_input_capture import broker_run as broker_run


@pytest.fixture
def committed(broker_run):
    payload = pipeline.score_pipeline(
        "2026-05-29", config_path=broker_run.config_path, include_ibkr=True,
        run_type="scheduled", capture_inputs=True,
    )
    return _details(broker_run, payload)


def _details(broker_run, payload):
    run_id = payload["persistence"]["run_id"]
    journal = broker_run.archive / f".score_run_transactions/runs/{run_id}/manifest.json"
    return SimpleNamespace(
        payload=payload, journal=journal,
        receipt=broker_run.archive / "broker_cache_publications" / f"{run_id}.json",
        arguments={"archive_dir": broker_run.archive, "run_id": run_id,
                   "expected_journal_sha256": hashlib.sha256(journal.read_bytes()).hexdigest(),
                   "decision_id": payload["decision_evidence"]["decision_id"],
                   "input_hash": payload["input_hash"]},
    )


@pytest.fixture
def publication_run(broker_run):
    def make(*, sources=("tws", "tws"), fail=(), tape_change=None):
        archive = broker_run.archive
        capture_id = uuid4().hex
        bundle = archive / "decision_inputs" / capture_id
        manifest_path, tape_path = bundle / "manifest.json", bundle / "broker.json"
        broker = BrokerCapture(include_ibkr=True)
        for (name, response), source in zip(broker_run.responses.items(), sources, strict=True):
            if source == "NOT_READ":
                broker.skipped(name, "disabled")
            elif source == "ERROR":
                broker.failed(name, OSError("synthetic read failure"))
            else:
                broker.observed(name, type(response).from_dict({**response.to_dict(), "source": source}))
        with pipeline_lock(path=archive / ".pipeline.lock") as lease:
            with score_run_transaction(
                archive, [archive.parent / path for path in business_paths("2026-05-29")],
                metadata={"as_of": "2026-05-29", "run_type": "scheduled", "shadow": False},
                evidence_artifacts=[manifest_path, tape_path], capture_id=capture_id, _lease=lease,
            ) as transaction:
                for relative in business_paths("2026-05-29"):
                    path = archive.parent / relative
                    if path.suffix == ".sqlite":
                        with closing(sqlite3.connect(path)) as db:
                            db.execute("CREATE TABLE IF NOT EXISTS synthetic (value TEXT)")
                            db.commit()
                    else:
                        path.write_text("{}\n")
                bundle.mkdir(parents=True, exist_ok=True)
                tape = deepcopy(broker.tape({"ibkr": {}, "execution_sync": {}}))
                if tape_change is not None:
                    tape_change(tape)
                tape_path.write_text(json.dumps(tape))
                binding = {"run_id": transaction.run_id, "capture_id": capture_id,
                           "as_of": "2026-05-29", "decision_id": "synthetic-decision", "input_hash": "b" * 64}
                manifest_path.write_text(json.dumps({
                    "schema_version": "hermes-in-run-input-binding-v1", "capture_mode": "IN_RUN_CAPTURE",
                    "binding": binding, "files": [{"path": tape_path.relative_to(archive.parent).as_posix(),
                                                   "sha256": hashlib.sha256(tape_path.read_bytes()).hexdigest()}],
                }))
                bind_score_run_inputs(
                    transaction, manifest_path=manifest_path,
                    expected_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                    decision_id=binding["decision_id"], input_hash=binding["input_hash"], _lease=lease,
                )
            with pytest.MonkeyPatch.context() as patch:
                def unavailable(*_args, **_kwargs):
                    raise OSError("synthetic publication failure")
                for name in fail:
                    patch.setattr(broker.modules[name], f"publish_{name}_cache", unavailable)
                broker.publish(transaction, _lease=lease)
        return _details(broker_run, {"persistence": {"run_id": transaction.run_id, "capture_id": capture_id},
                                   "decision_evidence": {"decision_id": binding["decision_id"]},
                                   "input_hash": binding["input_hash"]})
    return make


def _tree(root):
    return {path.relative_to(root).as_posix():
            (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns,
             path.stat().st_mode & 0o777)
            for path in root.rglob("*") if path.is_file()}


def test_matching_receipt_does_not_claim_or_read_current_cache_contents(broker_run, committed, tmp_path):
    for path in broker_run.caches.values():
        path.unlink()
    before = _tree(tmp_path)
    report = read_broker_publication_status(**committed.arguments)
    assert report["status"] == "OK"
    assert report["publication_status"] == "PUBLISHED"
    assert report["caches"] == {"positions": "PUBLISHED", "executions": "PUBLISHED"}
    assert report["scope"] == "OPERATIONS"
    assert report["strategy_blocking"] is False
    assert report["cache_contents_verified"] is False
    assert report["business_status"] == "COMMITTED"
    assert report["capture_id"] == committed.payload["persistence"]["capture_id"]
    assert _tree(tmp_path) == before


def test_missing_receipt_is_unknown_not_success_or_a_claim_that_caches_are_old(publication_run, tmp_path):
    run = publication_run()
    run.receipt.unlink()
    before = _tree(tmp_path)
    report = read_broker_publication_status(**run.arguments)
    assert report["status"] == "UNKNOWN"
    assert report["publication_status"] == "MISSING"
    assert report["reason"] == "RECEIPT_MISSING"
    assert report["business_status"] == "COMMITTED"
    assert report["caches"] == {}
    assert report["receipt_sha256"] is None
    assert report["strategy_blocking"] is False
    assert _tree(tmp_path) == before


@pytest.mark.parametrize(("sources", "fail", "status", "publication", "caches"), [
    (("tws", "tws"), ("positions",), "WARN", "PARTIAL", ("FAILED", "PUBLISHED")),
    (("tws", "tws"), ("positions", "executions"), "WARN", "FAILED", ("FAILED", "FAILED")),
    (("snapshot", "cache"), (), "INFO", "NOT_PUBLISHED", ("NOT_PUBLISHED", "NOT_PUBLISHED")),
    (("NOT_READ", "ERROR"), (), "INFO", "NOT_PUBLISHED", ("NOT_PUBLISHED", "NOT_PUBLISHED")),
    (("tws", "snapshot"), (), "INFO", "PARTIAL", ("PUBLISHED", "NOT_PUBLISHED")),
])
def test_valid_publication_outcomes_are_operations_only(
    publication_run, tmp_path, sources, fail, status, publication, caches,
):
    run = publication_run(sources=sources, fail=fail)
    before = _tree(tmp_path)
    report = read_broker_publication_status(**run.arguments)
    assert report["status"] == status
    assert report["publication_status"] == publication
    assert report["caches"] == dict(zip(("positions", "executions"), caches, strict=True))
    assert report["strategy_blocking"] is False
    assert report["scope"] == "OPERATIONS"
    assert report["cache_contents_verified"] is False
    assert "synthetic publication failure" not in json.dumps(report)
    assert _tree(tmp_path) == before


@pytest.mark.parametrize("damage", [
    "anchor", "missing_journal", "journal_json", "journal_shape", "schema", "pending", "run_id",
    "capture_id", "metadata", "binding", "decision_id", "input_hash", "manifest", "business", "tape",
])
def test_unverified_transaction_never_accepts_even_a_well_formed_receipt(publication_run, tmp_path, damage):
    run = publication_run()
    record = json.loads(run.journal.read_bytes())
    if damage == "anchor":
        run.arguments["expected_journal_sha256"] = "0" * 64
    elif damage == "missing_journal":
        run.journal.unlink()
    elif damage in {"journal_json", "journal_shape"}:
        run.journal.write_text("{" if damage == "journal_json" else "[]")
    elif damage in {"manifest", "business", "tape"}:
        capture = run.payload["persistence"]["capture_id"]
        target = {"manifest": f"decision_inputs/{capture}/manifest.json",
                  "tape": f"decision_inputs/{capture}/broker.json", "business": "audit_log.jsonl"}[damage]
        (run.arguments["archive_dir"] / target).unlink()
    else:
        if damage == "schema":
            record["schema_version"] = "hermes-score-run-transaction-v1"
        elif damage == "pending":
            record["status"] = "PENDING"
        elif damage == "run_id":
            record["run_id"] = uuid4().hex
        elif damage == "capture_id":
            record["capture_id"] = "../outside"
        elif damage == "metadata":
            record["metadata"] = []
        elif damage == "binding":
            del record["input_binding"]
        else:
            record["input_binding"][damage] = "other"
        run.journal.write_text(json.dumps(record))
    if damage not in {"anchor", "missing_journal"}:
        run.arguments["expected_journal_sha256"] = hashlib.sha256(run.journal.read_bytes()).hexdigest()
    before = _tree(tmp_path)
    report = read_broker_publication_status(**run.arguments)
    assert report["status"] == "UNKNOWN"
    assert report["publication_status"] == "UNVERIFIED"
    assert report["reason"] == "TRANSACTION_UNVERIFIED"
    assert report["business_status"] is None
    assert report["capture_id"] is None
    assert report["receipt_sha256"] is None
    assert report["caches"] == {}
    assert report["strategy_blocking"] is False
    assert _tree(tmp_path) == before


@pytest.mark.parametrize("damage", [
    "json", "utf8", "shape", "duplicate_key", "schema", "run_id", "capture_id", "business_status",
    "extra", "caches", "missing_cache", "extra_cache", "row", "status", "target", "error", "reason",
])
def test_malformed_or_foreign_receipt_is_unknown_without_partial_trust(publication_run, tmp_path, damage):
    run = publication_run()
    receipt = json.loads(run.receipt.read_bytes())
    if damage in {"json", "utf8", "shape", "duplicate_key"}:
        raw = {"json": b"{", "utf8": b"\xff", "shape": b"[]",
               "duplicate_key": (json.dumps(receipt)[:-1] + ',"run_id":' + json.dumps(receipt["run_id"]) + '}').encode()}[damage]
        run.receipt.write_bytes(raw)
    else:
        if damage in {"schema", "run_id", "capture_id", "business_status"}:
            receipt["schema_version" if damage == "schema" else damage] = "other"
        elif damage == "extra":
            receipt["unknown"] = True
        elif damage == "caches":
            receipt["caches"] = None
        elif damage == "missing_cache":
            del receipt["caches"]["executions"]
        elif damage == "extra_cache":
            receipt["caches"]["other"] = receipt["caches"]["positions"]
        else:
            receipt["caches"]["positions"] = {
                "row": [], "status": {"status": "FUTURE"}, "target": {"status": "PUBLISHED", "target": None},
                "error": {"status": "FAILED", "error": []},
                "reason": {"status": "NOT_PUBLISHED", "reason": ""},
            }[damage]
        run.receipt.write_text(json.dumps(receipt))
    before = _tree(tmp_path)
    report = read_broker_publication_status(**run.arguments)
    assert report["status"] == "UNKNOWN"
    assert report["publication_status"] == "INVALID"
    assert report["reason"] == "RECEIPT_INVALID"
    assert report["business_status"] == "COMMITTED"
    assert report["receipt_sha256"] is None
    assert report["caches"] == {}
    assert report["strategy_blocking"] is False
    assert _tree(tmp_path) == before


@pytest.mark.parametrize("damage", ["hidden_failure", "wrong_target", "false_live", "false_reason"])
def test_receipt_must_agree_with_authenticated_publication_intent(publication_run, tmp_path, damage):
    run = publication_run(sources=("snapshot", "tws") if damage in {"false_live", "false_reason"} else ("tws", "tws"))
    receipt = json.loads(run.receipt.read_bytes())
    if damage in {"hidden_failure", "false_reason"}:
        receipt["caches"]["positions"] = {"status": "NOT_PUBLISHED", "reason": "disabled"}
    elif damage == "wrong_target":
        receipt["caches"]["positions"]["target"] = "/never-open-this-cache.json"
    else:
        receipt["caches"]["positions"] = {"status": "PUBLISHED", "target": "/never-open-this-cache.json"}
    run.receipt.write_text(json.dumps(receipt))
    before = _tree(tmp_path)
    report = read_broker_publication_status(**run.arguments)
    assert report["status"] == "UNKNOWN"
    assert report["reason"] == "RECEIPT_INVALID"
    assert report["caches"] == {}
    assert _tree(tmp_path) == before


@pytest.mark.parametrize("damage", ["schema", "reads", "targets", "pending", "snapshot"])
def test_authenticated_but_unsupported_tape_is_not_publication_proof(publication_run, damage):
    def mutate(tape):
        if damage == "schema":
            tape["schema_version"] = "future"
        elif damage == "reads":
            tape["reads"] = []
        elif damage == "targets":
            tape["cache_targets"] = {"positions": "relative.json", "executions": "/other.json"}
        elif damage == "pending":
            tape["reads"]["positions"]["status"] = "PENDING"
        else:
            tape["reads"]["positions"]["snapshot"] = []
    run = publication_run(tape_change=mutate)
    report = read_broker_publication_status(**run.arguments)
    assert report["status"] == "UNKNOWN"
    assert report["reason"] == "TRANSACTION_UNVERIFIED"
    assert report["caches"] == {}


@pytest.mark.parametrize("target", ["journal", "receipt", "tape", "bundle"])
def test_linked_evidence_is_unknown_even_when_bytes_match(publication_run, tmp_path, target):
    run = publication_run()
    capture = run.payload["persistence"]["capture_id"]
    path = {"journal": run.journal, "receipt": run.receipt,
            "tape": run.arguments["archive_dir"] / "decision_inputs" / capture / "broker.json",
            "bundle": run.arguments["archive_dir"] / "decision_inputs" / capture}[target]
    moved = tmp_path / "linked-evidence"
    path.rename(moved)
    path.symlink_to(moved, target_is_directory=target == "bundle")
    before = _tree(tmp_path)
    report = read_broker_publication_status(**run.arguments)
    assert report["status"] == "UNKNOWN"
    assert report["reason"] == ("RECEIPT_INVALID" if target == "receipt" else "TRANSACTION_UNVERIFIED")
    assert report["caches"] == {}
    assert _tree(tmp_path) == before


@pytest.mark.parametrize("target", ["journal", "receipt"])
def test_unreadable_evidence_does_not_become_success(publication_run, monkeypatch, target):
    run = publication_run()
    path = run.journal if target == "journal" else run.receipt
    original = type(path).read_bytes
    def unreadable(current):
        if current == path:
            raise PermissionError("synthetic permission boundary")
        return original(current)
    monkeypatch.setattr(type(path), "read_bytes", unreadable)
    report = read_broker_publication_status(**run.arguments)
    assert report["status"] == "UNKNOWN"
    assert report["reason"] == ("RECEIPT_INVALID" if target == "receipt" else "TRANSACTION_UNVERIFIED")
    assert report["caches"] == {}


@pytest.mark.parametrize("bad_id", ["../outside", "", "0" * 31, "z" * 32, "A" * 32, None, []])
def test_invalid_run_identity_is_rejected_before_any_read(tmp_path, monkeypatch, bad_id):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("invalid run id must not access evidence")
    monkeypatch.setattr(type(tmp_path), "read_bytes", forbidden)
    with pytest.raises(ValueError):
        read_broker_publication_status(archive_dir=tmp_path / "absent", run_id=bad_id,
                                       expected_journal_sha256="0" * 64, decision_id="d", input_hash="b" * 64)
    assert not (tmp_path / "absent").exists()


def test_r6_archive_root_alias_preserves_matching_receipt(publication_run, tmp_path):
    run = publication_run()
    alias = tmp_path / "release-archive"
    alias.symlink_to(run.arguments["archive_dir"], target_is_directory=True)
    assert read_broker_publication_status(**{**run.arguments, "archive_dir": alias}) == read_broker_publication_status(**run.arguments)


def test_reader_only_opens_evidence_not_business_cache_or_lock_files(publication_run, broker_run, monkeypatch, tmp_path):
    run = publication_run()
    archive = run.arguments["archive_dir"]
    capture = run.payload["persistence"]["capture_id"]
    allowed = {run.journal, run.receipt, archive / "decision_inputs" / capture / "manifest.json",
               archive / "decision_inputs" / capture / "broker.json"}
    original = type(archive).open
    opened = []
    def evidence_only(path, mode="r", *args, **kwargs):
        assert path in allowed
        assert mode == "rb"
        opened.append(path)
        return original(path, mode, *args, **kwargs)
    before, calls = _tree(tmp_path), list(broker_run.calls)
    with monkeypatch.context() as patch:
        patch.setattr(type(archive), "open", evidence_only)
        report = read_broker_publication_status(**run.arguments)
    assert report["status"] == "OK"
    assert set(opened) == allowed
    assert broker_run.calls == calls
    assert _tree(tmp_path) == before


@pytest.mark.parametrize("kind", ["directory", "dangling_link"])
def test_nonregular_receipt_is_invalid_not_missing(publication_run, tmp_path, kind):
    run = publication_run()
    run.receipt.unlink()
    if kind == "directory":
        run.receipt.mkdir()
    else:
        run.receipt.symlink_to(tmp_path / "absent")
    report = read_broker_publication_status(**run.arguments)
    assert report["publication_status"] == "INVALID"
    assert report["caches"] == {}


@pytest.mark.parametrize("target", ["journal", "receipt", "input_manifest"])
def test_fifo_evidence_is_rejected_without_a_blocking_open(publication_run, monkeypatch, target):
    run = publication_run()
    capture = run.payload["persistence"]["capture_id"]
    path = {"journal": run.journal, "receipt": run.receipt,
            "input_manifest": run.arguments["archive_dir"] / "decision_inputs" / capture / "manifest.json"}[target]
    path.unlink()
    os.mkfifo(path)
    original = type(path).read_bytes
    def forbid_fifo(current):
        assert current != path, "FIFO must be rejected before a potentially blocking open"
        return original(current)
    monkeypatch.setattr(type(path), "read_bytes", forbid_fifo)
    report = read_broker_publication_status(**run.arguments)
    assert report["status"] == "UNKNOWN"
    assert report["reason"] == ("RECEIPT_INVALID" if target == "receipt" else "TRANSACTION_UNVERIFIED")
    assert report["caches"] == {}


@pytest.mark.parametrize("field", ["decision_id", "input_hash"])
def test_caller_binding_cannot_select_another_decision(publication_run, field):
    run = publication_run()
    report = read_broker_publication_status(**{**run.arguments, field: "other"})
    assert report["status"] == "UNKNOWN"
    assert report["reason"] == "TRANSACTION_UNVERIFIED"
    assert report["caches"] == {}
