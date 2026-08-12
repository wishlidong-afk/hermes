"""T20 decision-workbench smoke tests."""
from __future__ import annotations

import json
import os

from hermes_escape_top.web import render as render_mod
from hermes_escape_top.web import server as server_mod
from hermes_escape_top.web.render import _render_decision_workbench, _render_health_banner, _render_strategy_console


def _field(value):
    return {"value": value}


def test_health_report_copy_marks_post_deploy_pending_without_claiming_failure():
    text = render_mod._health_report_evidence_text(
        {"system_health_report": {"input_hash": "same"}, "input_hash": "same"},
        {"post_deploy_certification": {"status": "PENDING_POST_DEPLOY"}},
    )

    assert "待当前版本自然日跑再认证" in text


def test_trust_header_does_not_authorize_actions_while_post_deploy_is_pending():
    payload = _payload()
    payload.update(
        {
            "data_quality": {"level": "HIGH", "overall_score": 100},
            "run_receipt": {"status": "OK", "ok": True},
            "system_health_report": {"input_hash": "same"},
            "input_hash": "same",
        }
    )
    health = {
        "level": "OK",
        "layers": {
            "strategy_data": {"level": "OK", "checks": []},
            "position_reconciliation": {"level": "OK", "checks": []},
            "auxiliary_flows": {"level": "OK", "checks": []},
        },
        "post_deploy_certification": {"status": "PENDING_POST_DEPLOY"},
        "checks": [],
    }

    html = render_mod._render_trust_section(
        payload,
        {"status": "OK"},
        health,
    )

    assert "策略待认证" in html
    assert "今日操作：WAIT" in html
    assert "策略可用" not in html


