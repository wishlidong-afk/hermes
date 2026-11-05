"""Sandbox-only producer to official receipt integration; no live entry point."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from hermes_escape_top import pipeline
from hermes_escape_top.config import load_config
from hermes_escape_top.core.data import run_transaction
from hermes_escape_top.core.reporting.broker_capture import BrokerCapture
from hermes_escape_top.core.safe_io import pipeline_lock
from hermes_escape_top.scripts import run_daily_package as rdp
from test_a2_production_capture import capture_root as capture_root
from test_broker_input_capture import broker_run as broker_run
from test_score_transaction_v2 import AS_OF


@pytest.fixture
def receipt_run(broker_run, monkeypatch):
    config = load_config(broker_run.config_path)
    monkeypatch.setattr(rdp, "load_config", lambda: config)
    monkeypatch.setattr(rdp, "_last_bar_dates", lambda: {})
    monkeypatch.setattr("hermes_escape_top.web.refresh.manifest_status", lambda _config: {"status": "OK"})
    monkeypatch.setattr(rdp, "_attach_alpaca_flow_for_health", lambda payload, _as_of: payload)
    health_receipts = []
    monkeypatch.setattr(rdp, "_write_system_health_report",
                        lambda _payload, _as_of, receipt, **_: health_receipts.append(receipt))
    monkeypatch.setattr(rdp, "_preflight_report", lambda *_: None)
    monkeypatch.setattr(rdp, "_history_integrity_scan", lambda *_: [])
    monkeypatch.setattr(rdp, "translate", lambda _payload: {})
    monkeypatch.setattr(rdp, "write_artifacts", lambda *_, **__: None)
    monkeypatch.setattr(rdp, "_post_run_diff", lambda *_: None)
    monkeypatch.setattr(rdp, "_refresh_next5_unlock", lambda: None)
    monkeypatch.setattr(rdp.refresh_external, "status", lambda *_: {})
    monkeypatch.setattr("hermes_escape_top.core.data.audit.rotate_audit_log", lambda *_: None)
    locked = pipeline._score_pipeline_locked

    def score(*args, **kwargs):
        return locked(*args, config_path=broker_run.config_path, include_ibkr=False, **kwargs)

    monkeypatch.setattr(pipeline, "_score_pipeline_locked", score)
    return SimpleNamespace(
        args=SimpleNamespace(live=True, run_type="scheduled", as_of=AS_OF,
                             skip_refresh=True, commit_state=False),
        archive=broker_run.archive, health_receipts=health_receipts,
    )


def test_explicit_capture_reaches_receipt_without_changing_scoring_payload(receipt_run):
    with pipeline_lock(path=receipt_run.archive / ".pipeline.lock") as lease:
        rdp._run_daily_with_receipt(receipt_run.args, _lease=lease, capture_inputs=True)
    receipt = json.loads((receipt_run.archive / "run_receipt.json").read_bytes())
    observation = receipt["commit_observation"]
    audit = json.loads((receipt_run.archive / "audit_log.jsonl").read_text().splitlines()[-1])["payload"]
    journal = receipt_run.archive / f".score_run_transactions/runs/{observation['run_id']}/manifest.json"
    assert receipt["status"] == "OK"
    assert observation["journal_sha256"] == hashlib.sha256(journal.read_bytes()).hexdigest()
    assert observation["run_id"] == audit["persistence"]["run_id"]
    assert observation["capture_id"] == audit["persistence"]["capture_id"]
    assert observation["decision_id"] == audit["decision_evidence"]["decision_id"]
    assert observation["input_hash"] == audit["input_hash"]
    assert "commit_observation" not in audit
    assert receipt_run.health_receipts == [receipt]


def test_same_date_repeated_runs_have_distinct_current_receipt_observations(receipt_run):
    observations = []
    with pipeline_lock(path=receipt_run.archive / ".pipeline.lock") as lease:
        for _ in range(2):
            rdp._run_daily_with_receipt(receipt_run.args, _lease=lease, capture_inputs=True)
            observations.append(json.loads((receipt_run.archive / "run_receipt.json").read_bytes())["commit_observation"])
    assert observations[0]["run_id"] != observations[1]["run_id"]
    assert observations[0]["capture_id"] != observations[1]["capture_id"]
    assert observations[0]["decision_id"] == observations[1]["decision_id"]
    for value in observations:
        journal = receipt_run.archive / f".score_run_transactions/runs/{value['run_id']}/manifest.json"
        assert value["journal_sha256"] == hashlib.sha256(journal.read_bytes()).hexdigest()


@pytest.mark.parametrize("failure", ["cleanup", "broker", "receipt", "health"])
def test_post_commit_failure_keeps_business_and_never_certifies_ok(receipt_run, monkeypatch, failure):
    def unavailable(*_, **__):
        raise OSError(f"injected {failure} failure")

    if failure == "cleanup":
        monkeypatch.setattr(run_transaction, "_clear_active", unavailable)
    elif failure == "broker":
        monkeypatch.setattr(BrokerCapture, "publish", unavailable)
    elif failure == "receipt":
        original = rdp._atomic_write_json

        def write(path, value):
            if value["status"] == "OK":
                unavailable()
            return original(path, value)
        monkeypatch.setattr(rdp, "_atomic_write_json", write)
    else:
        monkeypatch.setattr(rdp, "_write_system_health_report", unavailable)
    with pipeline_lock(path=receipt_run.archive / ".pipeline.lock") as lease:
        with pytest.raises((OSError, RuntimeError)):
            rdp._run_daily_with_receipt(receipt_run.args, _lease=lease, capture_inputs=True)
    receipt = json.loads((receipt_run.archive / "run_receipt.json").read_bytes())
    assert receipt["status"] == "FAILED"
    assert receipt["ok"] is False
    observation = receipt["commit_observation"]
    record = run_transaction.load_score_run_transaction(receipt_run.archive, observation["run_id"])
    assert record["status"] == "COMMITTED"
    assert len([row for row in record["artifacts"] if row["role"] == "BUSINESS"]) == 7
    assert all((receipt_run.archive.parent / row["path"]).is_file() for row in record["artifacts"])
    assert observation["journal_sha256"] == hashlib.sha256(
        (receipt_run.archive / f".score_run_transactions/runs/{observation['run_id']}/manifest.json").read_bytes(),
    ).hexdigest()


def test_failed_next_invocation_does_not_reuse_previous_observation(receipt_run, monkeypatch):
    with pipeline_lock(path=receipt_run.archive / ".pipeline.lock") as lease:
        rdp._run_daily_with_receipt(receipt_run.args, _lease=lease, capture_inputs=True)
        previous = (receipt_run.archive / "run_receipt.json").read_bytes()

        def fail(**_):
            raise OSError("failed before commit")

        monkeypatch.setattr(rdp, "_execute_daily", fail)
        with pytest.raises(OSError, match="failed before commit"):
            rdp._run_daily_with_receipt(receipt_run.args, _lease=lease, capture_inputs=True)
    assert "commit_observation" in json.loads(previous)
    receipt = json.loads((receipt_run.archive / "run_receipt.json").read_bytes())
    assert receipt["status"] == "FAILED"
    assert "commit_observation" not in receipt


def _observation():
    return {
        "schema_version": "hermes-score-commit-observation-v1", "protocol": "recoverable-journal-v2",
        "run_id": "a" * 32, "capture_id": "b" * 32, "as_of": AS_OF,
        "decision_id": "synthetic-decision", "input_hash": "c" * 64,
        "journal_sha256": "d" * 64, "committed_at": datetime.now(timezone.utc).isoformat(),
    }


@pytest.mark.parametrize("field", ["run_id", "capture_id", "decision_id", "input_hash", "protocol", "as_of"])
def test_wrong_result_binding_is_not_carried_into_receipt(receipt_run, monkeypatch, field):
    def execute(*, commit_observer, **_):
        value = _observation()
        commit_observer(value)
        payload = {"as_of": AS_OF, "input_hash": value["input_hash"],
                   "persistence": {key: value[key] for key in ("run_id", "capture_id", "protocol")},
                   "decision_evidence": {"decision_id": value["decision_id"]}}
        target = (payload["persistence"] if field in {"run_id", "capture_id", "protocol"}
                  else payload["decision_evidence"] if field == "decision_id" else payload)
        target[field] = "wrong-result"
        return payload

    monkeypatch.setattr(rdp, "_execute_daily", execute)
    with pytest.raises(ValueError, match="does not match this scoring result"):
        rdp._run_daily_with_receipt(receipt_run.args, _lease=object(), capture_inputs=True)
    receipt = json.loads((receipt_run.archive / "run_receipt.json").read_bytes())
    assert receipt["status"] == "FAILED"
    assert "commit_observation" not in receipt


@pytest.mark.parametrize("damage", ["schema", "uuid", "digest", "missing", "extra", "naive", "old", "future"])
def test_invalid_or_stale_observation_cannot_replace_receipt(receipt_run, damage):
    value = _observation()
    if damage == "schema":
        value["schema_version"] = "future-v2"
    elif damage == "uuid":
        value["run_id"] = "../other"
    elif damage == "digest":
        value["journal_sha256"] = "d" * 16
    elif damage == "missing":
        del value["input_hash"]
    elif damage == "extra":
        value["account"] = "must-not-leak"
    else:
        stamp = datetime.now(timezone.utc)
        if damage == "old":
            stamp -= timedelta(days=1)
        elif damage == "future":
            stamp += timedelta(days=1)
        value["committed_at"] = (stamp.replace(tzinfo=None) if damage == "naive" else stamp).isoformat()
    before = {path: path.read_bytes() for path in receipt_run.archive.rglob("*") if path.is_file()}
    receipt = rdp._write_run_receipt(
        AS_OF, "scheduled", commit_observation=value,
        started_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
    )
    assert receipt is None
    assert not (receipt_run.archive / "run_receipt.json").exists()
    assert {path: path.read_bytes() for path in receipt_run.archive.rglob("*") if path.is_file()} == before


def test_default_daily_path_has_no_observation_or_capture_artifacts(receipt_run):
    with pipeline_lock(path=receipt_run.archive / ".pipeline.lock") as lease:
        rdp._run_daily_with_receipt(receipt_run.args, _lease=lease)
    receipt = json.loads((receipt_run.archive / "run_receipt.json").read_bytes())
    assert receipt["status"] == "OK"
    assert "commit_observation" not in receipt
    assert not (receipt_run.archive / "decision_inputs").exists()
    assert not (receipt_run.archive / "broker_cache_publications").exists()


def test_receipt_failure_never_leaves_a_previous_ok_anchor(receipt_run, monkeypatch):
    def unavailable(*_, **__):
        raise OSError("all final receipt writes failed")

    original = rdp._atomic_write_json

    def write(path, value):
        if value["status"] != "RUNNING":
            unavailable()
        return original(path, value)

    monkeypatch.setattr(rdp, "_atomic_write_json", write)
    with pipeline_lock(path=receipt_run.archive / ".pipeline.lock") as lease:
        with pytest.raises(RuntimeError, match="end-state receipt failed"):
            rdp._run_daily_with_receipt(receipt_run.args, _lease=lease, capture_inputs=True)
    assert not (receipt_run.archive / "run_receipt.json").exists()
    audit = json.loads((receipt_run.archive / "audit_log.jsonl").read_text().splitlines()[-1])["payload"]
    assert run_transaction.load_score_run_transaction(
        receipt_run.archive, audit["persistence"]["run_id"],
    )["status"] == "COMMITTED"


@pytest.mark.parametrize("live,run_type", [(False, "scheduled"), (True, "manual_rerun")])
def test_capture_is_not_exposed_to_unofficial_receipts(receipt_run, live, run_type):
    receipt_run.args.live = live
    receipt_run.args.run_type = run_type
    with pytest.raises(ValueError, match="requires a non-shadow scheduled invocation"):
        rdp._run_daily_with_receipt(receipt_run.args, _lease=object(), capture_inputs=True)
    assert not (receipt_run.archive / "run_receipt.json").exists()


def test_running_receipt_cannot_carry_a_commit_observation(receipt_run):
    receipt = rdp._write_run_receipt(
        AS_OF, "scheduled", status="RUNNING", commit_observation=_observation(),
    )
    assert receipt is None
    assert not (receipt_run.archive / "run_receipt.json").exists()
