"""Characterize existing anchor sources; do not implement producer attestation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hermes_escape_top import pipeline
from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.run_transaction import pending_score_run_transaction
from hermes_escape_top.core.reporting.broker_publication_status import read_broker_publication_status
from hermes_escape_top.scripts import run_daily_package as rdp
from test_a2_production_capture import capture_root as capture_root
from test_broker_input_capture import broker_run as broker_run
from test_broker_publication_status import publication_run as publication_run
from test_morning_acceptance import _load_module


def test_existing_v2_outputs_bind_ids_but_do_not_export_final_journal_anchor(broker_run, monkeypatch):
    archive = broker_run.archive
    observed = {}
    checkpoint = pipeline._persistence_checkpoint

    def observe(stage):
        checkpoint(stage)
        if stage == "signal_journal":
            pending = pending_score_run_transaction(archive)
            journal = archive / f".score_run_transactions/runs/{pending['run_id']}/manifest.json"
            observed.update(status=pending["status"], journal=journal,
                            pending_sha256=hashlib.sha256(journal.read_bytes()).hexdigest())

    monkeypatch.setattr(pipeline, "_persistence_checkpoint", observe)
    payload = pipeline.score_pipeline(
        "2026-05-29", config_path=broker_run.config_path, include_ibkr=False,
        run_type="scheduled", capture_inputs=True,
    )
    persistence = payload["persistence"]
    assert set(persistence) == {"run_id", "protocol", "capture_id", "recovered_run_id"}
    assert persistence["protocol"] == "recoverable-journal-v2"
    journal = observed["journal"]
    record = json.loads(journal.read_bytes())
    assert observed["status"] == "PENDING"
    assert record["status"] == "COMMITTED"
    assert observed["pending_sha256"] != hashlib.sha256(journal.read_bytes()).hexdigest()

    audit = json.loads((archive / "audit_log.jsonl").read_text().splitlines()[-1])["payload"]
    assert audit["persistence"] == persistence
    capture = archive / "decision_inputs" / persistence["capture_id"]
    manifest = json.loads((capture / "manifest.json").read_bytes())
    assert manifest["binding"] == {
        "run_id": persistence["run_id"], "capture_id": persistence["capture_id"],
        "as_of": payload["as_of"], "decision_id": payload["decision_evidence"]["decision_id"],
        "input_hash": payload["input_hash"],
    }
    assert not any(row["path"].startswith("archive/.score_run_transactions/") for row in manifest["files"])
    report = read_broker_publication_status(
        archive_dir=archive, run_id=persistence["run_id"],
        expected_journal_sha256=observed["pending_sha256"],
        decision_id=payload["decision_evidence"]["decision_id"], input_hash=payload["input_hash"],
    )
    assert report["status"] == "UNKNOWN"
    assert report["reason"] == "TRANSACTION_UNVERIFIED"


@pytest.mark.parametrize("source", ["input_manifest", "auxiliary_receipt"])
def test_other_artifact_digests_cannot_substitute_for_a_commit_anchor(publication_run, source):
    run = publication_run()
    record = json.loads(run.journal.read_bytes())
    digest = (record["input_binding"]["manifest_sha256"] if source == "input_manifest"
              else hashlib.sha256(run.receipt.read_bytes()).hexdigest())
    assert digest != run.arguments["expected_journal_sha256"]
    report = read_broker_publication_status(**{**run.arguments, "expected_journal_sha256": digest})
    assert report["status"] == "UNKNOWN"
    assert report["reason"] == "TRANSACTION_UNVERIFIED"
    assert report["caches"] == {}


def test_self_hashing_changed_journal_cannot_prove_trusted_issuance(publication_run):
    run = publication_run()
    record = json.loads(run.journal.read_bytes())
    record["committed_at"] = "2000-01-01T00:00:00+00:00"
    run.journal.write_text(json.dumps(record))
    refused = read_broker_publication_status(**run.arguments)
    assert refused["reason"] == "TRANSACTION_UNVERIFIED"

    # Deliberately supplying a replacement anchor is outside the reader's trust guarantee.
    self_hash = hashlib.sha256(run.journal.read_bytes()).hexdigest()
    declaration = read_broker_publication_status(**{**run.arguments, "expected_journal_sha256": self_hash})
    assert declaration["status"] == "OK"
    assert declaration["cache_contents_verified"] is False


def test_default_off_is_v1_without_a_capture_publication_receipt(broker_run):
    payload = pipeline.score_pipeline(
        "2026-05-29", config_path=broker_run.config_path, include_ibkr=False, run_type="scheduled",
    )
    persistence = payload["persistence"]
    assert persistence["protocol"] == "recoverable-journal-v1"
    assert "capture_id" not in persistence
    archive = broker_run.archive
    assert not (archive / "decision_inputs").exists()
    assert not (archive / "broker_cache_publications" / f"{persistence['run_id']}.json").exists()
    journal = archive / f".score_run_transactions/runs/{persistence['run_id']}/manifest.json"
    report = read_broker_publication_status(
        archive_dir=archive, run_id=persistence["run_id"],
        expected_journal_sha256=hashlib.sha256(journal.read_bytes()).hexdigest(),
        decision_id=payload["decision_evidence"]["decision_id"], input_hash=payload["input_hash"],
    )
    assert report["status"] == "UNKNOWN"
    assert report["reason"] == "TRANSACTION_UNVERIFIED"


def test_official_receipt_records_completion_not_a_run_specific_commit_anchor(broker_run, monkeypatch):
    config = load_config(broker_run.config_path)
    monkeypatch.setattr(rdp, "load_config", lambda: config)
    monkeypatch.setattr(rdp, "_last_bar_dates", lambda: {})
    monkeypatch.setattr("hermes_escape_top.web.refresh.manifest_status", lambda _config: {"status": "OK"})
    receipt = rdp._write_run_receipt("2026-05-29", "scheduled")
    assert receipt["ok"] is True
    assert set(receipt) == {
        "status", "run_at", "started_at", "finished_at", "as_of", "run_type", "ok",
        "failed_step", "error", "checks",
    }
    assert json.loads((broker_run.archive / "run_receipt.json").read_bytes()) == receipt


def test_transaction_acceptance_check_returns_a_pointer_not_a_digest_anchor(publication_run):
    run = publication_run()
    audit = {**run.payload, "as_of": "2026-05-29",
             "persistence": {**run.payload["persistence"], "protocol": "recoverable-journal-v2"}}
    validator = Path(__file__).resolve().parents[1] / "core/data/transaction_evidence.py"
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest()
              for path in run.arguments["archive_dir"].rglob("*") if path.is_file()}
    check = _load_module()._collect_transaction(
        run.arguments["archive_dir"], audit, require_soft_snapshot=True, validator_path=validator,
    )
    assert check["status"] == "PASS"
    assert set(check) == {"id", "status", "detail", "evidence"}
    assert Path(check["evidence"]) == run.journal
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in run.arguments["archive_dir"].rglob("*") if path.is_file()} == before
