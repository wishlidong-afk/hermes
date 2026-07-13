"""Daily run-health gate.

Turns the scattered freshness/quality/IBKR/manifest signals into ONE loud
verdict so a degraded run (stale data, dead source, IBKR down, manifest drift,
no cache) is impossible to miss — instead of silently shipping a "looks fine"
daily report. Read-only; consumed by the WebUI banner and /api/health_status.

Levels: OK (green) · DEGRADED (amber) · CRITICAL (red).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from ..core.data.external_sources.ledger import (
    CANONICAL_EVIDENCE_CRITICAL_STATUSES,
    canonical_evidence_issue,
)
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

_LAYER_LABELS = {
    "strategy_data": "策略数据",
    "position_reconciliation": "持仓对账",
    "auxiliary_flows": "辅助资金流",
}


def compute_health(
    payload: Dict[str, Any],
    manifest_status: Optional[Dict[str, Any]] = None,
    today: Optional[date] = None,
    now: Optional[datetime] = None,
    ibkr_max_age_seconds: float = 15 * 60,
    receipt_timeout_seconds: float = 2 * 60 * 60,
    receipt_max_age_seconds: float = 26 * 60 * 60,
) -> Dict[str, Any]:
    today = today or date.today()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    manifest_status = manifest_status or {}
    checks: List[Dict[str, str]] = []

    def add(level: str, label: str, detail: str = "", layer: str = "strategy_data") -> None:
        checks.append({"level": level, "label": label, "detail": detail, "layer": layer})

    cache = payload.get("cache_status") or {}
    as_of = str(payload.get("as_of", ""))[:10]
    breakdown = payload.get("data_quality_breakdown") or {}
    ibkr = payload.get("ibkr") or {}
    dq = payload.get("data_quality") or {}
    receipt = payload.get("run_receipt") or {}
    sip_flow = payload.get("alpaca_daily_flow") or {}
    sip_status = payload.get("alpaca_daily_flow_status") or {}
    external_sources = payload.get("external_source_status") or {}

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

    # 6. Today's scheduled receipt is the orchestration truth. The 26-hour age
    #    limit relies on com.hermes.daily running at 07:10 on EVERY calendar day
    #    (its StartCalendarInterval has no Weekday filter), including weekends
    #    and market holidays. Price freshness above remains trading-calendar based.
    #    Legacy receipts have no explicit status, so infer it from ok.
    receipt_status = str(receipt.get("status") or ("OK" if receipt.get("ok") else "FAILED" if receipt else "MISSING"))
    receipt_time = _parse_timestamp(receipt.get("finished_at") or receipt.get("run_at"))
    receipt_started = _parse_timestamp(receipt.get("started_at") or receipt.get("run_at"))
    receipt_age = _age_seconds(receipt_time, now)
    if receipt_status == "MISSING":
        add("CRITICAL", "今日官方 run 无回执", "scheduled receipt missing")
    elif str(receipt.get("run_type") or "") != "scheduled":
        add("CRITICAL", "官方 run 回执类型异常", f"run_type={receipt.get('run_type')}")
    elif receipt_status == "FAILED":
        detail = str(receipt.get("failed_step") or "unknown")
        error = str(receipt.get("error") or "")
        add("CRITICAL", "官方 run 失败", f"step={detail} {error}".strip()[:160])
    elif receipt_status == "RUNNING":
        running_age = _age_seconds(receipt_started, now)
        if running_age is None or running_age > receipt_timeout_seconds:
            add("CRITICAL", "官方 run 超时", f"running_age_seconds={running_age}")
        else:
            add("DEGRADED", "官方 run 正在执行", f"running_age_seconds={running_age:.0f}")
    elif receipt_status == "OK":
        if not receipt.get("ok"):
            add("CRITICAL", "官方 run 自检失败", "receipt status=OK but ok=false")
        elif receipt_age is None or receipt_age > receipt_max_age_seconds:
            add("CRITICAL", "官方 run 已停摆", f"last_run={receipt.get('run_at')}")
    else:
        add("CRITICAL", "官方 run 回执状态未知", receipt_status)

    # 7. IBKR is an auxiliary position-reconciliation layer, not strategy input.
    #    Keep it visible, but do not let an unstable local Gateway downgrade the
    #    official strategy/data health. Never trust the frozen snapshot_stale
    #    boolean from scoring time as the current position-truth age.
    src = str(ibkr.get("source") or "")
    ibkr_time = _parse_timestamp(ibkr.get("sync_time"))
    ibkr_age = _age_seconds(ibkr_time, now)
    if src in {"", "unavailable", "disabled"}:
        add("INFO", "IBKR 未连接", str(ibkr.get("error") or "")[:60], "position_reconciliation")
    elif ibkr_age is None:
        add("INFO", "IBKR 快照时间缺失", f"source={src}", "position_reconciliation")
    elif ibkr_age > max(float(ibkr_max_age_seconds), 0.0):
        add("INFO", "IBKR 快照陈旧", f"age={ibkr_age:.0f}s max={ibkr_max_age_seconds:.0f}s", "position_reconciliation")

    # 8. SIP is auxiliary: stale data degrades the page but never converts a
    #    successful core scheduled run into a false run failure.
    sip_as_of = str(sip_flow.get("as_of") or "")[:10]
    if str(sip_status.get("status") or "") in {"ERROR", "MISSING"}:
        add(
            "DEGRADED",
            "SIP 资金流不可用",
            str(sip_status.get("error") or sip_status.get("status") or "")[:120],
            "auxiliary_flows",
        )
    elif sip_flow and sip_as_of:
        sip_stale = _completed_trading_days_after(sip_as_of, today)
        if sip_stale >= 1:
            add("DEGRADED", "SIP 资金流陈旧", f"as_of={sip_as_of} stale={sip_stale}d", "auxiliary_flows")

    # 9. Source-run ledger: tells operators whether the automatic external
    #    refresh machinery itself ran. This is separate from CSV freshness: a
    #    failed external fetch keeps cached data, but the failure should be
    #    visible before it turns into a soft-data SLO breach.
    if isinstance(external_sources, dict):
        for source_id, row in external_sources.items():
            if not isinstance(row, dict):
                continue
            if row.get("active") is False:
                continue
            status = str(row.get("status") or "")
            freshness = str(row.get("freshness_status") or "")
            evidence = canonical_evidence_issue(row)
            if evidence:
                detail = f"{source_id}: {evidence} {row.get('evidence_detail') or ''}".strip()
                if evidence in CANONICAL_EVIDENCE_CRITICAL_STATUSES:
                    add("CRITICAL", "外部数据证据失配", detail[:160])
                else:
                    add("DEGRADED", "外部数据证据未绑定", detail[:160])
                continue
            if status == "OK" and freshness == "STALE":
                detail = (
                    f"{source_id}: age={row.get('age_days')}d "
                    f"{row.get('next_action') or ''}"
                ).strip()
                add("DEGRADED", "外部数据源陈旧", detail[:160])
                continue
            if status == "OK":
                continue
            if status == "MISSING":
                add("DEGRADED", "外部数据源未自动刷新", str(source_id))
                continue
            detail = f"{source_id}: {status} {row.get('error_message') or row.get('error') or ''}".strip()
            add("DEGRADED", "外部数据源刷新失败", detail[:160])

    layers = _layers(checks)
    overall = layers["strategy_data"]["level"]

    return {
        "level": overall,
        "layers": layers,
        "as_of": as_of,
        "stale_trading_days": stale,
        "receipt_status": receipt_status,
        "receipt_age_seconds": receipt_age,
        "ibkr_age_seconds": ibkr_age,
        "sip_as_of": sip_as_of,
        "checks": checks,
        "summary": _summary(overall, checks),
    }


def _layers(checks: List[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for key, label in _LAYER_LABELS.items():
        subset = [c for c in checks if c.get("layer", "strategy_data") == key]
        out[key] = {
            "label": label,
            "level": _level_from_checks(subset),
            "checks": subset,
        }
    return out


def _level_from_checks(checks: List[Dict[str, str]]) -> str:
    if any(c.get("level") == "CRITICAL" for c in checks):
        return "CRITICAL"
    if any(c.get("level") == "DEGRADED" for c in checks):
        return "DEGRADED"
    if any(c.get("level") == "INFO" for c in checks):
        return "INFO"
    return "OK"


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


def _age_seconds(value: Optional[datetime], now: datetime) -> Optional[float]:
    if value is None:
        return None
    return max(0.0, (now - value.astimezone(now.tzinfo)).total_seconds())


def _summary(level: str, checks: List[Dict[str, str]]) -> str:
    if level == "OK":
        return "策略数据正常：行情新鲜、数据清单一致、数据质量达标。"
    crit = [c["label"] for c in checks if c["level"] == "CRITICAL" and c.get("layer", "strategy_data") == "strategy_data"]
    deg = [c["label"] for c in checks if c["level"] == "DEGRADED" and c.get("layer", "strategy_data") == "strategy_data"]
    parts = []
    if crit:
        parts.append("严重：" + "、".join(crit))
    if deg:
        parts.append("降级：" + "、".join(deg))
    return "；".join(parts)
