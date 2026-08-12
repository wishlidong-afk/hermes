from __future__ import annotations

from datetime import date, datetime, timezone

from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.decision.action_intents import build_action_context
from hermes_escape_top.web.refresh import refresh_action_context_for_display
from hermes_escape_top.web.render import _render_today_ops


def _snapshots() -> dict[str, SymbolSnapshot]:
    day = date(2026, 7, 10)
    return {
        "MSTR": SymbolSnapshot("MSTR", day, {"close": Field("close", 400.0, "unit", day)}),
        "BOXX": SymbolSnapshot("BOXX", day, {"close": Field("close", 100.0, "unit", day)}),
    }


def _payload(ibkr: dict) -> dict:
    return {
        "as_of": "2026-07-10",
        "data_quality": {"level": "HIGH", "overall_score": 97.0},
        "ibkr": ibkr,
        "scores": {
            "MSTR": {
                "status": "EXIT",
                "final_score": 80.0,
                "sell_fraction": 1.0,
                "hard_valve_hits": ["H-M1"],
                "missing_weight": 0.0,
                "factor_scores": {},
            }
        },
        "sizing": {"MSTR": {"sleeve_cap": 0.15, "target_weight": 0.0}},
        "routing": {
            "MSTR": {
                "applies": True,
                "defcon": "DEFCON1",
                "destination": "BOXX",
                "weights": {"BOXX": 1.0},
                "reason": "unit route",
            }
        },
        "reentry": {"MSTR": {}},
        "posterior_pnl": {"portfolio_value": 100_000.0},
        "snapshots": {symbol: snap.to_dict() for symbol, snap in _snapshots().items()},
    }


def test_fresh_ibkr_makes_amounts_executable_without_changing_strategy_confidence():
    payload = _payload({
        "source": "tws",
        "net_liq": 100_000.0,
        "sync_time": "2026-07-10T12:00:00+00:00",
        "snapshot_stale": False,
    })
    payload["all_source_data_quality"] = {"level": "BLOCKED", "overall_score": 42.0}

    result = build_action_context(payload, _snapshots())

    layer = result["decision_layers"]["MSTR"]
    assert layer["strategy_confidence"]["score"] == 97.0
    assert layer["strategy_confidence"]["level"] == "HIGH"
    assert layer["execution_amount_confidence"]["level"] == "HIGH"
    assert layer["execution_amount_confidence"]["authoritative"] is True
    intent = result["action_intents"]["MSTR"]
    assert intent["execution_ready"] is True
    assert intent["amount_status"] == "LIVE"
    assert intent["target_weight"] == 0.15
    assert intent["target_notional"] == 15_000.0


def test_stale_ibkr_preserves_strategy_but_marks_dollar_and_share_amounts_as_estimates():
    payload = _payload({
        "source": "snapshot",
        "net_liq": 100_000.0,
        "sync_time": "2026-07-08T12:00:00+00:00",
        "snapshot_stale": True,
    })

    result = build_action_context(payload, _snapshots())

    layer = result["decision_layers"]["MSTR"]
    assert layer["strategy_confidence"]["score"] == 97.0
    assert not any("IBKR" in reason for reason in layer["strategy_confidence"]["reasons"])
    amount = layer["execution_amount_confidence"]
    assert amount["level"] == "LOW"
    assert amount["authoritative"] is False
    intent = result["action_intents"]["MSTR"]
    assert intent["status"] == "EXIT"
    assert intent["target_weight"] == 0.15
    assert intent["target_notional"] == 15_000.0
    assert intent["amount_status"] == "STALE_ESTIMATE"
    assert intent["execution_ready"] is False
    assert result["today_ops"]["destinations_are_estimates"] is True


def test_unavailable_ibkr_blocks_execution_list_but_keeps_model_weight_and_estimate():
    result = build_action_context(
        _payload({"source": "unavailable", "error": "Gateway offline"}),
        _snapshots(),
    )

    amount = result["decision_layers"]["MSTR"]["execution_amount_confidence"]
    assert amount["level"] == "BLOCKED"
    assert amount["mode"] == "MODEL_ESTIMATE"
    intent = result["action_intents"]["MSTR"]
    assert intent["execution_ready"] is False
    assert intent["amount_status"] == "MODEL_ESTIMATE"
    assert intent["target_weight"] == 0.15
    assert intent["target_notional"] == 15_000.0


def test_display_refresh_recomputes_amount_staleness_from_sync_time():
    payload = _payload({
        "source": "tws",
        "net_liq": 100_000.0,
        "sync_time": "2026-07-10T00:00:00+00:00",
        "snapshot_stale": False,
    })
    payload.update(build_action_context(payload, _snapshots()))

    refreshed = refresh_action_context_for_display(
        payload,
        config={"ibkr": {"snapshot_max_age_seconds": 900}},
        now=datetime(2026, 7, 10, 1, 0, tzinfo=timezone.utc),
    )

    amount = refreshed["decision_layers"]["MSTR"]["execution_amount_confidence"]
    assert amount["snapshot_age_seconds"] == 3600.0
    assert amount["level"] == "LOW"
    assert refreshed["action_intents"]["MSTR"]["execution_ready"] is False


def test_workbench_does_not_present_stale_amounts_as_an_order_list():
    payload = _payload({
        "source": "snapshot",
        "net_liq": 100_000.0,
        "snapshot_stale": True,
    })
    payload.update(build_action_context(payload, _snapshots()))

    html = _render_today_ops(payload)

    assert "策略置信度" in html
    assert "金额置信度" in html
    assert "金额/股数仅为估算" in html
    assert "等待新鲜 IBKR 对账后生成差额动作" in html
    assert "实际调仓：买入" not in html
    assert "实际调仓：卖出" not in html
