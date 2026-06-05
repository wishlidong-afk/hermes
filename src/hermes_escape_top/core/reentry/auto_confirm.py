from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List


def infer_execution_confirmations(
    executions: Dict[str, Any],
    reentry_plans: Dict[str, Any],
    *,
    as_of: str,
    lookback_days: int = 7,
) -> List[Dict[str, Any]]:
    """Infer T1/T2/T3 confirmations from read-only IBKR execution records.

    Only BUY executions are considered, and only when the current reentry plan is
    explicitly eligible for T1/T2/T3. This keeps automatic confirmation
    conservative: it never advances a tranche unless the strategy already says
    that tranche is allowed.
    """
    if executions.get("source") not in {"tws", "snapshot"}:
        return []
    records = executions.get("records") or []
    cutoff = _cutoff(as_of, lookback_days)
    out: List[Dict[str, Any]] = []
    for symbol, plan in sorted(reentry_plans.items()):
        tranche = str(plan.get("tranche") or "")
        if tranche not in {"T1", "T2", "T3"} or not bool(plan.get("eligible")):
            continue
        matches = [
            row for row in records
            if _symbol(row) == symbol and _is_buy(row) and _after_cutoff(row.get("time"), cutoff)
        ]
        if not matches:
            continue
        shares = sum(float(row.get("shares") or 0.0) for row in matches)
        notional = sum(float(row.get("shares") or 0.0) * float(row.get("price") or 0.0) for row in matches)
        avg_price = notional / shares if shares else 0.0
        exec_ids = sorted(str(row.get("exec_id") or "") for row in matches if row.get("exec_id"))
        latest_time = max((str(row.get("time") or "") for row in matches), default="")
        external_key = "|".join(exec_ids) if exec_ids else f"{symbol}:{tranche}:{latest_time}:{shares:g}"
        out.append({
            "symbol": symbol,
            "tranche": tranche,
            "status": "AUTO_CONFIRMED",
            "source": "ibkr_executions",
            "confirmed_at": latest_time or executions.get("sync_time"),
            "external_key": external_key,
            "payload": {
                "exec_ids": exec_ids,
                "shares": round(shares, 6),
                "avg_price": round(avg_price, 6),
                "notional": round(notional, 2),
                "execution_count": len(matches),
                "execution_source": executions.get("source"),
                "lookback_days": lookback_days,
            },
        })
    return out


def _symbol(row: Dict[str, Any]) -> str:
    return str(row.get("symbol") or "").upper().replace("BRK B", "BRK.B")


def _is_buy(row: Dict[str, Any]) -> bool:
    side = str(row.get("side") or "").upper()
    return side in {"BOT", "BUY"} or (side == "" and float(row.get("shares") or 0.0) > 0)


def _cutoff(as_of: str, lookback_days: int) -> datetime:
    try:
        base = datetime.fromisoformat(str(as_of)[:10]).replace(tzinfo=timezone.utc)
    except ValueError:
        base = datetime.now(timezone.utc)
    return base - timedelta(days=max(0, int(lookback_days)))


def _after_cutoff(value: Any, cutoff: datetime) -> bool:
    if not value:
        return True
    text = str(value).replace("Z", "+00:00")
    try:
        stamped = datetime.fromisoformat(text)
    except ValueError:
        return True
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=timezone.utc)
    return stamped.astimezone(timezone.utc) >= cutoff
