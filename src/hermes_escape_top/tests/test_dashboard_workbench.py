"""T20 decision-workbench smoke tests."""
from __future__ import annotations

from hermes_escape_top.web import render as render_mod
from hermes_escape_top.web.render import _render_decision_workbench, _render_health_banner


def _field(value):
    return {"value": value}


def _payload():
    return {
        "as_of": "2026-06-04",
        "snapshots": {
            "MSTR": {"fields": {"close": _field(120), "chandelier_exit": _field(150), "ma200": _field(180), "ema20": _field(130)}},
            "FNGU": {"fields": {"close": _field(32), "chandelier_exit": _field(28), "ma200": _field(22), "ema20": _field(31)}},
            "SOXL": {"fields": {"close": _field(25), "chandelier_exit": _field(20), "ma200": _field(18), "ema20": _field(24)}},
        },
        "scores": {
            "MSTR": {
                "final_score": 75,
                "status": "EXIT",
                "hard_valve_hits": ["H-M1"],
                "valve_candidates": [
                    {
                        "id": "H-M1",
                        "desc": "close <= MA200",
                        "confirm_condition": "close back above MA200",
                        "status": "triggered",
                        "current": {"close": 120, "ma200": 180},
                        "threshold": {"close_vs": "ma200"},
                    },
                    {
                        "id": "H-M6",
                        "desc": "Chandelier stop + 18% peak drawdown",
                        "confirm_condition": "close back above the 22d 4.5xATR stop",
                        "status": "clear",
                        "current": {"close": 120, "chandelier": 150, "drawdown_60d": -0.11},
                        "threshold": {"drawdown_60d": -0.18},
                    },
                ],
                "explain": ["Hard valve triggered H-M1: MSTR close <= MA200"],
                "module_scores": {"C": 22},
                "factor_scores": {
                    "C": [
                        {"factor_id": "C9_CHANDELIER_BREAK", "score": 5, "max_score": 5, "explain": "Close below Chandelier"},
                        {"factor_id": "C5_DISTRIBUTION", "score": 3, "max_score": 5, "explain": "Distribution pressure"},
                    ]
                },
            },
            "FNGU": {
                "final_score": 44,
                "status": "REDUCE",
                "hard_valve_hits": [],
                "valve_candidates": [
                    {
                        "id": "H-F4",
                        "desc": "2-day <= -22%",
                        "confirm_condition": "2-day return back above -22%",
                        "status": "pending",
                        "current": {"return_2d": -0.23},
                        "threshold": {"return_2d": -0.22},
                    },
                    {
                        "id": "H-F6",
                        "desc": "Chandelier stop + 12% peak drawdown",
                        "confirm_condition": "close back above the 22d 4.5xATR stop",
                        "status": "clear",
                        "current": {"close": 32, "chandelier": 28, "drawdown_60d": -0.05},
                        "threshold": {"drawdown_60d": -0.12},
                    },
                ],
                "module_scores": {"C": 8},
                "factor_scores": {"A": [{"factor_id": "A5_NET_LIQUIDITY", "score": 2, "max_score": 3, "explain": "Liquidity watch"}]},
            },
            "SOXL": {
                "final_score": 18,
                "status": "HOLD",
                "hard_valve_hits": [],
                "module_scores": {"C": 3},
                "factor_scores": {"B": [{"factor_id": "B2_MA200_EXTENSION", "score": 1, "max_score": 5, "explain": "Extension mild"}]},
            },
        },
        "decision_layers": {
            "MSTR": {"hard_valve_state": {"triggered": True, "ids": ["H-M1"], "count": 1}},
            "FNGU": {"hard_valve_state": {"triggered": False, "pending_ids": ["H-F4"], "count": 0}},
            "SOXL": {"hard_valve_state": {"triggered": False, "ids": [], "count": 0}},
        },
        "reentry": {
            "MSTR": {"eligible": False, "locked_reason": "active_sell_or_hard_valve", "tranche": "LOCKED", "explain": ["Sell signal active"]},
            "FNGU": {"eligible": False, "locked_reason": "score_lock", "tranche": "LOCKED", "explain": ["Score still high"]},
            "SOXL": {"eligible": True, "locked_reason": "", "tranche": "T1", "explain": ["T1 candidate"]},
        },
        "reentry_state": {
            "states": {
                "SOXL": {"t1_active": True, "t2_active": False, "last_tranche": "T1", "updated_at": "2026-06-04T00:00:00Z"}
            }
        },
        "risk_contributions": {
            "FNGU": {"target_weight": 0.06, "standalone_vol": 0.77, "vol_contribution": 0.03, "vol_contribution_pct": 0.30},
            "SOXL": {"target_weight": 0.09, "standalone_vol": 1.29, "vol_contribution": 0.07, "vol_contribution_pct": 0.70},
            "_portfolio": {"forecast_vol": 0.10},
        },
        "stress_scenarios": [
            {"name": "QQQ -5%", "est_pnl_pct": -3.5},
            {"name": "BTC -10%", "est_pnl_pct": -0.4},
            {"name": "correlation -> 0.9", "forecast_vol_before": 0.10, "forecast_vol_after": 0.15},
            {"name": "VIX spike (vol x1.5 + corr 0.9)", "forecast_vol_before": 0.10, "forecast_vol_after": 0.23},
        ],
        "routing_context": {
            "defcon1_rule": "A>=12 AND QQQ below MA200/EMA50/EMA20 -> BOXX50/DBMF30/GLD20",
            "defcon2_rule": "A>=12 or D>=10 or hard valve or C8/C6>=3 -> BRK.B",
            "qqq": {"close": 500, "ema20": 510, "ema50": 520, "ma200": 530, "below_ema20": True, "below_ema50": True, "below_ma200": True},
            "module_a": {"MSTR": 14, "FNGU": 13, "SOXL": 12},
            "brkb_defense": {"degraded": False, "reason": "BRK.B usable", "corr_to_spy": 0.42, "threshold": 0.85},
        },
    }