def test_strategy_failure_takes_precedence_over_post_deploy_pending_copy():
    payload = _payload()
    payload["data_quality"] = {"level": "HIGH", "overall_score": 100}
    health = {
        "level": "CRITICAL",
        "layers": {
            "strategy_data": {
                "level": "CRITICAL",
                "checks": [
                    {
                        "level": "CRITICAL",
                        "label": "行情陈旧",
                        "detail": "stale=3",
                        "layer": "strategy_data",
                    }
                ],
            },
            "position_reconciliation": {"level": "OK", "checks": []},
            "auxiliary_flows": {"level": "OK", "checks": []},
        },
        "post_deploy_certification": {"status": "PENDING_POST_DEPLOY"},
        "checks": [],
    }

    html = render_mod._render_trust_section(payload, {"status": "OK"}, health)

    assert "策略不可用" in html
    assert "今日操作：STOP" in html
    assert "新版本运行正常" not in html


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
        "sizing": {
            "MSTR": {"target_weight": 0.0},
            "FNGU": {"target_weight": 0.0},
            "SOXL": {"target_weight": 0.095},
        },
        "routing": {
            "MSTR": {"applies": True, "defcon": "DEFCON1", "weights": {"BOXX": 0.5, "DBMF": 0.3, "GLD": 0.2}},
        },
        "action_intents": {
            "MSTR": {
                "action": "SELL_AND_ROUTE",
                "target_symbol": "BOXX",
                "target_notional": 1000,
                "target_weight": 0.0,
                "top_reasons": ["Hard valves: H-M1"],
                "trade_plan": {"legs": [
                    {"role": "risk", "symbol": "MSTR", "target_weight": 0.0, "target_notional": 0.0, "target_shares": 0, "reference_price": 120},
                    {"role": "defense_route", "symbol": "BOXX", "target_weight": 0.1, "target_notional": 1000, "target_shares": 8.5, "reference_price": 117},
                ]},
            },
            "FNGU": {
                "action": "SELL_AND_ROUTE",
                "target_symbol": "BOXX",
                "target_notional": 1000,
                "target_weight": 0.0,
                "top_reasons": ["FNGU component flow severe"],
                "trade_plan": {"legs": [
                    {"role": "risk", "symbol": "FNGU", "target_weight": 0.0, "target_notional": 0.0, "target_shares": 0, "reference_price": 32},
                    {"role": "defense_route", "symbol": "BOXX", "target_weight": 0.1, "target_notional": 1000, "target_shares": 8.5, "reference_price": 117},
                ]},
            },
            "SOXL": {
                "action": "HOLD_OR_MAINTAIN",
                "target_weight": 0.095,
                "top_reasons": ["SOXL component flow abnormal"],
            },
        },
        "today_ops": {
            "headline": "需要处置",
            "action_count": 3,
            "data_quality": "HIGH",
            "data_quality_score": 93.5,
            "ibkr_source": "tws",
        },
        "data_quality": {
            "level": "HIGH",
            "overall_score": 93.5,
            "completeness_score": 96,
            "quality_score": 94,
            "latency_score": 91,
            "penalties": [],
        },
        "all_source_data_quality": {
            "level": "HIGH",
            "overall_score": 92.0,
            "completeness_score": 96,
            "quality_score": 89,
            "latency_score": 91,
            "penalties": [],
        },
        "data_quality_breakdown": {
            "components": {
                "price_fresh": True,
                "soft_proxy_count": 0,
                "ibkr_source": "tws",
                "ibkr_stale": False,
            },
            "sources": [
                {"category": "soft", "name": "cboe_pcr", "status": "AVAILABLE", "as_of": "2026-06-03", "is_proxy": False, "latency_days": 1, "source": "CBOE_DAILY_HTML"},
                {"category": "soft", "name": "aaii", "status": "AVAILABLE", "as_of": "2026-05-30", "is_proxy": False, "latency_days": 5, "source": "AAII"},
            ],
        },
        "soft_data": {
            "records": {
                "cboe_pcr": {"as_of": "2026-06-03", "data_available": True, "is_proxy": False, "latency_days": 1, "source": "CBOE_DAILY_HTML"},
                "aaii": {"as_of": "2026-05-30", "data_available": True, "is_proxy": False, "latency_days": 5, "source": "AAII"},
            }
        },
        "ibkr": {
            "source": "tws",
            "net_liq": 100000,
            "trade_symbols": [
                {"symbol": "MSTR", "ideal_weight": 0.0, "actual_weight": 0.0, "actual_notional": 0.0, "actual_shares": 0, "status": "MATCH"},
                {"symbol": "FNGU", "ideal_weight": 0.0, "actual_weight": 0.0, "actual_notional": 0.0, "actual_shares": 0, "status": "MATCH"},
                {"symbol": "SOXL", "ideal_weight": 0.095, "actual_weight": 0.0, "actual_notional": 0.0, "actual_shares": 0, "status": "MISSING"},
            ],
            "route_legs": [
                {"symbol": "BOXX", "ideal_weight": 0.277, "actual_weight": 0.0, "actual_notional": 0.0, "actual_shares": 0, "status": "MISSING"},
                {"symbol": "DBMF", "ideal_weight": 0.166, "actual_weight": 0.0, "actual_notional": 0.0, "actual_shares": 0, "status": "MISSING"},
                {"symbol": "GLD", "ideal_weight": 0.111, "actual_weight": 0.0, "actual_notional": 0.0, "actual_shares": 0, "status": "MISSING"},
            ],
            "extra_positions": [
                {"symbol": "BRK.B", "ideal_weight": 0.0, "actual_weight": 0.127, "actual_notional": 12700, "actual_shares": 23, "status": "EXTRA"},
            ],
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
        "flow": {
            "as_of": "2026-06-04",
            "db_path": "/tmp/flow_reference.sqlite",
            "symbols": {
                "MSTR": {"symbol": "MSTR", "severity": "WATCH", "cmf20": -0.08, "mfi14": 25.07, "legacy_signed_5d": -4_790_000_000, "outflow_days_5d": 5},
            },
            "component_baskets": {
                "FNGU": {
                    "severity": "SEVERE",
                    "avg_cmf20": -0.12,
                    "avg_mfi14": 37,
                    "abnormal_components": 3,
                    "component_count": 4,
                    "components": [
                        {"symbol": "NFLX", "severity": "SEVERE", "cmf20": -0.24, "mfi14": 29.03, "legacy_signed_5d": 3_740_000_000, "outflow_days_5d": 5},
                        {"symbol": "NVDA", "severity": "ABNORMAL", "cmf20": -0.17, "mfi14": 33.53, "legacy_signed_5d": -53_930_000_000, "outflow_days_5d": 5},
                        {"symbol": "AMZN", "severity": "ABNORMAL", "cmf20": -0.11, "mfi14": 24.97, "legacy_signed_5d": -32_060_000_000, "outflow_days_5d": 5},
                    ],
                },
                "SOXL": {
                    "severity": "ABNORMAL",
                    "avg_cmf20": -0.04,
                    "avg_mfi14": 55,
                    "abnormal_components": 1,
                    "component_count": 3,
                    "components": [
                        {"symbol": "NVDA", "severity": "ABNORMAL", "cmf20": -0.17, "mfi14": 33.53, "legacy_signed_5d": -53_930_000_000, "outflow_days_5d": 5},
                        {"symbol": "AMD", "severity": "NORMAL", "cmf20": 0.20, "mfi14": 61.59, "legacy_signed_5d": -25_240_000_000, "outflow_days_5d": 0},
                    ],
                },
            },
        },
        "alpaca_daily_flow": {
            "schema_version": "alpaca-sip-daily-flow-v1",
            "as_of": "2026-06-17",
            "source": "ALPACA_SIP_1MIN",
            "baskets": {
                "MSTR": {
                    "direction": "NET_BUY", "buy_notional": 1_200_000_000,
                    "sell_notional": 800_000_000, "net_notional": 400_000_000,
                    "total_notional": 2_000_000_000, "component_count": 1,
                    "requested_component_count": 1,
                    "components": [{"symbol": "MSTR", "buy_notional": 1_200_000_000,
                                    "sell_notional": 800_000_000, "net_notional": 400_000_000,
                                    "buy_share": 0.6, "trade_count": 12345}],
                },
                "FNGU": {
                    "direction": "NET_SELL", "buy_notional": 3_000_000_000,
                    "sell_notional": 3_500_000_000, "net_notional": -500_000_000,
                    "total_notional": 6_500_000_000, "component_count": 1,
                    "requested_component_count": 1,
                    "components": [{"symbol": "NVDA", "buy_notional": 3_000_000_000,
                                    "sell_notional": 3_500_000_000, "net_notional": -500_000_000,
                                    "buy_share": 3 / 6.5, "trade_count": 54321}],
                },
                "SOXL": {
                    "direction": "BALANCED", "buy_notional": 900_000_000,
                    "sell_notional": 900_000_000, "net_notional": 0,
                    "total_notional": 1_800_000_000, "component_count": 1,
                    "requested_component_count": 1,
                    "components": [{"symbol": "AMD", "buy_notional": 900_000_000,
                                    "sell_notional": 900_000_000, "net_notional": 0,
                                    "buy_share": 0.5, "trade_count": 22222}],
                },
            },
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

    assert "风险与路由解释" in html
    assert "风险贡献条形图" in html
    assert "portfolio forecast vol" in html
    assert "四情景压力测试" in html
    assert "QQQ -5%" in html and "BTC -10%" in html
    assert "DEFCON 条件链" in html
    assert "A&gt;=12 AND QQQ below" in html
    assert "BRK.B usable" in html
    assert "correlation gauge" in html


def test_strategy_console_prioritizes_strategy_positions_and_underlying_flow():
    html = render_mod.render_dashboard(_payload(), health={"level": "OK"}, manifest_status={"status": "OK"})

    assert "今日可信度与系统状态" in html
    assert "Trust &amp; System Health" in html
    assert "trust-status-lanes" in html
    assert "策略数据链" in html and "外部数据链" in html and "持仓对账" in html and "辅助资金流" in html
    assert html.count("health-pill") >= 3
    assert "刷新全部外部源" in html
    assert "IBKR Live 验收" not in html
    assert "ibkr-live-btn" not in html
    assert "runIbkrLiveCheck" not in html
    # 8765 workbench retired — its launch button must NOT be on the dashboard.
    assert "工作台 8765" not in html
    assert "127.0.0.1:8765" not in html
    assert "M4 迁移控制台" not in html
    assert "运行影子对比" not in html
    assert "补基准并对比" not in html
    assert "区域 5 · 数据信任区" in html
    assert "<details class='work-card data-trust-zone'" in html
    assert "cboe_equity_pcr" in html and "CBOE_DAILY_HTML" in html and "剩 5d" in html
    assert "aaii_sentiment" in html and "AAII" in html and "真实" in html
    assert html.index("今日可信度与系统状态") < html.index("区域 5 · 数据信任区") < html.index("今日操作台")
    assert "页面底部系统运维详情" in html
    for label in ("外部源预检", "20 维系统自检", "最近 7 次系统健康", "Audit Detail"):
        assert html.index("穿透股票成交与流向参考") < html.index(label)
    assert html.count("需要处置") == 1
    assert "今日操作台" in html
    assert "DEFCON 路由" in html and "执行计划资金去向" in html
    assert "路由/执行口径不一致" in html and "DBMF" in html and "GLD" in html
    assert html.index("今日可信度与系统状态") < html.index("今日操作台")
    assert html.index("今日操作台") < html.index("为什么这么做")
    assert html.index("为什么这么做") < html.index("硬阀门雷达")
    assert html.index("硬阀门雷达") < html.index("全量打分因子表") < html.index("展开点阵矩阵")
    assert html.index("硬阀门雷达") < html.index("当前持仓 + IBKR 对账")
    assert "MSTR EXIT" in html and "FNGU REDUCE" in html and "SOXL HOLD" in html
    assert "当前持仓 + IBKR 对账" in html
    assert "IBKR 现有总资产" in html
    assert "理想仓位上一交易日盈亏" in html
    assert "穿透股票成交与流向参考" in html
    assert html.index("当前持仓 + IBKR 对账") < html.index("穿透股票成交与流向参考")
    assert "Mirror Reference" not in html
    assert "SOXL" in html and "买入缺口" in html
    assert "BOXX" in html and "+27.7%" in html
    assert "FNGU 量价流向代理" in html and "SEVERE" in html
    assert "NVDA" in html and "-$53.93B" in html
    assert "量价流向热力" in html
    assert "CMF20热格" in html and "MFI-50热格" in html
    assert "上一交易日成交额拆分估算" in html and "ALPACA_SIP_1MIN · 2026-06-17" in html
    assert "只能确认真实总成交额" in html and "不是交易所 aggressor side" in html
    assert "估算买入侧占优" in html and "估算卖出侧占优" in html
    assert "+$400.00M" in html and "-$500.00M" in html
    assert "总成交额 $2.00B" in html and "买入侧估算</th>" in html
    assert "不是真实资金净流" in html
    assert "主动买入占优" not in html
    assert "+$1.20B" not in html
    assert "其他折叠详情" in html and "硬阀门全景" in html


def test_trust_health_section_explains_degraded_without_old_loud_banner():
    payload = _payload()
    payload["run_receipt"] = {
        "status": "OK",
        "ok": True,
        "run_at": "2026-07-04T07:11:29+08:00",
        "as_of": "2026-07-02",
    }
    payload["state"] = {"score_run_id": 136}
    payload["input_hash"] = "d9350b42d00bec781"
    payload["system_health_report"] = {
        "as_of": "2026-07-02",
        "input_hash": "d9350b42d00bec781",
        "health": {"level": "DEGRADED"},
    }
    health = {
        "level": "DEGRADED",
        "stale_trading_days": 1,
        "layers": {
            "strategy_data": {
                "level": "DEGRADED",
                "checks": [{"level": "DEGRADED", "label": "行情落后 1 个交易日", "detail": "as_of=2026-07-02"}],
            },
            "position_reconciliation": {
                "level": "INFO",
                "checks": [{"level": "INFO", "label": "IBKR 快照陈旧", "detail": "age=20h"}],
            },
            "auxiliary_flows": {"level": "OK", "checks": []},
        },
        "checks": [
            {"level": "DEGRADED", "label": "行情落后 1 个交易日", "detail": "as_of=2026-07-02", "layer": "strategy_data"},
            {"level": "INFO", "label": "IBKR 快照陈旧", "detail": "age=20h", "layer": "position_reconciliation"},
        ],
    }

    html = render_mod.render_dashboard(payload, health=health, manifest_status={"status": "OK"})

    assert "今日可信度与系统状态" in html
    assert "策略可用" in html
    assert "今日操作：REVIEW ONLY" in html
    assert "策略链路正常；当前黄灯来自可解释的外部/日历/对账因素" in html
    assert "HOLIDAY-LAG" in html
    assert "IBKR 快照陈旧" in html
    assert "阻断策略？否" in html
    assert "阻断下单？需复核" in html
    assert "Health 报告" in html and "hash 匹配" in html
    assert "运行降级 / DEGRADED" not in html


def test_trust_health_defaults_to_compact_summary_with_diagnostics_folded():
    payload = _payload()
    health = {
        "level": "CRITICAL",
        "layers": {
            "strategy_data": {
                "level": "CRITICAL",
                "checks": [
                    {
                        "level": "CRITICAL",
                        "label": "官方评分已有更新行情待重跑",
                        "detail": "as_of=2026-07-13 latest=2026-07-14",
                    }
                ],
            },
            "position_reconciliation": {
                "level": "INFO",
                "checks": [{"level": "INFO", "label": "IBKR 快照陈旧", "detail": "age=20h"}],
            },
            "auxiliary_flows": {
                "level": "DEGRADED",
                "checks": [{"level": "DEGRADED", "label": "SIP 资金流陈旧", "detail": "stale=1d"}],
            },
        },
        "checks": [
            {
                "level": "CRITICAL",
                "label": "官方评分已有更新行情待重跑",
                "detail": "as_of=2026-07-13 latest=2026-07-14",
                "layer": "strategy_data",
            }
        ],
    }

    html = render_mod.render_dashboard(payload, health=health, manifest_status={"status": "OK"})
    trust_section = html[html.index("今日可信度与系统状态"):html.index("今日操作台")]

    assert "trust-compact-head" in trust_section
    assert "trust-status-lanes" in trust_section
    for label in ("策略数据链", "外部数据链", "持仓对账", "辅助资金流"):
        assert label in trust_section
    assert "当前阻断" in trust_section
    assert trust_section.index("当前阻断") < trust_section.index("<details class=\"trust-diagnostics\"")
    assert "<details class=\"trust-diagnostics\" open" not in trust_section
    assert "展开诊断、质量与运行证据" in trust_section
    assert trust_section.index("展开诊断、质量与运行证据") < trust_section.index("行情完整度")
    assert trust_section.index("行情完整度") < trust_section.index("策略输入质量扣分账本")
    assert trust_section.index("策略输入质量扣分账本") < trust_section.index("区域 5 · 数据信任区")


def test_trust_health_strategy_usability_comes_from_strategy_layer():
    payload = _payload()
    health = {
        "level": "CRITICAL",
        "layers": {
            "strategy_data": {"level": "OK", "checks": []},
            "position_reconciliation": {
                "level": "CRITICAL",
                "checks": [{"level": "CRITICAL", "label": "IBKR 对账不可用", "detail": "snapshot missing"}],
            },
            "auxiliary_flows": {"level": "OK", "checks": []},
        },
        "checks": [],
    }

    html = render_mod.render_dashboard(payload, health=health, manifest_status={"status": "OK"})
    trust_section = html[html.index("今日可信度与系统状态"):html.index("今日操作台")]

    assert "策略可用" in trust_section
    assert "今日操作：REVIEW ONLY" in trust_section
    assert "今日操作：STOP" not in trust_section


def test_trust_health_primary_blocker_comes_from_strategy_layer():
    payload = _payload()
    health = {
        "level": "CRITICAL",
        "layers": {
            "strategy_data": {
                "level": "CRITICAL",
                "checks": [
                    {
                        "level": "DEGRADED",
                        "label": "官方行情证据不完整",
                        "detail": "certified market witness missing",
                    }
                ],
            },
            "position_reconciliation": {
                "level": "CRITICAL",
                "checks": [
                    {
                        "level": "CRITICAL",
                        "label": "IBKR 对账不可用",
                        "detail": "snapshot missing",
                    }
                ],
            },
        },
        "checks": [],
    }

    html = render_mod.render_dashboard(payload, health=health, manifest_status={"status": "OK"})
    trust_section = html[html.index("今日可信度与系统状态"):html.index("今日操作台")]
    compact_section = trust_section[:trust_section.index('<details class="trust-diagnostics"')]
    primary_issue = compact_section[compact_section.index("trust-primary-issue"):]

    assert "当前阻断" in primary_issue
    assert "官方行情证据不完整" in primary_issue
    assert "IBKR 对账不可用" not in primary_issue


def test_trust_health_section_summarizes_data_quality_penalties():
    payload = _payload()
    payload["data_quality"] = {
        "level": "HIGH",
        "overall_score": 97.0,
        "completeness_score": 100.0,
        "quality_score": 92.0,
        "latency_score": 97.0,
        "penalties": [
            {
                "field": "SOFT.component_breadth,SOFT.fngu_pct_above_50dma,SOFT.soxl_pct_above_50dma",
                "penalty": 2.0,
                "reason": "proxy",
            },
            {
                "field": "SOFT.btc_funding_basis,SOFT.btc_basis_pctl",
                "penalty": 2.0,
                "reason": "proxy",
            },
            {
                "field": "SOFT.cboe_pcr,SOFT.equity_pcr",
                "penalty": 3.0,
                "reason": "latency",
            },
        ],
    }

    html = render_mod.render_dashboard(payload, health={"level": "OK"}, manifest_status={"status": "OK"})

    trust_section = html[html.index("今日可信度与系统状态"):html.index("区域 5 · 数据信任区")]
    assert "策略输入质量扣分账本" in trust_section
    assert "proxy × 2" in trust_section
    assert "latency × 1" in trust_section
    assert "component_breadth" in trust_section
    assert "btc_funding_basis" in trust_section
    assert "cboe_pcr" in trust_section
    assert "影响策略置信度；是否阻断由策略数据链综合判定" in trust_section


def test_dashboard_separates_strategy_input_quality_from_all_source_quality():
    payload = _payload()
    payload["data_quality"] = {
        "level": "HIGH",
        "overall_score": 97.0,
        "completeness_score": 100.0,
        "quality_score": 96.0,
        "latency_score": 97.0,
        "penalties": [],
    }
    payload["all_source_data_quality"] = {
        "level": "LOW",
        "overall_score": 61.0,
        "completeness_score": 100.0,
        "quality_score": 40.0,
        "latency_score": 45.0,
        "penalties": [
            {
                "field": "SOFT.btc_funding_basis,SOFT.btc_basis_pctl",
                "penalty": 20.0,
                "reason": "proxy",
            }
        ],
    }

    html = render_mod.render_dashboard(
        payload,
        health={"level": "OK", "layers": {"strategy_data": {"level": "OK"}}},
        manifest_status={"status": "OK"},
    )

    trust_section = html[html.index("今日可信度与系统状态"):html.index("今日操作台")]
    system_ops = html[html.index("页面底部系统运维详情"):]
    assert "策略输入质量" in trust_section
    assert "HIGH 97.00" in trust_section
    assert "策略不可用" not in trust_section
    assert "全源观测质量" in system_ops
    assert "LOW 61.00" in system_ops
    assert "btc_funding_basis" in system_ops


def test_trust_health_external_chain_prefers_current_daily_ledger_over_stale_precheck():
    payload = _payload()
    payload["external_source_status"] = {
        source: {
            "source_id": source,
            "status": "OK",
            "latest_promoted_as_of": "2026-07-02",
            "freshness_status": "OK",
        }
        for source in ("dollar", "real_rate", "fred_net_liquidity", "naaim_exposure", "aaii_sentiment")
    }
    payload["external_precheck_status"] = {
        "ready": False,
        "blocking_sources": ["fred_net_liquidity"],
        "warning_sources": ["dollar"],
        "refresh": {"ok": False, "ok_count": 4, "error_count": 1},
        "sources": {
            "fred_net_liquidity": {
                "status": "FETCH_ERROR",
                "latest_promoted_as_of": None,
                "error_message": "404 Client Error",
            }
        },
    }

    html = render_mod.render_dashboard(payload, health={"level": "OK"}, manifest_status={"status": "OK"})

    trust_section = html[html.index("今日可信度与系统状态"):html.index("区域 5 · 数据信任区")]
    assert "OK 5 / ERR 0 / MISS 0" in trust_section
    assert "BLOCK · ok=4 err=1" not in trust_section
    assert "DUE_SOON" not in trust_section


def test_external_source_ops_shows_latest_failed_attempt_over_cached_ok_status():
    payload = _payload()
    payload["external_source_status"] = {
        "cboe_vix": {
            "source_id": "cboe_vix",
            "status": "OK",
            "latest_promoted_as_of": "2026-07-10",
            "finished_at": "2026-07-13T06:45:00+08:00",
            "latest_attempt_status": "VALIDATION_ERROR",
            "latest_attempt_finished_at": "2026-07-14T06:45:00+08:00",
            "latest_attempt_error_message": "Yahoo witness mismatch 2026-07-13",
            "freshness_status": "OK",
            "evidence_status": "MATCH",
        }
    }

    html = render_mod.render_dashboard(
        payload,
        health={"level": "DEGRADED"},
        manifest_status={"status": "OK"},
    )

    assert "VALIDATION_ERROR" in html
    assert "Yahoo witness mismatch 2026-07-13" in html
    assert "2026-07-14T06:45:00+08:00" in html
    assert "CBOE VIX" in html


def test_external_chain_counts_failed_retry_with_current_certified_cache_as_warn():
    payload = {
        "external_source_status": {
            "naaim_exposure": {
                "status": "OK",
                "freshness_status": "OK",
                "evidence_status": "MATCH",
                "latest_attempt_status": "FETCH_ERROR",
            }
        }
    }

    text, kind = render_mod._external_precheck_metric(payload)

    assert text == "OK 1 / ERR 0 / MISS 0 · RETRY 1"
    assert kind == "warn"


def test_external_chain_keeps_failed_retry_red_when_certified_cache_is_stale():
    payload = {
        "external_source_status": {
            "naaim_exposure": {
                "status": "OK",
                "freshness_status": "STALE",
                "evidence_status": "MATCH",
                "latest_attempt_status": "FETCH_ERROR",
            }
        }
    }

    text, kind = render_mod._external_precheck_metric(payload)

    assert text == "OK 0 / ERR 1 / MISS 0"
    assert kind == "danger"


def test_external_source_ops_discloses_fred_api_non_endorsement():
    payload = _payload()
    payload["external_source_status"] = {
        "fred_vintages": {
            "source_id": "fred_vintages",
            "status": "OK",
            "latest_promoted_as_of": "2026-07-13",
        }
    }

    html = render_mod.render_dashboard(
        payload,
        health={"level": "OK"},
        manifest_status={"status": "OK"},
    )

    assert "FRED/ALFRED Vintage Events" in html
    assert "uses the FRED® API" in html
    assert "not endorsed or certified by the Federal Reserve Bank of St. Louis" in html


def test_external_source_ops_labels_exact_fred_derivatives():
    payload = _payload()
    payload["external_source_status"] = {
        "dollar_vintage": {"source_id": "dollar_vintage", "status": "OK"},
        "real_rate_vintage": {"source_id": "real_rate_vintage", "status": "OK"},
        "fred_net_liquidity_vintage": {
            "source_id": "fred_net_liquidity_vintage",
            "status": "OK",
        },
    }

    html = render_mod.render_dashboard(
        payload,
        health={"level": "OK"},
        manifest_status={"status": "OK"},
    )

    assert "DXY / Dollar · exact vintage" in html
    assert "10Y Real Rate · exact vintage" in html
    assert "FRED Net Liquidity · exact vintage" in html


def test_external_precheck_table_uses_latest_attempt_time_and_error():
    payload = {
        "external_source_status": {
            "cboe_vix": {
                "source_id": "cboe_vix",
                "status": "OK",
                "latest_attempt_status": "VALIDATION_ERROR",
                "evidence_status": "MATCH",
            }
        },
        "external_precheck_status": {
            "ready": False,
            "refresh": {"ok_count": 0, "error_count": 1},
            "sources": {
                "cboe_vix": {
                    "source_id": "cboe_vix",
                    "status": "OK",
                    "latest_promoted_as_of": "2026-07-10",
                    "finished_at": "2026-07-13T06:45:00+08:00",
                    "latest_attempt_status": "VALIDATION_ERROR",
                    "latest_attempt_finished_at": "2026-07-14T06:45:00+08:00",
                    "latest_attempt_error_message": "Yahoo witness mismatch latest close",
                    "evidence_status": "MATCH",
                }
            },
        },
    }

    html = render_mod._render_external_precheck_summary(payload)

    assert "VALIDATION_ERROR" in html
    assert "2026-07-14T06:45:00+08:00" in html
    assert "Yahoo witness mismatch latest close" in html
    assert "2026-07-13T06:45:00+08:00" not in html


def test_trust_health_does_not_certify_runner_ok_when_canonical_evidence_drifted():
    payload = _payload()
    payload["external_source_status"] = {
        source: {
            "source_id": source,
            "status": "OK",
            "latest_promoted_as_of": "2026-07-02",
            "freshness_status": "OK",
            "evidence_status": "EVIDENCE_DRIFT" if source == "dollar" else "MATCH",
            "evidence_detail": "canonical sha256 changed" if source == "dollar" else "canonical matches",
        }
        for source in ("dollar", "real_rate", "fred_net_liquidity", "naaim_exposure", "aaii_sentiment")
    }
    payload["external_precheck_status"] = {
        "ready": False,
        "blocking_sources": ["dollar"],
        "warning_sources": [],
        "refresh": {"ok": True, "ok_count": 5, "error_count": 0},
        "sources": {},
    }

    html = render_mod.render_dashboard(payload, health={"level": "OK"}, manifest_status={"status": "OK"})

    trust_section = html[html.index("今日可信度与系统状态"):html.index("区域 5 · 数据信任区")]
    assert "OK 4 / ERR 1 / MISS 0 · EVIDENCE 1" in trust_section
    assert "正式 daily ledger OK" not in trust_section
    assert "EVIDENCE_DRIFT" in html
    assert 'badge danger">EVIDENCE_DRIFT' in html


def test_factor_map_lists_all_scoring_inputs_grouped_by_module():
    html = render_mod._render_hard_valve_radar(_payload())

    assert "全量打分因子表" in html
    assert "Factor Map" in html
    assert "A 宏观/市场温度" in html
    assert "B 标的过热/估值" in html
    assert "C 结构破坏/技术确认" in html
    assert "D 个股/资产自身风险" in html
    assert "A5_NET_LIQUIDITY" in html
    assert "B2_MA200_EXTENSION" in html
    assert "C9_CHANDELIER_BREAK" in html
    assert "D1_ASSET_MA200_BREAK" in html
    assert "看什么" in html and "何时加分" in html


def test_factor_map_separates_placeholders_from_retired_and_scored_missing_inputs():
    payload = _payload()
    payload["scores"]["MSTR"]["factor_scores"].update(
        {
            "A": [
                {
                    "factor_id": "A2_CNN_FEAR_GREED",
                    "module": "A",
                    "score": 0,
                    "max_score": 0,
                    "missing_fields": ["A2 cnn_fear_greed"],
                },
                {
                    "factor_id": "A2_NAAIM",
                    "module": "A",
                    "score": 0,
                    "max_score": 2,
                    "missing_fields": [],
                },
            ],
            "B": [
                {
                    "factor_id": "B5_SOCIAL_EUPHORIA",
                    "module": "B",
                    "score": 0,
                    "max_score": 0,
                    "missing_fields": ["B5 social"],
                },
                {
                    "factor_id": "B6_VALUATION_HEAT",
                    "module": "B",
                    "score": 0,
                    "max_score": 5,
                    "missing_fields": ["B6 valuation"],
                },
            ],
            "D": [
                {
                    "factor_id": "D_M4_BALANCE_SHEET_PROXY",
                    "module": "D",
                    "score": 0,
                    "max_score": 0,
                    "missing_fields": ["D-M4"],
                },
                {
                    "factor_id": "D_M5_CRYPTO_SENTIMENT",
                    "module": "D",
                    "score": 0,
                    "max_score": 0,
                    "missing_fields": ["D-M5"],
                },
            ],
        }
    )
    payload["external_source_status"] = {
        "naaim_exposure": {
            "source_id": "naaim_exposure",
            "lifecycle_status": "RETIRED_PAYWALL",
            "freshness_status": "OK",
            "evidence_status": "MATCH",
        }
    }

    html = render_mod._render_factor_map_panel(payload)
    placeholder_start = html.index("<summary>非计分占位")
    scoring_section = html[:placeholder_start]
    placeholder_section = html[placeholder_start:]

    for factor_id in (
        "A2_CNN_FEAR_GREED",
        "B5_SOCIAL_EUPHORIA",
        "D_M4_BALANCE_SHEET_PROXY",
        "D_M5_CRYPTO_SENTIMENT",
    ):
        assert factor_id not in scoring_section
        assert factor_id in placeholder_section
    assert "不进入策略 missing_weight" in placeholder_section
    assert "已退役来源，等待 SLO 缺失路径" in scoring_section
    assert "MSTR：计分输入缺失 5 分" in scoring_section
    assert "B6_VALUATION_HEAT" in scoring_section


def test_trust_zone_uses_external_source_ledger_status():
    payload = _payload()
    payload["external_source_status"] = {
        "dollar": {
            "source_id": "dollar",
            "status": "OK",
            "latest_promoted_as_of": "2026-06-30",
            "latest_started_at": "2026-07-01T02:00:00+00:00",
            "freshness_status": "DUE_SOON",
            "age_days": 8,
            "publisher_note": "official source checked today; publisher has not posted a newer observation",
            "next_action": "official source checked today; wait for publisher update for dollar",
            "message": "",
        },
        "real_rate": {
            "source_id": "real_rate",
            "status": "ERROR",
            "latest_promoted_as_of": "2026-06-29",
            "started_at": "2026-07-01T03:00:00+00:00",
            "error_message": "FRED timeout",
        },
        "fred_net_liquidity": {
            "source_id": "fred_net_liquidity",
            "status": "MISSING",
        },
        "naaim_exposure": {
            "source_id": "naaim_exposure",
            "status": "OK",
            "latest_promoted_as_of": "2026-06-24",
            "finished_at": "2026-06-25T14:00:00+00:00",
            "official_issue_as_of": "2026-06-24",
            "official_file_sha256": "abcdef1234567890",
            "success_rate_30d": 92.86,
            "success_rate_90d": 96.15,
            "samples_30d": 7,
            "samples_90d": 13,
            "consecutive_failures": 0,
            "migration_status": "MIGRATION_DUE",
            "migration_deadline": "2026-08-01",
        },
        "aaii_sentiment": {
            "source_id": "aaii_sentiment",
            "status": "FETCH_ERROR",
            "error_message": "AAII public endpoint blocked; manual import required",
            "success_rate_30d": 75.0,
            "success_rate_90d": 80.0,
            "samples_30d": 4,
            "samples_90d": 10,
            "consecutive_failures": 2,
            "stage_reliability": {
                "transport": {"success_rate_30d": 75.0, "samples_30d": 4},
                "parse": {"success_rate_30d": 100.0, "samples_30d": 3},
                "validation": {"success_rate_30d": 66.67, "samples_30d": 3},
                "promotion": {"success_rate_30d": 100.0, "samples_30d": 2},
            },
            "advancement_rate_30d": 50.0,
            "advancement_samples_30d": 2,
            "latest_expected_release_date": "2026-07-10",
            "latest_expected_release_status": "ADVANCED",
            "latest_source_channel": "official_insights_rss",
            "latest_primary_source": "public_html",
            "latest_primary_failure": "blocked",
            "fallback_rescues_7d": 2,
            "primary_success_rate_30d": 25.0,
            "primary_samples_30d": 4,
            "migration_status": "ACTION_REQUIRED",
        },
    }

    html = render_mod.render_dashboard(payload, health={"level": "OK"}, manifest_status={"status": "OK"})

    assert "外部源运维" in html
    assert "dollar" in html
    assert "2026-06-30" in html
    assert "ExternalSourceRunner · OK" in html
    assert "DUE_SOON · 8d" in html
    assert "publisher has not posted a newer observation" in html
    assert "wait for publisher update for dollar" in html
    assert "refreshExternalSource('dollar')" in html
    assert "real_rate" in html
    assert "ExternalSourceRunner · ERROR" in html
    assert "FRED timeout" in html
    assert "refreshExternalSource('real_rate')" in html
    assert "fred_net_liquidity" in html
    assert "尚无 ledger run" in html
    assert "refreshExternalSource('fred_net_liquidity')" in html
    assert "naaim_exposure" in html
    assert "NAAIM Exposure" in html
    assert "refreshExternalSource('naaim_exposure')" in html
    assert "issue=2026-06-24 sha=abcdef12" in html
    assert "aaii_sentiment" in html
    assert "AAII Sentiment" in html
    assert "AAII public endpoint blocked; manual import required" in html
    assert "refreshExternalSource('aaii_sentiment')" in html
    assert "30d 92.86% (n=7)" in html
    assert "90d 96.15% (n=13)" in html
    assert "连续失败 2" in html
    assert "渠道 official_insights_rss" in html
    assert "主源 public_html" in html
    assert "主源失败 blocked" in html
    assert "7d fallback 救回 2" in html
    assert "30d INSUFFICIENT_EVIDENCE (n=4)" in html
    assert "90d 80.00% (n=10)" in html
    assert "主源 30d INSUFFICIENT_EVIDENCE (n=4)" in html
    assert "四段 T不足(n=4)/P不足(n=3)/V不足(n=3)/R不足(n=2)" in html
    assert "推进 INSUFFICIENT_EVIDENCE (n=2)" in html
    assert "应发 2026-07-10 ADVANCED" in html
    assert "MIGRATION_DUE" in html
    assert "ACTION_REQUIRED" in html
    assert "--source aaii_sentiment --import-file ~/.hermes/external_imports/sentiment.xls" in html
    assert "--source naaim_exposure --import-file ~/.hermes/external_imports/naaim.xlsx" in html
    assert "刷新全部外部源" in html
    assert "refreshExternalSources()" in html
    assert "external-source-real_rate-status" in html


def test_external_source_controls_render_official_import_candidates():
    payload = _payload()
    payload["external_source_status"] = {
        "aaii_sentiment": {
            "source_id": "aaii_sentiment",
            "status": "FETCH_ERROR",
            "error_message": "AAII public endpoint blocked; manual import required",
        },
    }
    payload["external_import_candidates"] = [
        {
            "source_id": "aaii_sentiment",
            "label": "AAII Sentiment",
            "path": "/Users/liweishi/.hermes/external_imports/sentiment.xls",
            "mtime": "2026-07-07T11:20:00",
            "size_bytes": 12345,
        }
    ]

    html = render_mod.render_dashboard(payload, health={"level": "OK"}, manifest_status={"status": "OK"})

    assert "官方文件候选" in html
    assert "AAII Sentiment" in html
    assert "sentiment.xls" in html
    assert "2026-07-07T11:20:00" in html
    assert "导入此文件" in html
    assert "refreshExternalSourceImport(" in html
    assert "/Users/liweishi/.hermes/external_imports/sentiment.xls" in html


def test_retired_naaim_renders_frozen_history_and_weekly_probe_without_manual_prompt():
    payload = _payload()
    payload["external_source_status"] = {
        "naaim_exposure": {
            "source_id": "naaim_exposure",
            "status": "OK",
            "freshness_status": "STALE",
            "evidence_status": "MATCH",
            "migration_status": "RETIRED_PAYWALL",
            "lifecycle_status": "RETIRED_PAYWALL",
            "lifecycle_reason": "public workbook retired behind paid subscription",
            "latest_promoted_as_of": "2026-07-29",
            "latest_attempt_status": "FETCH_ERROR",
            "latest_attempt_error_message": "public workbook unavailable",
            "next_action": (
                "NAAIM public feed retired behind paywall; certified history frozen; "
                "weekly official-access probe only"
            ),
        }
    }

    html = render_mod.render_dashboard(
        payload,
        health={"level": "OK"},
        manifest_status={"status": "OK"},
    )

    assert "RETIRED_PAYWALL" in html
    assert "certified history frozen" in html
    assert "周五自动探测" in html
    assert "refreshExternalSource('naaim_exposure')" not in html
    assert "--source naaim_exposure --import-file" not in html
    assert "AAII 自动抓取失败时" in html
    assert "AAII/NAAIM 自动抓取失败时" not in html
    assert render_mod._external_precheck_metric(payload) == (
        "OK 1 / ERR 0 / MISS 0 · RETIRED 1",
        "ok",
    )
    assert render_mod._external_daily_ledger_all_ok(payload) is True


def test_missing_external_source_ledger_does_not_mark_existing_data_missing():
    payload = _payload()
    payload["soft_data"]["records"]["dollar"] = {
        "as_of": "2026-06-30",
        "data_available": True,
        "is_proxy": False,
        "source": "FRED_DXY",
    }
    payload["external_source_status"] = {
        "dollar": {
            "source_id": "dollar",
            "status": "MISSING",
        }
    }

    html = render_mod.render_dashboard(payload, health={"level": "OK"}, manifest_status={"status": "OK"})

    assert "FRED_DXY" in html
    assert "ExternalSourceRunner · MISSING" not in html
    assert "refreshExternalSource('dollar')" in html


def test_strategy_console_explains_forced_status_floor():
    payload = _payload()
    payload["scores"]["SOXL"]["final_score"] = 32.53
    payload["scores"]["SOXL"]["status"] = "REDUCE"
    payload["scores"]["SOXL"]["explain"] = [
        "Base score status: WATCH (32.53)",
        "Red-light factor count >=4: minimum REDUCE",
    ]
    payload["action_intents"]["SOXL"]["action"] = "REDUCE_AND_ROUTE"
    payload["action_intents"]["SOXL"]["status"] = "REDUCE"

    html = render_mod.render_dashboard(payload, health={"level": "OK"}, manifest_status={"status": "OK"})

    assert "分数 32.53 → 分数档 WATCH" in html
    assert "裁决档 REDUCE（Red-light factor count &gt;=4: minimum REDUCE）" in html


def test_strategy_console_uses_combo_trade_plan_when_execution_legs_are_present():
    payload = _payload()
    payload["action_intents"]["MSTR"]["trade_plan"]["legs"] = [
        {"role": "risk", "symbol": "MSTR", "target_weight": 0.0, "target_notional": 0.0, "target_shares": 0, "reference_price": 120},
        {"role": "defense_route", "symbol": "BOXX", "target_weight": 0.05, "target_notional": 500, "target_shares": 4.3, "reference_price": 117},
        {"role": "defense_route", "symbol": "DBMF", "target_weight": 0.03, "target_notional": 300, "target_shares": 10.0, "reference_price": 30},
        {"role": "defense_route", "symbol": "GLD", "target_weight": 0.02, "target_notional": 200, "target_shares": 1.0, "reference_price": 200},
    ]

    html = _render_strategy_console(payload, {"level": "OK"})

    assert "路由与执行计划一致" in html
    assert "路由/执行口径不一致" not in html
    assert "执行计划资金去向" in html and "BOXX" in html and "DBMF" in html and "GLD" in html


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


def _system_health_report(as_of: str = "2026-06-04") -> dict:
    return {
        "schema_version": "hermes-system-health-v1",
        "generated_at": "2026-07-03T07:12:00+08:00",
        "as_of": as_of,
        "data_quality_dimensions": {
            "market_completeness": 100.0,
            "provenance": 97.0,
            "timeliness": 96.0,
            "decision_input_coverage": 98.0,
        },
        "market_witness_status": {
            "status": "OK",
            "as_of": as_of,
            "summary": {"MATCH": 3, "NO_WITNESS": 2},
        },
        "health": {
            "level": "OK",
            "layers": {
                "strategy_data": {"level": "OK"},
                "position_reconciliation": {"level": "INFO"},
                "auxiliary_flows": {"level": "OK"},
            },
        },
        "audit_dimensions": [
            {
                "id": "scored_payload_cache",
                "label": "评分 payload 缓存",
                "status": "PASS",
                "detail": "cache_status.hit=true source=scheduled_run_payload",
            },
            {
                "id": "ibkr_snapshot",
                "label": "IBKR 持仓对账",
                "status": "WARN",
                "detail": "stale but non-blocking",
            },
            {
                "id": "manifest",
                "label": "数据清单",
                "status": "FAIL",
                "detail": "manifest drift in fixture",
            },
        ],
    }


def test_system_health_section_renders_20_dimension_report():
    payload = _payload()
    payload["system_health_report"] = _system_health_report()

    html = render_mod.render_dashboard(payload, health={"level": "OK"}, manifest_status={"status": "OK"})

    assert "20 维系统自检" in html
    assert "System Health Audit" in html
    assert "PASS 1" in html and "WARN 1" in html and "FAIL 1" in html
    assert "评分 payload 缓存" in html
    assert "source=scheduled_run_payload" in html
    assert "IBKR 持仓对账" in html
    assert "评分置信权重覆盖" in html
    assert "不是因子数量覆盖率" in html
    assert "决策输入覆盖" not in html
    assert "98.0" in html
    assert "OHLCV 见证" in html
    assert "MATCH 3" in html


def test_system_health_section_marks_stale_report():
    payload = _payload()
    report = _system_health_report(as_of="2026-06-03")
    report["stale"] = True
    payload["system_health_report"] = report

    html = render_mod.render_dashboard(payload, health={"level": "OK"}, manifest_status={"status": "OK"})

    assert "STALE" in html
    assert "报告 as_of=2026-06-03" in html
    assert "页面 as_of=2026-06-04" in html


def test_external_precheck_summary_renders_latest_result():
    payload = _payload()
    payload["external_precheck_status"] = {
        "ready": True,
        "blocking_sources": [],
        "warning_sources": ["dollar"],
        "refresh": {"ok": True, "ok_count": 5, "error_count": 0},
        "sources": {
            "naaim_exposure": {
                "label": "NAAIM Exposure",
                "status": "OK",
                "freshness_status": "OK",
                "latest_promoted_as_of": "2026-07-01",
                "finished_at": "2026-07-02T23:05:13+00:00",
                "official_issue_as_of": "2026-07-01",
                "official_file_sha256": "9296ac10697e3b8c6a3323af5c9c9663a76fe5ca9b7c5704474d4f0cec6fdcd9",
            },
            "dollar": {
                "label": "DXY / Dollar",
                "status": "OK",
                "freshness_status": "DUE_SOON",
                "latest_promoted_as_of": "2026-06-26",
                "finished_at": "2026-07-02T23:05:07+00:00",
                "age_days": 7,
            },
        },
        "source_path": "/Users/liweishi/.hermes/logs/external/external_precheck_latest.json",
    }

    html = render_mod.render_dashboard(payload, health={"level": "OK"}, manifest_status={"status": "OK"})

    assert "外部源预检" in html
    assert "External Precheck" in html
    assert "READY" in html
    assert "ok=5 error=0" in html
    assert "warning=dollar" in html
    assert "NAAIM Exposure" in html
    assert "issue=2026-07-01 sha=9296ac10" in html
    assert "DUE_SOON · 7d" in html


def test_trust_health_embeds_morning_external_precheck_report():
    payload = _payload()
    payload["external_precheck_status"] = {
        "ready": True,
        "blocking_sources": [],
        "warning_sources": ["dollar", "real_rate"],
        "nonblocking_refresh_error_sources": ["aaii_sentiment"],
        "blocking_refresh_error_sources": [],
        "refresh": {"ok": False, "ok_count": 4, "error_count": 1},
        "source_path": "/Users/liweishi/.hermes/logs/external/external_precheck_latest.json",
        "markdown_path": "/Users/liweishi/.hermes/logs/external/external_precheck_latest.md",
        "markdown_text": (
            "# External Precheck 2026-07-05\n\n"
            "- ready: `True`\n"
            "- nonblocking_refresh_error_sources: `['aaii_sentiment']`\n\n"
            "| Source | Status | Latest | Action | Detail |\n"
            "|---|---:|---:|---|---|\n"
            "| aaii_sentiment | OK | 2026-07-02 | run refresh_external --source aaii_sentiment | AAII public endpoint blocked |\n"
        ),
    }

    html = render_mod.render_dashboard(payload, health={"level": "OK"}, manifest_status={"status": "OK"})
    trust_section = html[html.index("今日可信度与系统状态"):html.index("区域 5 · 数据信任区")]

    assert "晨间外部源取证" in trust_section
    assert "ready=True" in trust_section
    assert "warning=2" in trust_section
    assert "retry_error=1" in trust_section
    assert "缓存可用" in trust_section
    assert "external_precheck_latest.md" in trust_section
    assert "# External Precheck 2026-07-05" in trust_section
    assert "AAII public endpoint blocked" in trust_section
    assert "重跑晨间预检" in trust_section
    assert "rerunExternalPrecheck()" in html
    assert "/api/rerun_external_precheck" in html


def test_external_precheck_summary_labels_nonblocking_refresh_errors():
    payload = _payload()
    payload["external_precheck_status"] = {
        "ready": True,
        "blocking_sources": [],
        "warning_sources": ["dollar"],
        "nonblocking_refresh_error_sources": ["aaii_sentiment"],
        "blocking_refresh_error_sources": [],
        "refresh": {"ok": False, "ok_count": 4, "error_count": 1},
        "sources": {
            "aaii_sentiment": {
                "label": "AAII Sentiment",
                "status": "OK",
                "freshness_status": "OK",
                "latest_promoted_as_of": "2026-07-02",
                "latest_attempt_status": "PARSE_ERROR",
                "latest_attempt_error_message": "old import file",
            },
            "dollar": {
                "label": "DXY / Dollar",
                "status": "OK",
                "freshness_status": "DUE_SOON",
                "latest_promoted_as_of": "2026-06-26",
                "age_days": 8,
            },
        },
    }

    html = render_mod.render_dashboard(payload, health={"level": "OK"}, manifest_status={"status": "OK"})
    summary = html[html.index("外部源预检 / External Precheck"):html.index("20 维系统自检 / System Health Audit")]

    assert "READY" in summary
    assert "retry_error=1" in summary
    assert "缓存可用" in summary
    assert "nonblocking=aaii_sentiment" in summary
    assert "ok=4 error=1" not in summary


def test_external_precheck_summary_explains_skipped_stale_import_file():
    payload = _payload()
    payload["external_precheck_status"] = {
        "ready": True,
        "blocking_sources": [],
        "warning_sources": [],
        "nonblocking_refresh_error_sources": ["aaii_sentiment"],
        "blocking_refresh_error_sources": [],
        "refresh": {
            "ok": False,
            "ok_count": 4,
            "error_count": 1,
            "runs": [
                {
                    "source_id": "aaii_sentiment",
                    "status": "FETCH_ERROR",
                    "fallback_import_skipped": "/Users/liweishi/.hermes/external_imports/sentiment.xls",
                    "fallback_import_skip_reason": "previous failure for same official file hash",
                }
            ],
        },
        "sources": {
            "aaii_sentiment": {
                "label": "AAII Sentiment",
                "status": "OK",
                "freshness_status": "OK",
                "latest_promoted_as_of": "2026-07-02",
            },
        },
    }

    html = render_mod.render_dashboard(payload, health={"level": "OK"}, manifest_status={"status": "OK"})
    summary = html[html.index("外部源预检 / External Precheck"):html.index("20 维系统自检 / System Health Audit")]

    assert "跳过旧下载文件" in summary
    assert "sentiment.xls" in summary
    assert "previous failure for same official file hash" in summary


def test_external_precheck_summary_does_not_override_current_daily_ledger():
    payload = _payload()
    payload["external_source_status"] = {
        source: {
            "source_id": source,
            "status": "OK",
            "latest_promoted_as_of": "2026-07-02",
            "freshness_status": "OK",
        }
        for source in ("dollar", "real_rate", "fred_net_liquidity", "naaim_exposure", "aaii_sentiment")
    }
    payload["external_precheck_status"] = {
        "ready": False,
        "blocking_sources": ["fred_net_liquidity"],
        "warning_sources": [],
        "refresh": {"ok": False, "ok_count": 4, "error_count": 1},
        "sources": {
            "fred_net_liquidity": {
                "label": "FRED Net Liquidity",
                "status": "FETCH_ERROR",
                "latest_promoted_as_of": None,
                "error_message": "404 Client Error",
            }
        },
        "source_path": "/Users/liweishi/.hermes/logs/external/external_precheck_latest.json",
    }

    html = render_mod.render_dashboard(payload, health={"level": "OK"}, manifest_status={"status": "OK"})
    summary = html[html.index("外部源预检 / External Precheck"):html.index("20 维系统自检 / System Health Audit")]

    assert "PRECHECK WARN" in summary
    assert "正式 daily ledger OK，本预检异常不影响今日策略" in summary
    assert "NOT READY" not in summary


def test_system_health_history_renders_recent_reports():
    payload = _payload()
    payload["system_health_history"] = [
        {
            "as_of": "2026-07-02",
            "generated_at": "2026-07-03T08:44:09+08:00",
            "health_level": "OK",
            "counts": {"PASS": 18, "WARN": 2, "FAIL": 0},
            "layers": {"strategy_data": "OK", "position_reconciliation": "INFO", "auxiliary_flows": "OK"},
        },
        {
            "as_of": "2026-07-01",
            "generated_at": "2026-07-02T07:12:00+08:00",
            "health_level": "DEGRADED",
            "counts": {"PASS": 16, "WARN": 3, "FAIL": 1},
            "layers": {"strategy_data": "DEGRADED", "position_reconciliation": "INFO", "auxiliary_flows": "OK"},
        },
    ]

    html = render_mod.render_dashboard(payload, health={"level": "OK"}, manifest_status={"status": "OK"})

    assert "最近 7 次系统健康" in html
    assert "Health History" in html
    assert "2026-07-02" in html and "2026-07-01" in html
    assert "PASS 18" in html and "WARN 2" in html and "FAIL 0" in html
    assert "策略数据=DEGRADED" in html


def _write_health_report(report_dir, as_of: str, *, generated_at: str, input_hash: str | None = "report-hash"):
    report = _system_health_report(as_of)
    report["generated_at"] = generated_at
    report["input_hash"] = input_hash
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"system_health_{as_of}.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_system_health_report_loader_prefers_exact_as_of(monkeypatch, tmp_path):
    _write_health_report(tmp_path, "2026-06-03", generated_at="2026-07-03T08:00:00+08:00")
    _write_health_report(tmp_path, "2026-06-04", generated_at="2026-07-03T07:00:00+08:00")
    monkeypatch.setattr(server_mod, "_system_health_report_roots", lambda: [tmp_path], raising=False)

    payload = server_mod._attach_system_health_report({"as_of": "2026-06-04"})

    assert payload["system_health_report"]["as_of"] == "2026-06-04"
    assert payload["system_health_report"]["stale"] is False


def test_system_health_report_loader_prefers_matching_input_hash_over_newer_exact(monkeypatch, tmp_path):
    matching = tmp_path / "matching"
    newer_bad = tmp_path / "newer_bad"
    good = _write_health_report(
        matching,
        "2026-07-02",
        generated_at="2026-07-03T07:11:27+08:00",
        input_hash="payload-hash",
    )
    bad = _write_health_report(
        newer_bad,
        "2026-07-02",
        generated_at="2026-07-03T08:44:09+08:00",
        input_hash=None,
    )
    os.utime(good, (1000, 1000))
    os.utime(bad, (2000, 2000))
    monkeypatch.setattr(server_mod, "_system_health_report_roots", lambda: [matching, newer_bad], raising=False)

    payload = server_mod._attach_system_health_report({"as_of": "2026-07-02", "input_hash": "payload-hash"})

    assert payload["system_health_report"]["input_hash"] == "payload-hash"
    assert "matching" in payload["system_health_report"]["source_path"]


def test_system_health_report_loader_finds_matching_immutable_run(monkeypatch, tmp_path):
    report_dir = tmp_path / "system_health_runs"
    _write_health_report(
        tmp_path,
        as_of="2026-07-02",
        input_hash="later-preview",
        generated_at="2026-07-02T09:00:00+08:00",
    )
    immutable = _system_health_report("2026-07-02")
    immutable["input_hash"] = "scheduled-hash"
    immutable["generated_at"] = "2026-07-02T07:11:00+08:00"
    report_dir.mkdir(parents=True)
    (report_dir / "system_health_2026-07-02_run_scheduled-hash.json").write_text(
        json.dumps(immutable), encoding="utf-8"
    )
    monkeypatch.setattr(server_mod, "_system_health_report_roots", lambda: [tmp_path], raising=False)

    payload = server_mod._attach_system_health_report(
        {"as_of": "2026-07-02", "input_hash": "scheduled-hash"}
    )

    assert payload["system_health_report"]["input_hash"] == "scheduled-hash"
    assert "system_health_runs" in payload["system_health_report"]["source_path"]


def test_system_health_report_loader_attaches_newest_as_stale(monkeypatch, tmp_path):
    _write_health_report(tmp_path, "2026-06-02", generated_at="2026-07-03T07:00:00+08:00")
    _write_health_report(tmp_path, "2026-06-03", generated_at="2026-07-03T08:00:00+08:00")
    monkeypatch.setattr(server_mod, "_system_health_report_roots", lambda: [tmp_path], raising=False)

    payload = server_mod._attach_system_health_report({"as_of": "2026-06-04"})

    assert payload["system_health_report"]["as_of"] == "2026-06-03"
    assert payload["system_health_report"]["stale"] is True
    assert payload["system_health_report"]["requested_as_of"] == "2026-06-04"


def test_system_health_report_roots_include_sibling_versioned_releases(monkeypatch, tmp_path):
    releases = tmp_path / "releases"
    current = releases / "new_release"
    old_report_dir = releases / "old_release" / "hermes_escape_top" / "reports"
    _write_health_report(old_report_dir, "2026-06-04", generated_at="2026-07-03T07:00:00+08:00")
    monkeypatch.setattr(server_mod, "BASE_DIR", current)
    monkeypatch.setattr(server_mod, "PACKAGE_DIR", current / "hermes_escape_top")

    payload = server_mod._attach_system_health_report({"as_of": "2026-06-04"})

    assert payload["system_health_report"]["as_of"] == "2026-06-04"
    assert payload["system_health_report"]["stale"] is False
    assert "old_release" in payload["system_health_report"]["source_path"]


def test_external_precheck_loader_attaches_latest_json(monkeypatch, tmp_path):
    status_path = tmp_path / "external_precheck_latest.json"
    status_path.write_text(
        json.dumps(
            {
                "ready": True,
                "blocking_sources": [],
                "warning_sources": [],
                "refresh": {"ok": True, "ok_count": 5, "error_count": 0},
                "sources": {"dollar": {"status": "OK", "latest_promoted_as_of": "2026-06-26"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(server_mod, "_external_precheck_status_paths", lambda: [status_path], raising=False)

    payload = server_mod._attach_external_precheck_status({})

    assert payload["external_precheck_status"]["ready"] is True
    assert payload["external_precheck_status"]["source_path"] == str(status_path)


def test_external_precheck_loader_attaches_sibling_markdown(monkeypatch, tmp_path):
    status_path = tmp_path / "external_precheck_latest.json"
    markdown_path = tmp_path / "external_precheck_latest.md"
    status_path.write_text(
        json.dumps({"ready": True, "blocking_sources": [], "warning_sources": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    markdown_path.write_text("# External Precheck\n\n| Source | Status |\n|---|---|\n| dollar | OK |\n", encoding="utf-8")
    monkeypatch.setattr(server_mod, "_external_precheck_status_paths", lambda: [status_path], raising=False)

    payload = server_mod._attach_external_precheck_status({})

    status = payload["external_precheck_status"]
    assert status["source_path"] == str(status_path)
    assert status["markdown_path"] == str(markdown_path)
    assert "| dollar | OK |" in status["markdown_text"]


def test_external_precheck_loader_marks_old_report_stale(monkeypatch, tmp_path):
    status_path = tmp_path / "external_precheck_latest.json"
    status_path.write_text(
        json.dumps({"ready": True, "blocking_sources": [], "warning_sources": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    old = 946684800  # 2000-01-01T00:00:00Z
    os.utime(status_path, (old, old))
    monkeypatch.setattr(server_mod, "_external_precheck_status_paths", lambda: [status_path], raising=False)

    payload = server_mod._attach_external_precheck_status({})

    status = payload["external_precheck_status"]
    assert status["stale"] is True
    assert status["mtime_date"] == "2000-01-01"


def test_external_import_candidate_loader_attaches_latest_official_file(monkeypatch, tmp_path):
    import_path = tmp_path / "sentiment.xls"
    import_path.write_bytes(b"official-aaii-file")

    class Profile:
        label = "AAII Sentiment"

    monkeypatch.setattr(server_mod, "IMPORT_FILE_SOURCE_IDS", ("aaii_sentiment",), raising=False)
    monkeypatch.setattr(server_mod, "profile_for", lambda source_id: Profile(), raising=False)
    monkeypatch.setattr(server_mod, "pending_import_file", lambda source_id, archive_dir: import_path, raising=False)

    payload = server_mod._attach_external_import_candidates({})

    candidate = payload["external_import_candidates"][0]
    assert candidate["source_id"] == "aaii_sentiment"
    assert candidate["label"] == "AAII Sentiment"
    assert candidate["path"] == str(import_path)
    assert candidate["size_bytes"] == len(b"official-aaii-file")
    assert "T" in candidate["mtime"]


def test_trust_health_marks_stale_external_precheck_report():
    payload = _payload()
    payload["external_precheck_status"] = {
        "ready": True,
        "stale": True,
        "mtime_date": "2026-07-04",
        "blocking_sources": [],
        "warning_sources": [],
        "nonblocking_refresh_error_sources": [],
        "blocking_refresh_error_sources": [],
        "refresh": {"ok": True, "ok_count": 5, "error_count": 0},
        "source_path": "/Users/liweishi/.hermes/logs/external/external_precheck_latest.json",
    }

    html = render_mod.render_dashboard(payload, health={"level": "OK"}, manifest_status={"status": "OK"})
    trust_section = html[html.index("今日可信度与系统状态"):html.index("区域 5 · 数据信任区")]
    precheck_card = trust_section[trust_section.index("晨间外部源取证"):]

    assert "STALE REPORT" in precheck_card
    assert "报告日期=2026-07-04" in precheck_card
    assert "等待今日 06:45/07:05 预检" in precheck_card
    assert ">READY<" not in precheck_card


def test_trust_health_separates_precheck_stale_from_source_due_soon():
    payload = _payload()
    payload["external_source_status"] = {
        "dollar": {
            "source_id": "dollar",
            "status": "OK",
            "freshness_status": "DUE_SOON",
            "latest_promoted_as_of": "2026-06-26",
        },
        "real_rate": {
            "source_id": "real_rate",
            "status": "OK",
            "freshness_status": "OK",
            "latest_promoted_as_of": "2026-07-02",
        },
    }
    payload["external_precheck_status"] = {
        "ready": True,
        "stale": True,
        "mtime_date": "2026-07-04",
        "blocking_sources": [],
        "warning_sources": [],
        "refresh": {"ok": True, "ok_count": 2, "error_count": 0},
    }

    html = render_mod.render_dashboard(payload, health={"level": "OK"}, manifest_status={"status": "OK"})
    trust_section = html[html.index("今日可信度与系统状态"):html.index("区域 5 · 数据信任区")]

    assert "预检报告：陈旧（2026-07-04）" in trust_section
    assert "外部源数据 DUE_SOON：dollar" in trust_section
    assert "到期前刷新" in trust_section
    assert "refreshExternalSource('dollar')" in trust_section


def test_system_health_history_loader_deduplicates_latest_by_as_of(monkeypatch, tmp_path):
    older = tmp_path / "older"
    newer = tmp_path / "newer"
    _write_health_report(older, "2026-07-02", generated_at="2026-07-03T07:11:27+08:00")
    _write_health_report(newer, "2026-07-02", generated_at="2026-07-03T08:44:09+08:00")
    _write_health_report(newer, "2026-07-01", generated_at="2026-07-02T07:12:00+08:00")
    monkeypatch.setattr(server_mod, "_system_health_report_roots", lambda: [older, newer], raising=False)

    payload = server_mod._attach_system_health_history({})

    history = payload["system_health_history"]
    assert [row["as_of"] for row in history] == ["2026-07-02", "2026-07-01"]
    assert history[0]["generated_at"] == "2026-07-03T08:44:09+08:00"
    assert history[0]["counts"]["PASS"] == 1


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


def test_risk_panels_explain_no_active_legs_instead_of_waiting():
    payload = {
        "portfolio_risk": {
            "binding_constraint": "NO_ACTIVE_LEGS",
            "legs_used": [],
            "legs_reported": ["MSTR", "FNGU", "SOXL"],
            "target_weights": {"MSTR": 0.0, "FNGU": 0.0, "SOXL": 0.0},
            "explain": ["Excluded hard-valve legs from gross calculation: FNGU,MSTR,SOXL"],
        },
        "risk_contributions": {},
        "stress_scenarios": [],
        "routing_context": {
            "defcon1_rule": "max A >= 12 and QQQ trend broken",
            "qqq": {"close": 100, "ema20": 101, "ema50": 102, "ma200": 103},
            "module_a": {"MSTR": 13},
            "brkb_defense": {},
        },
    }

    html = render_mod._render_p3_visuals(payload)

    assert "当前风险腿目标为 0" in html
    assert "防守腿路由后风险尚未纳入" in html
    assert "等待下一次日跑" not in html


def test_health_banner_ignores_auxiliary_info_checks():
    html = _render_health_banner({
        "level": "OK",
        "checks": [
            {"level": "INFO", "label": "IBKR 快照陈旧", "detail": "age=3600s max=900s"},
        ],
    })

    assert "运行健康" in html
    assert "IBKR 快照陈旧" not in html
    assert "运行降级" not in html


def test_degraded_health_banner_lists_only_actionable_checks():
    html = _render_health_banner({
        "level": "DEGRADED",
        "checks": [
            {"level": "INFO", "label": "IBKR 快照陈旧", "detail": "age=3600s max=900s"},
            {"level": "DEGRADED", "label": "外部数据源陈旧", "detail": "dollar"},
        ],
    })

    assert "外部数据源陈旧" in html
    assert "IBKR 快照陈旧" not in html
    assert "#runbook-data" in html
    assert "#runbook-ibkr" not in html


# --- value-correctness regression guards (the 2026-06-14 dashboard bugs) ---
# These assert the rendered VALUES, not just that a section/string is present —
# the fixture already fed module_a={MSTR:14,...} but nothing checked the output,
# so "A模块 NA" shipped. Each test below would have failed on that bug.

def test_evidence_strip_shows_module_a_max_not_na():
    # module_a is a per-symbol dict; the DEFCON line must show the max (14),
    # never "A模块 NA" (the .get("score")->None render bug).
    html = render_mod._render_evidence_strip(_payload())
    assert "A模块 14" in html
    assert "A模块 NA" not in html


def test_evidence_strip_shows_brkb_reason_when_corr_missing():
    # corr is None when BRK.B already failed MA200 (short-circuit) — show the real
    # reason from the payload, not a bare "BRK.B NA".
    payload = _payload()
    payload["routing_context"]["brkb_defense"] = {
        "degraded": True, "reason": "BRK.B close <= MA200",
        "corr_to_spy": None, "threshold": 0.85,
    }
    html = render_mod._render_evidence_strip(payload)
    # the real reason is shown ("<=" is HTML-escaped in source, displays correctly)
    assert "BRK.B close" in html and "MA200" in html
    assert "BRK.B NA" not in html


def test_trust_latest_data_date_backs_out_latency():
    # The trust zone must show the actual data date (as_of - latency), not the run
    # as_of, so a stale source reads stale (the dollar-looked-fresh bug).
    f = render_mod._trust_latest_data_date
    assert f({"as_of": "2026-06-12", "latency_days": 6}) == "2026-06-06"
    assert f({"as_of": "2026-06-12", "latency_days": 0}) == "2026-06-12"
    assert f({"latest_data_date": "2026-06-01", "as_of": "2026-06-12", "latency_days": 6}) == "2026-06-01"


def test_dashboard_no_false_na_or_undefined_leaks_with_full_payload():
    # Render-invariant: a fully-populated payload must not leak NA/undefined/NaN
    # into the decision evidence (the whole class that shipped on 2026-06-14).
    html = render_mod.render_dashboard(_payload(), health={"level": "OK"}, manifest_status={"status": "OK"})
    for token in ("undefined", "NaN", "[object Object]"):
        assert token not in html
    assert "A模块 NA" not in html


def test_decision_history_strip_renders_per_symbol_sequence():
    # The consistency strip: a REDUCE->EXIT->REDUCE flip must surface as current
    # status + a flip count, with the valve day marked — so an operator sees at a
    # glance whether a decision is stable or whipsawing.
    payload = _payload()
    payload["status_history"] = {
        "SOXL": [
            {"as_of": "2026-06-10", "status": "REDUCE", "valve": False},
            {"as_of": "2026-06-11", "status": "EXIT", "valve": True},
            {"as_of": "2026-06-12", "status": "REDUCE", "valve": False},
        ],
    }
    html = render_mod._render_status_history(payload)
    assert "决策历史" in html and "SOXL" in html
    assert "当前 REDUCE" in html
    assert "翻转 2 次" in html
    assert "⚠硬阀门" in html


def test_decision_history_strip_empty_when_absent():
    # Back-compatible: no status_history injected -> nothing rendered.
    assert render_mod._render_status_history(_payload()) == ""


def test_valve_radar_marks_newly_fired_valve_pending_confirmation():
    payload = _payload()
    payload["scores"]["MSTR"]["hard_valve_hits"] = ["H-M1", "H-M4"]
    payload["prev_valves"] = {"MSTR": ["H-M1"], "FNGU": [], "SOXL": []}  # H-M4 is new today
    html = render_mod._render_hard_valve_radar(payload)
    assert "今日新触发" in html and "H-M4" in html and "待明日收盘确认" in html


def test_valve_radar_no_new_badge_without_prev_valves():
    # No previous official run -> don't label everything as "newly fired".
    payload = _payload()
    payload.pop("prev_valves", None)
    assert "今日新触发" not in render_mod._render_hard_valve_radar(payload)


def test_position_desk_warns_and_dims_when_snapshot_stale():
    payload = _payload()
    payload.setdefault("ibkr", {})["snapshot_stale"] = True
    payload["ibkr"]["snapshot_age_seconds"] = 152152  # ~42h
    html = render_mod._render_position_desk(payload, history=[])
    assert "请勿据此下单" in html and "约 42 小时前" in html
    assert "opacity:.45" in html  # actionable cells de-emphasized
