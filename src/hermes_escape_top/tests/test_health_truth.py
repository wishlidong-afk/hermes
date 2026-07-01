from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from hermes_escape_top.web.health import compute_health


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


def test_ibkr_age_is_recomputed_from_sync_time():
    payload = _payload()
    payload["ibkr"]["sync_time"] = "2026-01-01T00:00:00+00:00"
    payload["ibkr"]["snapshot_stale"] = False

    health = _health(payload)

    assert health["level"] == "DEGRADED"
    assert health["ibkr_age_seconds"] > 900
    assert any("IBKR 快照陈旧" in check["label"] for check in health["checks"])


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

    assert health["level"] == "DEGRADED"
    assert health["receipt_status"] == "OK"
    assert any("SIP 资金流陈旧" in check["label"] for check in health["checks"])


def test_sip_refresh_error_degrades_without_failing_core_receipt():
    payload = _payload()
    payload.pop("alpaca_daily_flow")
    payload["alpaca_daily_flow_status"] = {"status": "ERROR", "error": "timeout"}

    health = _health(payload)

    assert health["level"] == "DEGRADED"
    assert health["receipt_status"] == "OK"
    assert any("SIP 资金流不可用" in check["label"] for check in health["checks"])


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


def test_previous_receipt_expires_after_next_run_grace_window():
    # com.hermes.daily runs every calendar day at 07:10. The extra two hours
    # distinguish a missed daily job from normal weekend/holiday price staleness.
    payload = _payload()
    stale = NOW - timedelta(hours=26, seconds=1)
    payload["run_receipt"].update({"run_at": stale.isoformat(), "finished_at": stale.isoformat()})

    health = _health(payload)

    assert health["level"] == "CRITICAL"
    assert any("官方 run 已停摆" in check["label"] for check in health["checks"])
