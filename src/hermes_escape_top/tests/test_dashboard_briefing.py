"""T20: first-screen daily briefing smoke tests."""
from __future__ import annotations

from hermes_escape_top.web.render import _render_briefing


def _payload():
    return {
        "scores": {
            "MSTR": {"final_score": 72.4, "status": "EXIT", "sell_fraction": 1.0,
                     "hard_valve_hits": ["H-M1"],
                     "factor_scores": {"C": [{"factor_id": "C9", "score": 5.0,
                                              "explain": "Close below Chandelier"}]}},
            "FNGU": {"final_score": 53.4, "status": "REDUCE", "sell_fraction": 0.6,
                     "hard_valve_hits": [], "factor_scores": {}},
        },
        "today_ops": {"headline": "MSTR 清仓维持"},
        "confidence_spine": {
            "decision_confidence": 0.81, "mode": "NORMAL", "weakest_link": "stale",
            "components": {"data_conf": 0.92, "stale": 0.85, "fragility": 0.0,
                           "disagreement": 0.0},
        },
        "decision_layers": {"MSTR": {"hard_valve_state": {"pending_ids": ["H-M2"]}}},
    }


def test_briefing_answers_six_questions():
    html = _render_briefing(_payload(), {"level": "OK"})
    for marker in ("今天总体状态", "最危险资产", "为什么危险", "建议动作",
                   "置信度最弱环节", "需人工确认"):
        assert marker in html
    assert "MSTR" in html and "72.4" in html          # worst symbol picked by score
    assert "硬阀门 H-M1" in html                       # valve-first explanation
    assert "（未接线）" in html                         # fragility=0 labeled honestly
    assert "H-M2" in html and "PENDING" in html        # manual-confirmation surfaced


def test_briefing_tolerates_old_payload_without_spine():
    html = _render_briefing({"scores": {}}, {})
    assert "spine 未导出" in html
    assert "无（advisory only" in html
