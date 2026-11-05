"""Cross-contract checks for the isolated A2 and deployed-hotfix integration."""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

import pytest

from hermes_escape_top.core.data.run_transaction import load_score_run_transaction
from hermes_escape_top.core.data.transaction_evidence import business_paths
from hermes_escape_top.core.safe_io import pipeline_lock
from hermes_escape_top.scripts import run_daily_package as daily
from test_a2_production_capture import capture_root as capture_root
from test_broker_input_capture import broker_run as broker_run
from test_commit_observation_receipt import receipt_run as receipt_run
from test_deploy_offline_verification import preview as preview
from test_score_transaction_v2 import AS_OF


_WRITE_HEALTH = daily._write_system_health_report


def _business_bytes(archive):
    return {name: (archive.parent / name).read_bytes() for name in business_paths(AS_OF)}


def _committed_receipt(receipt_run, before):
    archive = receipt_run.archive
    receipt = json.loads((archive / "run_receipt.json").read_bytes())
    observation = receipt["commit_observation"]
    record = load_score_run_transaction(archive, observation["run_id"])
    assert record["status"] == "COMMITTED"
    assert len([row for row in record["artifacts"] if row["role"] == "BUSINESS"]) == 7
    assert _business_bytes(archive) == before
    assert not (archive / ".score_run_transactions/active.json").exists()
    journal = archive / f".score_run_transactions/runs/{observation['run_id']}/manifest.json"
    assert observation["journal_sha256"] == hashlib.sha256(journal.read_bytes()).hexdigest()
    payload = json.loads((archive / "audit_log.jsonl").read_text().splitlines()[-1])["payload"]
    assert observation["input_hash"] == payload["input_hash"]
    assert observation["decision_id"] == payload["decision_evidence"]["decision_id"]
    assert observation["capture_id"] == payload["persistence"]["capture_id"]
    return receipt, payload


@pytest.mark.parametrize("health_storage_failure", [False, True])
def test_failed_freshness_retains_commit_anchor_and_current_failed_health(
    receipt_run, monkeypatch, capsys, health_storage_failure,
):
    before = {}

    def flow(payload, _as_of):
        before.update(_business_bytes(receipt_run.archive))
        return payload

    monkeypatch.setattr(daily, "_attach_alpaca_flow_for_health", flow)
    monkeypatch.setattr(daily, "_last_bar_dates", lambda: {
        "SOXL": date.fromisoformat(AS_OF), "QQQ": date.fromisoformat(AS_OF) + timedelta(days=1),
    })
    monkeypatch.setattr(daily, "_system_health_generator_identity", lambda: {
        "generator_release_hash": "isolated-integration", "generator_policy_sha256": "a" * 64,
    })

    def unavailable(*_args, **_kwargs):
        raise OSError("integration health storage unavailable")

    monkeypatch.setattr(daily, "_write_system_health_report",
                        unavailable if health_storage_failure else _WRITE_HEALTH)
    with pipeline_lock(path=receipt_run.archive / ".pipeline.lock") as lease:
        with pytest.raises(RuntimeError, match="scheduled run end-state receipt failed"):
            daily._run_daily_with_receipt(receipt_run.args, _lease=lease, capture_inputs=True)

    receipt, payload = _committed_receipt(receipt_run, before)
    assert receipt["status"] == "FAILED" and receipt["ok"] is False
    assert receipt["failed_step"] == "run_receipt"
    assert any(row["name"] == "as_of_latest" and not row["ok"] for row in receipt["checks"])
    if health_storage_failure:
        assert "integration health storage unavailable" in capsys.readouterr().out
        assert not daily._system_health_report_dir().exists()
    else:
        report = json.loads((daily._system_health_report_dir() / f"system_health_{AS_OF}.json").read_bytes())
        assert report["run_receipt"] == receipt
        assert report["input_hash"] == payload["input_hash"]
        assert report["decision_hash"] == payload["decision_evidence"]["decision_hash"]
        assert report["health"]["level"] == "CRITICAL"
        assert next(row for row in report["audit_dimensions"]
                    if row["id"] == "scheduled_receipt")["status"] == "FAIL"


def test_initial_health_failure_preserves_anchor_in_failed_replacement(receipt_run, monkeypatch):
    before = {}
    statuses = []

    def flow(payload, _as_of):
        before.update(_business_bytes(receipt_run.archive))
        return payload

    def report(_payload, _as_of, receipt, **_kwargs):
        statuses.append(receipt)
        if len(statuses) == 1:
            raise OSError("integration initial health failure")

    monkeypatch.setattr(daily, "_attach_alpaca_flow_for_health", flow)
    monkeypatch.setattr(daily, "_write_system_health_report", report)
    with pipeline_lock(path=receipt_run.archive / ".pipeline.lock") as lease:
        with pytest.raises(OSError, match="integration initial health failure"):
            daily._run_daily_with_receipt(receipt_run.args, _lease=lease, capture_inputs=True)
    receipt, _payload = _committed_receipt(receipt_run, before)
    assert [row["status"] for row in statuses] == ["OK", "FAILED"]
    assert statuses[0]["commit_observation"] == statuses[1]["commit_observation"]
    assert statuses[1] == receipt
    assert receipt["failed_step"] == "system_health_report"


def test_capture_forwarding_keeps_explicit_broker_disable(monkeypatch):
    calls = []

    def observer(_value):
        pass

    lease = object()
    monkeypatch.setattr(daily.pipeline, "_score_pipeline_locked",
                        lambda *args, **kwargs: calls.append((args, kwargs)) or {})
    daily.run_score_pipeline(AS_OF, shadow=False, run_type="scheduled", capture_inputs=True,
                             commit_observer=observer, include_ibkr=False, _lease=lease)
    assert calls == [((AS_OF,), {
        "shadow": False, "run_type": "scheduled", "market_admission_status": None,
        "capture_inputs": True, "commit_observer": observer, "_lease": lease, "include_ibkr": False,
    })]


def test_offline_preview_cannot_enter_capture_path(preview, monkeypatch):
    root, args = preview
    monkeypatch.setattr(daily, "_execute_daily",
                        lambda **_kwargs: pytest.fail("unofficial preview entered capture producer"))
    with daily._deploy_verification_guard(args):
        with pytest.raises(ValueError, match="capture requires a non-shadow scheduled invocation"):
            daily._run_daily_with_receipt(args, _lease=object(), capture_inputs=True)
    assert not (root / "data").exists()
