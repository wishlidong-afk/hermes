from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode

import pandas as pd

from ...config import resolve_path
from .alpaca_flow import DATA_URL, _request_json, load_alpaca_credentials
from .store import LocalStore


SCHEMA_VERSION = "hermes-market-witness-v1"
PRICE_MATCH_PCT = 0.5
PRICE_WARN_PCT = 1.0
VOLUME_MATCH_PCT = 10.0
VOLUME_WARN_PCT = 25.0
_US_EQUITY_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")


def fetch_alpaca_daily_bars(
    symbols: Iterable[str],
    as_of: str,
    credentials: Mapping[str, str],
    *,
    request_json: Callable[[str, Mapping[str, str]], dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    ordered = sorted({str(symbol).upper() for symbol in symbols if _is_supported(symbol)})
    if not ordered:
        return {}
    day = date.fromisoformat(str(as_of)[:10])
    params = {
        "symbols": ",".join(ordered),
        "timeframe": "1Day",
        "start": f"{day.isoformat()}T00:00:00Z",
        "end": f"{(day + timedelta(days=1)).isoformat()}T00:00:00Z",
        "limit": "10000",
        "feed": "sip",
        "adjustment": "raw",
        "sort": "asc",
    }
    headers = {
        "APCA-API-KEY-ID": str(credentials.get("key") or ""),
        "APCA-API-SECRET-KEY": str(credentials.get("secret") or ""),
        "Accept": "application/json",
        "User-Agent": "Hermes-Market-Witness/1.0",
    }
    transport = request_json or _request_json
    out: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in ordered}
    page_token = None
    while True:
        query = dict(params)
        if page_token:
            query["page_token"] = page_token
        payload = transport(f"{DATA_URL}?{urlencode(query)}", headers)
        for symbol, rows in (payload.get("bars") or {}).items():
            if symbol in out and isinstance(rows, list):
                out[symbol].extend(row for row in rows if isinstance(row, dict))
        page_token = payload.get("next_page_token")
        if not page_token:
            return out


def build_market_witness_payload(
    as_of: str,
    symbols: Iterable[str],
    local_bars: Mapping[str, Mapping[str, Any]],
    witness_bars: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    for symbol in sorted({str(value).upper() for value in symbols}):
        if not _is_supported(symbol):
            rows[symbol] = {
                "status": "NO_WITNESS",
                "supported": False,
                "reason": "symbol is not supported by Alpaca US equities SIP",
            }
            continue
        local = local_bars.get(symbol)
        remote = list(witness_bars.get(symbol) or [])
        rows[symbol] = _compare_bar(local, remote[-1] if remote else None)

    summary: dict[str, int] = {}
    for row in rows.values():
        status = str(row.get("status") or "UNKNOWN")
        summary[status] = summary.get(status, 0) + 1
    mismatch_states = {"DATE_MISMATCH", "PRICE_MISMATCH", "VOLUME_MISMATCH"}
    status = "WARN" if any(
        row.get("status") in mismatch_states
        or (row.get("status") == "NO_WITNESS" and row.get("supported") is not False)
        for row in rows.values()
    ) else "OK"
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": str(as_of)[:10],
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "source": "ALPACA_SIP_1DAY",
        "mode": "shadow_only_no_promotion",
        "status": status,
        "summary": summary,
        "symbols": rows,
    }


def refresh_market_witness(
    as_of: str,
    config: dict[str, Any],
    *,
    credentials: Mapping[str, str] | None = None,
    request_json: Callable[[str, Mapping[str, str]], dict[str, Any]] | None = None,
    symbols: Iterable[str] | None = None,
) -> dict[str, Any]:
    selected = sorted(set(symbols or market_witness_symbols(config)))
    local_bars = _load_local_bars(config, selected, as_of)
    try:
        auth = dict(credentials or load_alpaca_credentials())
        remote = fetch_alpaca_daily_bars(
            selected,
            as_of,
            auth,
            request_json=request_json,
        )
        payload = build_market_witness_payload(as_of, selected, local_bars, remote)
    except Exception as exc:
        payload = build_market_witness_payload(as_of, selected, local_bars, {})
        payload["status"] = "FETCH_ERROR"
        payload["error_type"] = exc.__class__.__name__
        payload["error"] = str(exc)
    return write_market_witness(resolve_path(config, "archive_dir"), payload)


def market_witness_symbols(config: dict[str, Any]) -> list[str]:
    symbols = set(str(symbol) for symbol in (config.get("symbols") or {}))
    symbols.update(str(symbol) for symbol in (config.get("market_symbols") or []))
    for group in ("radars", "component_proxies"):
        for values in (config.get(group) or {}).values():
            symbols.update(str(symbol) for symbol in values)
    symbols.update({"QQQ", "SPY", "BRK.B", "BOXX", "DBMF", "BIL", "SHV"})
    return sorted(symbols)


def write_market_witness(archive_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    archive = Path(archive_dir)
    archive.mkdir(parents=True, exist_ok=True)
    as_of = str(payload.get("as_of") or "")[:10]
    if not as_of:
        raise ValueError("market witness payload missing as_of")
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    exact = archive / f"market_witness_{as_of}.json"
    latest = archive / "market_witness_latest.json"
    for path in (exact, latest):
        temp = path.with_name(f".{path.name}.tmp")
        temp.write_text(encoded, encoding="utf-8")
        temp.replace(path)
    out = dict(payload)
    out["cache_path"] = str(exact)
    return out


def _load_local_bars(
    config: dict[str, Any], symbols: Iterable[str], as_of: str
) -> dict[str, dict[str, Any]]:
    store = LocalStore(config)
    day = pd.Timestamp(str(as_of)[:10])
    out: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        frame = store.load_history(symbol)
        if frame.empty or day not in frame.index:
            continue
        row = frame.loc[day]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[-1]
        out[str(symbol).upper()] = {
            "date": day.date().isoformat(),
            "open": _number(row.get("Open")),
            "high": _number(row.get("High")),
            "low": _number(row.get("Low")),
            "close": _number(row.get("Close")),
            "volume": _number(row.get("Volume")),
        }
    return out


def _compare_bar(
    local: Mapping[str, Any] | None,
    witness: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not local:
        return {
            "status": "DATE_MISMATCH",
            "supported": True,
            "reason": "canonical bar missing for as_of",
        }
    if not witness:
        return {
            "status": "NO_WITNESS",
            "supported": True,
            "reason": "Alpaca SIP returned no daily bar for as_of",
            "local_sha256": _hash_mapping(local),
        }
    local_date = str(local.get("date") or "")[:10]
    witness_date = str(witness.get("t") or "")[:10]
    if not local_date or not witness_date or local_date != witness_date:
        return {
            "status": "DATE_MISMATCH",
            "supported": True,
            "reason": f"canonical date {local_date or 'NA'} != witness date {witness_date or 'NA'}",
            "local_sha256": _hash_mapping(local),
            "witness_sha256": _hash_mapping(witness),
        }
    price_diffs = {
        field: _relative_diff_pct(local.get(field), witness.get(field[0]))
        for field in ("open", "high", "low", "close")
    }
    finite_price_diffs = [value for value in price_diffs.values() if value is not None]
    max_price_diff = max(finite_price_diffs) if finite_price_diffs else None
    volume_diff = _relative_diff_pct(local.get("volume"), witness.get("v"))
    if max_price_diff is None:
        status = "PRICE_MISMATCH"
        reason = "comparable OHLC fields unavailable"
    elif max_price_diff > PRICE_WARN_PCT:
        status = "PRICE_MISMATCH"
        reason = "raw OHLC difference exceeds witness policy"
    elif volume_diff is not None and volume_diff > VOLUME_WARN_PCT:
        status = "VOLUME_MISMATCH"
        reason = "raw volume difference exceeds witness policy"
    else:
        status = "MATCH"
        reason = "raw OHLC and volume agree within witness policy"
    return {
        "status": status,
        "supported": True,
        "reason": reason,
        "warning_band": bool(
            (max_price_diff is not None and max_price_diff > PRICE_MATCH_PCT)
            or (volume_diff is not None and volume_diff > VOLUME_MATCH_PCT)
        ),
        "close_diff_pct": price_diffs.get("close"),
        "max_ohlc_diff_pct": max_price_diff,
        "volume_diff_pct": volume_diff,
        "local_sha256": _hash_mapping(local),
        "witness_sha256": _hash_mapping(witness),
    }


def _is_supported(symbol: Any) -> bool:
    return bool(_US_EQUITY_SYMBOL.fullmatch(str(symbol or "").upper()))


def _relative_diff_pct(left: Any, right: Any) -> float | None:
    a = _number(left)
    b = _number(right)
    if a is None or b is None or b == 0:
        return None
    return round(abs(a - b) / abs(b) * 100.0, 4)


def _number(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if pd.notna(out) else None


def _hash_mapping(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(value), sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
