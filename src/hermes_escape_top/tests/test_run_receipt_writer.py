"""The run receipt is the trust attestation, so it must be written LAST and must
go RED when a required step failed — never certify green just because the
data-state self-checks pass (the 2026-06-18 review: receipt was stamped before
commit_state, so a failed state commit could still show '自检全绿')."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from hermes_escape_top.scripts import run_daily_package as rdp


def _patch(monkeypatch, tmp_path):
    monkeypatch.setattr(rdp, "load_config", lambda: {"_t": 1})
    monkeypatch.setattr(rdp, "_last_bar_dates", lambda: {})
    monkeypatch.setattr("hermes_escape_top.config.resolve_path", lambda c, k: tmp_path)
    monkeypatch.setattr("hermes_escape_top.web.refresh.manifest_status", lambda c=None: {"status": "OK"})


def test_receipt_red_when_a_required_step_failed(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    rdp._write_run_receipt("2026-06-17", "scheduled", steps_ok=False, step_error="state commit failed: boom")
    r = json.loads((tmp_path / "run_receipt.json").read_text())
    assert r["ok"] is False
    assert any(c["name"] == "run_steps" and not c["ok"] for c in r["checks"])
    assert "boom" in next(c["detail"] for c in r["checks"] if c["name"] == "run_steps")


def test_receipt_green_when_steps_ok_and_checks_pass(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    rdp._write_run_receipt("2026-06-17", "scheduled", steps_ok=True)
    r = json.loads((tmp_path / "run_receipt.json").read_text())
    assert r["ok"] is True
    assert not any(c["name"] == "run_steps" for c in r["checks"])  # no failure check added


def test_receipt_running_state_has_no_finished_at(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    rdp._write_run_receipt(
        "2026-06-17",
        "scheduled",
        status="RUNNING",
        started_at="2026-06-17T07:10:00+08:00",
    )
    r = json.loads((tmp_path / "run_receipt.json").read_text())
    assert r["status"] == "RUNNING"
    assert r["started_at"] == "2026-06-17T07:10:00+08:00"
    assert r["finished_at"] is None
    assert r["ok"] is False


def test_top_level_failure_overwrites_running_receipt(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    args = SimpleNamespace(live=True, run_type="scheduled", as_of="2026-06-17")

    def fail(*, args, _lease, _run_context):
        _run_context["step"] = "artifact_write"
        raise OSError("disk full")

    monkeypatch.setattr(rdp, "_execute_daily", fail)
    with pytest.raises(OSError, match="disk full"):
        rdp._run_daily_with_receipt(args, _lease=object())

    receipt = json.loads((tmp_path / "run_receipt.json").read_text())
    assert receipt["status"] == "FAILED"
    assert receipt["failed_step"] == "artifact_write"
    assert "disk full" in receipt["error"]
    assert receipt["finished_at"]


def test_scheduled_run_writes_system_health_report_after_ok_receipt(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    args = SimpleNamespace(live=True, run_type="scheduled", as_of="2026-06-17")
    captured = {}

    monkeypatch.setattr(rdp, "_execute_daily", lambda **_kwargs: {"as_of": "2026-06-17"})
    monkeypatch.setattr(
        rdp,
        "_write_system_health_report",
        lambda payload, as_of, receipt, shadow=False: captured.update(
            {"payload": payload, "as_of": as_of, "receipt": receipt, "shadow": shadow}
        ),
    )

    rdp._run_daily_with_receipt(args, _lease=object())

    assert captured["as_of"] == "2026-06-17"
    assert captured["receipt"]["status"] == "OK"
    assert captured["shadow"] is False


def test_system_health_report_writes_json_and_markdown(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(rdp, "load_config", lambda: {"paths": {"archive_dir": "data/archive"}})
    monkeypatch.setattr(
        "hermes_escape_top.web.refresh.manifest_status",
        lambda _config=None: {"status": "OK"},
    )
    payload = {
        "as_of": "2026-06-17",
        "input_hash": "abc123def456",
        "cache_status": {"hit": True},
        "data_quality": {"level": "HIGH", "overall_score": 1.0},
        "data_quality_breakdown": {"sources": []},
        "external_source_status": {
            "aaii_sentiment": {
                "status": "OK",
                "latest_promoted_as_of": "2026-06-17",
                "official_issue_as_of": "2026-06-17",
                "official_file_name": "sentiment.xls",
                "official_file_sha256": "abcdefff12345678",
            }
        },
        "ibkr": {"source": "unavailable", "error": "Gateway offline"},
        "alpaca_daily_flow": {"as_of": "2026-06-17"},
        "scores": {"MSTR": {"final_score": 81}},
        "factor_scores": {"MSTR": [{"factor_id": "A1", "score": 4}]},
        "sizing": {"MSTR": {"target_weight": 0.0}},
        "decision_layers": {"MSTR": {"hard_valve_state": {"triggered": []}}},
        "action_intents": [{"symbol": "MSTR", "action": "EXIT"}],
        "risk_contributions": [{"symbol": "MSTR", "pct": 0.0}],
        "stress_scenarios": [{"name": "QQQ -5%", "est_pnl_pct": -1.2}],
    }
    receipt = {
        "status": "OK",
        "run_type": "scheduled",
        "run_at": "2026-06-17T07:10:00+08:00",
        "finished_at": "2026-06-17T07:12:00+08:00",
        "ok": True,
    }

    out = rdp._write_system_health_report(payload, "2026-06-17", receipt)

    assert out["json"] == tmp_path / "reports" / "system_health_2026-06-17.json"
    assert out["markdown"] == tmp_path / "reports" / "system_health_2026-06-17.md"
    assert out["json"].exists()
    assert out["markdown"].exists()
    data = json.loads(out["json"].read_text(encoding="utf-8"))
    assert data["health"]["layers"]["position_reconciliation"]["level"] == "INFO"
    dimensions = data["audit_dimensions"]
    assert len(dimensions) == 20
    assert {row["id"] for row in dimensions} >= {
        "strategy_data_layer",
        "position_reconciliation_layer",
        "auxiliary_flows_layer",
        "external_file_evidence",
    }
    evidence = next(row for row in dimensions if row["id"] == "external_file_evidence")
    assert evidence["status"] == "PASS"
    assert "aaii_sentiment:2026-06-17:abcdefff" in evidence["detail"]
    markdown = out["markdown"].read_text(encoding="utf-8")
    assert "策略数据" in markdown
    assert "## 20 维自检" in markdown
    assert "| external_file_evidence | PASS |" in markdown


def test_system_health_report_uses_shared_release_reports(monkeypatch, tmp_path):
    release = tmp_path / "releases" / "abc123_20260703"
    package_data = release / "hermes_escape_top"
    shared_reports = release / "reports"
    package_data.mkdir(parents=True)
    shared_reports.mkdir(parents=True)
    monkeypatch.setattr(rdp, "BASE_DIR", release)
    monkeypatch.setenv("HERMES_DATA_DIR", str(package_data))
    monkeypatch.setattr(rdp, "load_config", lambda: {"paths": {"archive_dir": "data/archive"}})
    monkeypatch.setattr(
        "hermes_escape_top.web.refresh.manifest_status",
        lambda _config=None: {"status": "OK"},
    )
    payload = {
        "as_of": "2026-07-02",
        "input_hash": "release-hash",
        "data_quality": {"level": "HIGH", "overall_score": 100},
        "data_quality_breakdown": {"sources": []},
        "external_source_status": {},
        "ibkr": {"source": "disabled"},
        "alpaca_daily_flow": {"as_of": "2026-07-02"},
        "scores": {"MSTR": {"final_score": 66.6}},
        "factor_scores": {"MSTR": []},
        "sizing": {"MSTR": {"target_weight": 0.0}},
        "decision_layers": {"MSTR": {}},
        "risk_contributions": [{"symbol": "MSTR"}],
        "stress_scenarios": [{"name": "QQQ -5%"}],
    }
    receipt = {
        "status": "OK",
        "run_type": "scheduled",
        "run_at": "2026-07-03T07:11:27+08:00",
        "finished_at": "2026-07-03T07:11:27+08:00",
        "ok": True,
    }

    out = rdp._write_system_health_report(payload, "2026-07-02", receipt)

    assert out["json"] == shared_reports / "system_health_2026-07-02.json"
    assert out["markdown"] == shared_reports / "system_health_2026-07-02.md"
    assert out["json"].exists()
    assert not (package_data / "reports" / "system_health_2026-07-02.json").exists()


def test_system_health_report_treats_scheduled_payload_as_scored_without_web_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(rdp, "load_config", lambda: {"paths": {"archive_dir": "data/archive"}})
    monkeypatch.setattr(
        "hermes_escape_top.web.refresh.manifest_status",
        lambda _config=None: {"status": "OK"},
    )
    payload = {
        "as_of": "2026-07-02",
        "input_hash": "scheduled-payload-hash",
        "data_quality": {"level": "HIGH", "overall_score": 100},
        "data_quality_breakdown": {"sources": []},
        "external_source_status": {
            "aaii_sentiment": {
                "source_id": "aaii_sentiment",
                "status": "OK",
                "official_issue_as_of": "2026-07-02",
                "official_file_sha256": "39bd37c2ffff",
            }
        },
        "ibkr": {"source": "disabled"},
        "alpaca_daily_flow": {"as_of": "2026-07-02"},
        "scores": {"MSTR": {"final_score": 66.6}},
        "factor_scores": {"MSTR": []},
        "sizing": {"MSTR": {"target_weight": 0.0}},
        "decision_layers": {"MSTR": {}},
        "risk_contributions": [{"symbol": "MSTR"}],
        "stress_scenarios": [{"name": "QQQ -5%"}],
    }
    receipt = {
        "status": "OK",
        "run_type": "scheduled",
        "run_at": "2026-07-03T07:11:27+08:00",
        "finished_at": "2026-07-03T07:11:27+08:00",
        "ok": True,
    }

    out = rdp._write_system_health_report(payload, "2026-07-02", receipt)
    data = json.loads(out["json"].read_text(encoding="utf-8"))

    assert data["health"]["level"] == "OK"
    scored = next(row for row in data["audit_dimensions"] if row["id"] == "scored_payload_cache")
    assert scored["status"] == "PASS"
    assert "scheduled_run_payload" in scored["detail"]


def test_receipt_write_failure_removes_prior_green_attestation(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    receipt_path = tmp_path / "run_receipt.json"
    receipt_path.write_text('{"status":"OK","ok":true}\n', encoding="utf-8")
    monkeypatch.setattr(
        rdp,
        "_atomic_write_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    result = rdp._write_run_receipt("2026-06-17", "scheduled", status="RUNNING")

    assert result is None
    assert not receipt_path.exists()
