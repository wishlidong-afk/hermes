"""T20 decision-workbench smoke tests."""
from __future__ import annotations

import json
import os

from hermes_escape_top.web import render as render_mod
from hermes_escape_top.web import server as server_mod
from hermes_escape_top.web.render import _render_decision_workbench, _render_health_banner, _render_strategy_console


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
    assert "health-strip" in html
    assert "策略数据链" in html and "外部数据链" in html and "持仓/执行链" in html
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
            "next_action": "watch next publication",
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
        },
        "aaii_sentiment": {
            "source_id": "aaii_sentiment",
            "status": "FETCH_ERROR",
            "error_message": "AAII public endpoint blocked; manual import required",
        },
    }

    html = render_mod.render_dashboard(payload, health={"level": "OK"}, manifest_status={"status": "OK"})

    assert "外部源运维" in html
    assert "dollar" in html
    assert "2026-06-30" in html
    assert "ExternalSourceRunner · OK" in html
    assert "DUE_SOON · 8d" in html
    assert "watch next publication" in html
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
    assert "--source aaii_sentiment --import-file ~/.hermes/external_imports/sentiment.xls" in html
    assert "--source naaim_exposure --import-file ~/.hermes/external_imports/naaim.xlsx" in html
    assert "刷新全部外部源" in html
    assert "refreshExternalSources()" in html
    assert "external-source-real_rate-status" in html


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
