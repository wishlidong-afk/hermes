from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from hermes_escape_top.web.health import compute_health
from hermes_escape_top.web.refresh import _completed_trading_days_after


DAY = date(2026, 6, 18)
NOW = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)


def _payload() -> dict:
    return {
        "as_of": DAY.isoformat(),
        "cache_status": {"hit": True},
        "data_quality": {"level": "HIGH", "overall_score": 1.0},
        "data_quality_breakdown": {"sources": []},
        "ibkr": {
            "source": "tws",
            "sync_time": (NOW - timedelta(minutes=5)).isoformat(),
            "snapshot_stale": False,
        },
        "run_receipt": {
            "status": "OK",
            "run_type": "scheduled",
            "run_at": NOW.isoformat(),
            "started_at": (NOW - timedelta(minutes=5)).isoformat(),
            "finished_at": NOW.isoformat(),
            "ok": True,
            "checks": [],
        },
        "alpaca_daily_flow": {"as_of": DAY.isoformat()},
    }


def _health(payload: dict) -> dict:
    return compute_health(
        payload,
        {"status": "OK"},
        today=DAY,
        now=NOW,
        ibkr_max_age_seconds=900,
        receipt_timeout_seconds=7200,
    )


def test_ibkr_age_is_recomputed_from_sync_time_without_degrading_strategy_health():
    payload = _payload()
    payload["ibkr"]["sync_time"] = "2026-01-01T00:00:00+00:00"
    payload["ibkr"]["snapshot_stale"] = False

    health = _health(payload)

    assert health["level"] == "OK"
    assert health["layers"]["position_reconciliation"]["level"] == "INFO"
    assert health["ibkr_age_seconds"] > 900
    check = next(check for check in health["checks"] if "IBKR 快照陈旧" in check["label"])
    assert check["level"] == "INFO"
    assert check["layer"] == "position_reconciliation"


def test_ibkr_unavailable_is_auxiliary_not_strategy_degradation():
    payload = _payload()
    payload["ibkr"] = {
        "source": "unavailable",
        "error": "Gateway offline",
    }

    health = _health(payload)

    assert health["level"] == "OK"
    assert health["layers"]["position_reconciliation"]["level"] == "INFO"
    check = next(check for check in health["checks"] if "IBKR 未连接" in check["label"])
    assert check["level"] == "INFO"
    assert check["layer"] == "position_reconciliation"
    assert "Gateway offline" in check["detail"]


def test_failed_scheduled_receipt_is_critical():
    payload = _payload()
    payload["run_receipt"].update({
        "status": "FAILED",
        "ok": False,
        "failed_step": "artifact_write",
        "error": "OSError: disk full",
    })

    health = _health(payload)

    assert health["level"] == "CRITICAL"
    assert any("官方 run 失败" in check["label"] for check in health["checks"])


def test_stuck_running_receipt_is_critical():
    payload = _payload()
    payload["run_receipt"].update({
        "status": "RUNNING",
        "ok": False,
        "started_at": (NOW - timedelta(hours=3)).isoformat(),
        "finished_at": None,
    })

    health = _health(payload)

    assert health["level"] == "CRITICAL"
    assert any("官方 run 超时" in check["label"] for check in health["checks"])


def test_stale_sip_as_of_degrades_without_failing_core_receipt():
    payload = _payload()
    payload["alpaca_daily_flow"]["as_of"] = "2026-06-15"

    health = _health(payload)

    assert health["level"] == "OK"
    assert health["layers"]["strategy_data"]["level"] == "OK"
    assert health["layers"]["auxiliary_flows"]["level"] == "DEGRADED"
    assert health["receipt_status"] == "OK"
    check = next(check for check in health["checks"] if "SIP 资金流陈旧" in check["label"])
    assert check["layer"] == "auxiliary_flows"


