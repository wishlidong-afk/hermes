"""Daily run-health gate.

Turns the scattered freshness/quality/IBKR/manifest signals into ONE loud
verdict so a degraded run (stale data, dead source, IBKR down, manifest drift,
no cache) is impossible to miss — instead of silently shipping a "looks fine"
daily report. Read-only; consumed by the WebUI banner and /api/health_status.

Levels: OK (green) · DEGRADED (amber) · CRITICAL (red).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from .refresh import _completed_trading_days_after

# Sources that are off/unwired BY DESIGN — their absence is the steady-state
# baseline, not a degradation, so excluding them keeps "no alarm" meaningful.
_EXPECTED_OFF_SOURCES = {"gex", "valuation"}

# Soft sources backed by live market data (ETF price ratios / index levels).
# These update on every trading day; staleness is immediately actionable.
_ONLINE_SOFT_SOURCES = {
    "credit_etf", "concentration", "defensive_rotation",
    "financial_stress", "ndx_concentration", "move",
}


def compute_health(
    payload: Dict[str, Any],
    manifest_status: Optional[Dict[str, Any]] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    today = today or date.today()
    manifest_status = manifest_status or {}
    checks: List[Dict[str, str]] = []

    def add(level: str, label: str, detail: str = "") -> None:
        checks.append({"level": level, "label": label, "detail": detail})

    cache = payload.get("cache_status") or {}
    as_of = str(payload.get("as_of", ""))[:10]
    breakdown = payload.get("data_quality_breakdown") or {}
    ibkr = payload.get("ibkr") or {}
    dq = payload.get("data_quality") or {}

    # 1. Is there a scored payload at all?
    if not cache.get("hit"):
        add("CRITICAL", "无评分缓存", "NO_CACHE — 点『更新策略数据』或跑 run_daily")

    # 2. Price freshness in TRADING days (stale advice is the #1 silent failure)
    stale = _completed_trading_days_after(as_of, today) if as_of else 99
    if as_of:
        if stale >= 3:
            add("CRITICAL", f"行情陈旧 {stale} 个交易日", f"as_of={as_of}")
        elif stale >= 1:
            add("DEGRADED", f"行情落后 {stale} 个交易日", f"as_of={as_of}")

    # 3. Data-manifest integrity (drift = silent data/code mismatch)
    ms = str(manifest_status.get("status") or "")
    if ms == "DRIFT":
        add("CRITICAL", "数据清单漂移", "manifest 与历史 CSV 不一致")
    elif ms == "MISSING":
        add("DEGRADED", "数据清单缺失", "")

    # 4. Overall data-quality level
    level = str(dq.get("level") or "")
    if level in {"LOW", "BLOCKED", "NO_CACHE"}:
        add("CRITICAL", f"数据质量 {level}", f"overall={dq.get('overall_score')}")
    elif level == "MEDIUM":
        add("DEGRADED", "数据质量 MEDIUM", "")

    # 5. Soft source staleness and unexpected absence.
    #    Stale = had data but max_age_days was exceeded (reason contains "stale").
    #    Online sources (ETF-ratio / INDEX_LEVEL) going stale is CRITICAL because
    #    they derive from live market prices and should update every trading day.
    #    FRED/NAAIM sources going stale is DEGRADED (publication lags are normal).
    #    Feature-disabled sources are not unexpected — skip them.
    sources = breakdown.get("sources") or []
    stale_critical: List[str] = []
    stale_degraded: List[str] = []
    missing_unexpected: List[str] = []
    for s in sources:
        name = str(s.get("name") or "")
        status = str(s.get("status") or "")
        reason = str(s.get("reason") or "")
        if status != "MISSING":
            continue
        if name in _EXPECTED_OFF_SOURCES:
            continue
        if "feature disabled" in reason:
            continue
        if "stale" in reason:
            if name in _ONLINE_SOFT_SOURCES:
                stale_critical.append(name)
            else:
                stale_degraded.append(name)
        else:
            missing_unexpected.append(name)
    if stale_critical:
        add("CRITICAL", f"在线软数据源过期 {len(stale_critical)}", ", ".join(stale_critical[:6]))
    if stale_degraded:
        add("DEGRADED", f"软数据源过期 {len(stale_degraded)}", ", ".join(stale_degraded[:6]))
    if missing_unexpected:
        add("DEGRADED", f"软数据源意外缺失 {len(missing_unexpected)}", ", ".join(missing_unexpected[:6]))

    # 6. IBKR connectivity (can't reconcile real positions if down)
    src = str(ibkr.get("source") or "")
    if src in {"", "unavailable", "disabled"}:
        add("DEGRADED", "IBKR 未连接", str(ibkr.get("error") or "")[:60])
    elif ibkr.get("snapshot_stale"):
        add("DEGRADED", "IBKR 快照陈旧", "")

    overall = "OK"
    if any(c["level"] == "CRITICAL" for c in checks):
        overall = "CRITICAL"
    elif any(c["level"] == "DEGRADED" for c in checks):
        overall = "DEGRADED"

    return {
        "level": overall,
        "as_of": as_of,
        "stale_trading_days": stale,
        "checks": checks,
        "summary": _summary(overall, checks),
    }


def _summary(level: str, checks: List[Dict[str, str]]) -> str:
    if level == "OK":
        return "全部正常：行情新鲜、数据清单一致、数据质量达标。"
    crit = [c["label"] for c in checks if c["level"] == "CRITICAL"]
    deg = [c["label"] for c in checks if c["level"] == "DEGRADED"]
    parts = []
    if crit:
        parts.append("严重：" + "、".join(crit))
    if deg:
        parts.append("降级：" + "、".join(deg))
    return "；".join(parts)