def test_workbench_renders_hard_valves_reentry_and_top_factors():
    html = _render_decision_workbench(_payload())

    assert "决策工作台" in html
    assert "硬阀门全景" in html
    assert "H-M1" in html and "已触发" in html
    assert "H-F4" in html and "PENDING" in html
    assert "H-M6" in html and "H-F6" in html and "未触发" in html
    assert "当前：" in html and "阈值：" in html and "距离：" in html
    assert "close 低于 MA200 33.3%" in html
    assert "两日跌幅 已越过阈值 1.0pct" in html
    assert "Chandelier" in html
    assert "再入场三锁" in html
    assert "时间锁" in html and "分数锁" in html and "结构锁" in html
    assert "T1=True" in html
    assert "Top 5 因子贡献" in html
    assert "C9_CHANDELIER_BREAK" in html


def test_workbench_renders_p3_visual_blocks():
    html = _render_decision_workbench(_payload())

    assert "风险贡献条形图" in html
    assert "portfolio forecast vol" in html
    assert "四情景压力测试" in html
    assert "QQQ -5%" in html and "BTC -10%" in html
    assert "DEFCON 条件链" in html
    assert "A&gt;=12 AND QQQ below" in html
    assert "BRK.B usable" in html
    assert "correlation gauge" in html


def test_daily_diff_panel_reads_latest_shadow_report(tmp_path, monkeypatch):
    report_dir = tmp_path / "reports" / "shadow"
    report_dir.mkdir(parents=True)
    (report_dir / "daily_diff_2026-06-04.md").write_text(
        "# Daily diff 2026-05-29 -> 2026-06-04\n\n"
        "## MSTR\n\n"
        "- score 49.7 -> 66.2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(render_mod, "REPO_ROOT", tmp_path)

    html = render_mod._render_daily_diff_panel({"as_of": "2026-06-04"})

    assert "今日变化" in html
    assert "Daily diff 2026-05-29 -&gt; 2026-06-04" in html
    assert "score 49.7 -&gt; 66.2" in html


def test_health_banner_links_each_degraded_check_to_runbook_summary():
    html = _render_health_banner({
        "level": "DEGRADED",
        "checks": [
            {"level": "DEGRADED", "label": "IBKR 未连接", "detail": "disabled"},
            {"level": "DEGRADED", "label": "软数据源过期 1", "detail": "dollar"},
        ],
    })

    assert "#runbook-ibkr" in html
    assert "#runbook-data" in html
    assert "Runbook: IBKR 只读连接失败" in html
    assert "Runbook: 数据缺失 / 过期" in html
