from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import pandas as pd

from ..config import load_config, resolve_path, trade_symbols
from ..core.data.store import safe_symbol
from ..pipeline import score_pipeline
from ..scripts.backfill_history import all_backfill_symbols, backfill


def refresh_score_with_market_data(requested_as_of: Any = "latest") -> Dict[str, Any]:
    """Refresh OHLCV first, then score the newest locally available trading day."""
    config = load_config()
    history_dir = resolve_path(config, "history_dir")
    symbols = all_backfill_symbols(config)
    latest_before = latest_history_date(config, _critical_symbols(config))
    stale_flow_symbols = _stale_symbols(config, _flow_symbols(config), latest_before) if latest_before else []
    if _history_is_fresh(latest_before) and not stale_flow_symbols:
        refresh = {}
        history_refreshed = False
        skip_reason = f"core history already fresh at {latest_before}"
    else:
        refresh_symbols = symbols if not _history_is_fresh(latest_before) else stale_flow_symbols
        refresh = backfill(
            refresh_symbols,
            start=(date.today() - timedelta(days=500)).isoformat(),
            end=None,
            store_dir=history_dir,
            repair_overlap_days=5,
        )
        history_refreshed = True
        skip_reason = "" if refresh_symbols == symbols else f"core fresh; refreshed stale flow symbols: {','.join(stale_flow_symbols)}"
    as_of = latest_history_date(config, _critical_symbols(config)) or _normalize_as_of(requested_as_of)
    payload = score_pipeline(as_of)
    payload["refresh_status"] = {
        "history_refreshed": history_refreshed,
        "skip_reason": skip_reason,
        "requested_as_of": str(requested_as_of),
        "effective_as_of": as_of,
        "history_dir": str(history_dir),
        "symbols_requested": len(symbols),
        "symbols_refreshed_requested": len(refresh),
        "symbols_updated": sum(1 for item in refresh.values() if item.updated),
        "latest_by_symbol": {
            symbol: result.end_date
            for symbol, result in sorted(refresh.items())
            if symbol in _critical_symbols(config)
        },
    }
    return payload


def _history_is_fresh(as_of: Optional[str], max_calendar_lag_days: int = 3) -> bool:
    if not as_of:
        return False
    try:
        lag = (date.today() - date.fromisoformat(as_of)).days
    except ValueError:
        return False
    return 0 <= lag <= max_calendar_lag_days


def latest_history_date(config: Optional[Dict[str, Any]] = None, symbols: Optional[Iterable[str]] = None) -> Optional[str]:
    cfg = config or load_config()
    history_dir = resolve_path(cfg, "history_dir")
    candidates = []
    for symbol in symbols or _critical_symbols(cfg):
        path = history_dir / f"{safe_symbol(symbol)}.csv"
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path, usecols=["date"])
        except Exception:
            continue
        if frame.empty or "date" not in frame:
            continue
        dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
        if not dates.empty:
            candidates.append(dates.max().date())
    if not candidates:
        return None
    return min(candidates).isoformat()


def latest_cached_as_of() -> Optional[str]:
    cfg = load_config()
    path = resolve_path(cfg, "archive_dir") / "audit_log.jsonl"
    if not path.exists():
        return None
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line).get("payload", {})
        except Exception:
            continue
        as_of = str(payload.get("as_of", ""))[:10]
        if as_of:
            return as_of
    return None


def _critical_symbols(config: Dict[str, Any]) -> set[str]:
    symbols = set(trade_symbols(config))
    symbols.update({"QQQ", "SOXX", "SPY", "^VIX"})
    return symbols


def _flow_symbols(config: Dict[str, Any]) -> set[str]:
    symbols = set(trade_symbols(config))
    for components in config.get("component_proxies", {}).values():
        symbols.update(components)
    return symbols


def _stale_symbols(config: Dict[str, Any], symbols: Iterable[str], reference_as_of: Optional[str]) -> list[str]:
    if not reference_as_of:
        return sorted(set(symbols))
    latest = _latest_by_symbol(config, symbols)
    out = []
    ref = pd.Timestamp(str(reference_as_of)[:10]).date()
    for symbol in sorted(set(symbols)):
        day = latest.get(symbol)
        if day is None or day < ref:
            out.append(symbol)
    return out


def _latest_by_symbol(config: Dict[str, Any], symbols: Iterable[str]) -> Dict[str, Optional[date]]:
    history_dir = resolve_path(config, "history_dir")
    out: Dict[str, Optional[date]] = {}
    for symbol in symbols:
        path = history_dir / f"{safe_symbol(symbol)}.csv"
        if not path.exists():
            out[symbol] = None
            continue
        try:
            frame = pd.read_csv(path, usecols=["date"])
            dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
        except Exception:
            dates = pd.Series(dtype="datetime64[ns]")
        out[symbol] = dates.max().date() if not dates.empty else None
    return out


def _normalize_as_of(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) >= 10 and text[:4].isdigit():
        return text[:10]
    fallback = latest_history_date()
    if fallback:
        return fallback
    return "2026-06-02"