def test_observed_us_market_holiday_does_not_count_as_stale_trading_day():
    today = date(2026, 7, 4)
    now = datetime(2026, 7, 4, 8, 0, tzinfo=timezone.utc)
    payload = _payload()
    payload["as_of"] = "2026-07-02"
    payload["alpaca_daily_flow"]["as_of"] = "2026-07-02"
    payload["run_receipt"].update({
        "run_at": now.isoformat(),
        "started_at": (now - timedelta(minutes=2)).isoformat(),
        "finished_at": now.isoformat(),
    })

    health = compute_health(
        payload,
        {"status": "OK"},
        today=today,
        now=now,
        ibkr_max_age_seconds=900,
        receipt_timeout_seconds=7200,
    )

    assert health["level"] == "OK"
    assert health["stale_trading_days"] == 0
    assert not any("行情落后" in check["label"] for check in health["checks"])
    assert not any("SIP 资金流陈旧" in check["label"] for check in health["checks"])


def test_completed_trading_days_skip_good_friday_but_count_regular_session():
    assert _completed_trading_days_after("2026-04-02", date(2026, 4, 4)) == 0
    assert _completed_trading_days_after("2026-04-02", date(2026, 4, 7)) == 1


def test_completed_trading_days_keep_friday_open_before_saturday_new_year():
    assert _completed_trading_days_after("2027-12-29", date(2028, 1, 4)) == 3


def test_sip_refresh_error_degrades_without_failing_core_receipt():
    payload = _payload()
    payload.pop("alpaca_daily_flow")
    payload["alpaca_daily_flow_status"] = {"status": "ERROR", "error": "timeout"}

    health = _health(payload)

    assert health["level"] == "OK"
    assert health["layers"]["auxiliary_flows"]["level"] == "DEGRADED"
    assert health["receipt_status"] == "OK"
    check = next(check for check in health["checks"] if "SIP 资金流不可用" in check["label"])
    assert check["layer"] == "auxiliary_flows"


def test_external_source_failure_degrades_with_reason():
    payload = _payload()
    payload["external_source_status"] = {
        "dollar": {
            "source_id": "dollar",
            "status": "FETCH_ERROR",
            "error_message": "FRED 503",
        }
    }

    health = _health(payload)

    assert health["level"] == "DEGRADED"
    assert health["layers"]["strategy_data"]["level"] == "DEGRADED"
    assert any(
        "外部数据源刷新失败" in check["label"]
        and "dollar" in check["detail"]
        and "FRED 503" in check["detail"]
        for check in health["checks"]
    )


def test_missing_external_source_ledger_degrades_but_not_critical():
    payload = _payload()
    payload["external_source_status"] = {
        "dollar": {
            "source_id": "dollar",
            "status": "MISSING",
        }
    }

    health = _health(payload)

    assert health["level"] == "DEGRADED"
    assert any("外部数据源未自动刷新" in check["label"] for check in health["checks"])


def test_stale_external_source_profile_degrades_even_when_last_run_ok():
    payload = _payload()
    payload["external_source_status"] = {
        "dollar": {
            "source_id": "dollar",
            "status": "OK",
            "freshness_status": "STALE",
            "age_days": 14,
            "next_action": "run refresh_external --source dollar",
        }
    }

    health = _health(payload)

    assert health["level"] == "DEGRADED"
    assert any(
        "外部数据源陈旧" in check["label"]
        and "dollar" in check["detail"]
        and "run refresh_external --source dollar" in check["detail"]
        for check in health["checks"]
    )


def test_previous_receipt_expires_after_next_run_grace_window():
    # com.hermes.daily runs every calendar day at 07:10. The extra two hours
    # distinguish a missed daily job from normal weekend/holiday price staleness.
    payload = _payload()
    stale = NOW - timedelta(hours=26, seconds=1)
    payload["run_receipt"].update({"run_at": stale.isoformat(), "finished_at": stale.isoformat()})

    health = _health(payload)

    assert health["level"] == "CRITICAL"
    assert any("官方 run 已停摆" in check["label"] for check in health["checks"])
