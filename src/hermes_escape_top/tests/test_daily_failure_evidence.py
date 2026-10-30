"""Failed daily finalization must retain current, truthful diagnostic evidence."""
from __future__ import annotations

import json
import socket
from datetime import date
from types import SimpleNamespace

import pytest

from hermes_escape_top.scripts import run_daily_package as rdp


AS_OF = "2026-10-20"


@pytest.fixture
def daily(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        rdp, "load_config", lambda: {"paths": {"archive_dir": "data/archive"}},
    )
    monkeypatch.setattr(
        rdp, "_last_bar_dates",
        lambda: {"QQQ": date(2026, 10, 21), "SOXL": date(2026, 10, 20)},
    )
    monkeypatch.setattr(
        "hermes_escape_top.web.refresh.manifest_status",
        lambda _config=None: {"status": "OK"},
    )
    monkeypatch.setattr(
        rdp, "_system_health_generator_identity",
        lambda: {"generator_release_hash": "test-release", "generator_policy_sha256": "test-policy"},
    )

    def no_network(*_args, **_kwargs):
        pytest.fail("daily finalization must not request network data")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    payload = {
        "as_of": AS_OF,
        "run_type": "scheduled",
        "input_hash": "a" * 64,
        "decision_evidence": {"decision_hash": "current-decision"},
    }

    def execute(*, _run_context, **_kwargs):
        _run_context["as_of"] = AS_OF
        return payload

    flow_calls = []

    def attach_flow(value, as_of):
        flow_calls.append(as_of)
        value["alpaca_daily_flow_status"] = {"status": "OK", "as_of": as_of}
        return value

    monkeypatch.setattr(rdp, "_execute_daily", execute)
    monkeypatch.setattr(rdp, "_attach_alpaca_flow_for_health", attach_flow)
    return SimpleNamespace(
        args=SimpleNamespace(live=True, run_type="scheduled", as_of=AS_OF),
        root=tmp_path,
        receipt=tmp_path / "data/archive/run_receipt.json",
        payload=payload,
        flow_calls=flow_calls,
    )


def test_failed_end_state_identifies_receipt_not_successful_flow(daily):
    with pytest.raises(RuntimeError, match="scheduled run end-state receipt failed"):
        rdp._run_daily_with_receipt(daily.args, _lease=object())

    receipt = json.loads(daily.receipt.read_text())
    assert daily.flow_calls == [AS_OF]
    assert receipt["status"] == "FAILED"
    assert receipt["failed_step"] == "run_receipt"
    assert any(row["name"] == "as_of_latest" and not row["ok"] for row in receipt["checks"])


@pytest.mark.parametrize("implicit_date", [False, True])
def test_failed_self_check_writes_current_bound_health_report(daily, implicit_date):
    if implicit_date:
        daily.args.as_of = None
    report_path = daily.root / f"reports/system_health_{AS_OF}.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps({"input_hash": "old-input", "run_receipt": {"status": "OK"}}))

    with pytest.raises(RuntimeError, match="scheduled run end-state receipt failed"):
        rdp._run_daily_with_receipt(daily.args, _lease=object())

    report = json.loads(report_path.read_text())
    receipt = json.loads(daily.receipt.read_text())
    assert report["as_of"] == AS_OF
    assert report["input_hash"] == daily.payload["input_hash"]
    assert report["decision_hash"] == "current-decision"
    assert report["run_receipt"] == receipt
    assert report["run_receipt"]["status"] == "FAILED"
    assert report["health"]["level"] == "CRITICAL"
    scheduled = next(row for row in report["audit_dimensions"] if row["id"] == "scheduled_receipt")
    assert scheduled["status"] == "FAIL"
    assert "FAILED" in report_path.with_suffix(".md").read_text()
    archived = list((report_path.parent / "system_health_runs").glob("*.json"))
    assert len(archived) == 1
    assert json.loads(archived[0].read_text()) == report


def test_secondary_report_failure_preserves_original_error(daily, monkeypatch, capsys):
    def fail_report(*_args, **_kwargs):
        raise OSError("health storage unavailable")

    monkeypatch.setattr(rdp, "_write_system_health_report", fail_report)
    with pytest.raises(RuntimeError, match="scheduled run end-state receipt failed"):
        rdp._run_daily_with_receipt(daily.args, _lease=object())

    receipt = json.loads(daily.receipt.read_text())
    assert receipt["failed_step"] == "run_receipt"
    assert "health storage unavailable" in capsys.readouterr().out


def test_failure_before_scoring_result_does_not_fabricate_report(daily, monkeypatch):
    def fail_execute(*, _run_context, **_kwargs):
        _run_context["step"] = "score_pipeline"
        raise ValueError("scoring failed before returning inputs")

    def unexpected_report(*_args, **_kwargs):
        pytest.fail("must not manufacture a bound report without the current payload")

    monkeypatch.setattr(rdp, "_execute_daily", fail_execute)
    monkeypatch.setattr(rdp, "_write_system_health_report", unexpected_report)
    with pytest.raises(ValueError, match="scoring failed before returning inputs"):
        rdp._run_daily_with_receipt(daily.args, _lease=object())

    receipt = json.loads(daily.receipt.read_text())
    assert receipt["status"] == "FAILED"
    assert receipt["failed_step"] == "score_pipeline"
    assert not (daily.root / "reports").exists()


def test_missing_failed_receipt_cannot_be_replaced_by_synthetic_health(daily, monkeypatch):
    write_json = rdp._atomic_write_json

    def fail_finished_receipt(path, value):
        if path == daily.receipt and value.get("status") == "FAILED":
            raise OSError("receipt storage unavailable")
        write_json(path, value)

    monkeypatch.setattr(rdp, "_atomic_write_json", fail_finished_receipt)
    with pytest.raises(RuntimeError, match="scheduled run end-state receipt failed"):
        rdp._run_daily_with_receipt(daily.args, _lease=object())

    assert not daily.receipt.exists()
    assert not (daily.root / "reports").exists()


def test_initial_health_failure_can_only_be_replaced_by_failed_report(daily, monkeypatch):
    monkeypatch.setattr(rdp, "_last_bar_dates", lambda: {})
    write_health = rdp._write_system_health_report
    statuses = []

    def fail_first_health(payload, as_of, receipt, shadow=False):
        statuses.append(receipt["status"])
        if len(statuses) == 1:
            raise OSError("initial health report failure")
        return write_health(payload, as_of, receipt, shadow=shadow)

    monkeypatch.setattr(rdp, "_write_system_health_report", fail_first_health)
    with pytest.raises(OSError, match="initial health report failure"):
        rdp._run_daily_with_receipt(daily.args, _lease=object())

    report = json.loads((daily.root / f"reports/system_health_{AS_OF}.json").read_text())
    assert statuses == ["OK", "FAILED"]
    assert report["run_receipt"]["failed_step"] == "system_health_report"
    assert report["health"]["level"] == "CRITICAL"


@pytest.mark.parametrize("live,run_type", [(False, "shadow"), (True, "manual_rerun")])
def test_unofficial_failure_does_not_publish_official_evidence(daily, monkeypatch, live, run_type):
    daily.args.live = live
    daily.args.run_type = run_type

    def fail_execute(**_kwargs):
        raise ValueError("unofficial failure")

    monkeypatch.setattr(rdp, "_execute_daily", fail_execute)
    with pytest.raises(ValueError, match="unofficial failure"):
        rdp._run_daily_with_receipt(daily.args, _lease=object())

    assert not daily.receipt.exists()
    assert not (daily.root / "reports").exists()
