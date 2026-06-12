"""Operator workbench (8765) smoke tests."""
from __future__ import annotations

from hermes_escape_top.web.workbench import render_workbench


def _payload():
    return {
        "as_of": "2026-06-11",
        "today_ops": {"headline": "FNGU 清仓"},
        "scores": {
            "FNGU": {"status": "EXIT", "final_score": 48.8, "sell_fraction": 1.0,
                     "hard_valve_hits": ["H-F5"],
                     "factor_scores": {"A": [{"factor_id": "A10_REAL_RATE", "score": 4.0,
                                              "max_score": 4.0, "explain": "extreme"}]},
                     "valve_candidates": [
                         {"id": "H-F1", "status": "clear", "desc": "QQQ <= MA200",
                          "confirm_condition": "above MA200",
                          "current": {"close": 640.0, "ma200": 620.0}, "threshold": {"close_vs": "ma200"}},
                         {"id": "H-F5", "status": "triggered", "desc": "3d below EMA50",
                          "confirm_condition": "close above EMA50", "current": None, "threshold": None},
                     ]},
        },
        "routing": {"FNGU": {"destination": "QQQ", "weights": {"QQQ": 1.0}}},
        "confidence_spine": {"decision_confidence": 0.79, "mode": "CAUTION",
                             "weakest_link": "fragility", "components": {"fragility": 0.7}},
        "decision_layers": {"FNGU": {"hard_valve_state": {"pending_ids": [],
                            "candidates": []}}},
        "routing_context": {"qqq": {"close": 740, "ma200": 620, "ema50": 682, "ema20": 719,
                                    "below_ma200": False, "below_ema50": False, "below_ema20": False},
                            "brkb_defense": {"reason": "BRK.B close <= MA200", "corr_to_spy": 0.23,
                                             "threshold": 0.85}},
        "regime": {"current": "HIGH_VOL"},
        "stress_scenarios": [{"name": "QQQ -5%", "est_pnl_pct": -1.7}],
        "flow": {
            "symbols": {"FNGU": {"cmf20": 0.10, "mfi14": 51, "outflow_days_5d": 0, "severity": "NORMAL"}},
            "component_baskets": {"FNGU": {
                "abnormal_components": 1,
                "components": [
                    {"symbol": "NVDA", "cmf20": -0.17, "mfi14": 33.5, "ad_slope20": -4e7,
                     "outflow_days_5d": 5, "legacy_signed_5d": -5.4e10, "severity": "ABNORMAL"},
                    {"symbol": "MSFT", "cmf20": 0.07, "mfi14": 58, "ad_slope20": 1e6,
                     "outflow_days_5d": 0, "legacy_signed_5d": 2.1e9, "severity": "NORMAL"},
                ]}},
        },
    }


def test_four_zones_render():
    html = render_workbench(_payload())
    for marker in ("区域 1", "区域 2", "区域 3", "区域 4"):
        assert marker in html


def test_lookthrough_sorts_worst_first_and_flags_divergence():
    html = render_workbench(_payload())
    assert html.index("NVDA") < html.index("MSFT")        # ABNORMAL first
    assert "背离" in html and "-54.0B" in html             # signed 5d billions
    assert "H-F5" in html and "触发" in html               # triggered valve dot


def test_tolerates_empty_payload():
    html = render_workbench({})
    assert "区域 4" in html and "flow 数据缺失" in html


def test_trust_zone_renders_and_orders_by_urgency():
    from hermes_escape_top.web.workbench import _zone_trust
    html = _zone_trust([
        {"name": "aaii_sentiment", "cadence": "weekly", "last_date": "2026-06-11",
         "days_left": 9, "is_proxy": False, "source": "AAII_PUBLIC_HTML"},
        {"name": "cboe_equity_pcr", "cadence": "daily", "last_date": "2026-05-29",
         "days_left": -8, "is_proxy": True, "source": "vix_derived_proxy"},
    ])
    assert "数据信任区" in html
    assert html.index("cboe_equity_pcr") < html.index("aaii_sentiment")  # urgent first
    assert "超期 8d" in html and "代理" in html and "真实" in html
    assert _zone_trust(None) == ""  # offline render omits the zone
