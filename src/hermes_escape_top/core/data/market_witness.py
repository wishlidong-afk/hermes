from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode

import pandas as pd

from ...config import resolve_path
from .alpaca_flow import DATA_URL, _request_json, load_alpaca_credentials
from .store import LocalStore


SCHEMA_VERSION = "hermes-market-witness-v1"
RAW_COMPARISON_SCHEMA_VERSION = "hermes-market-bar-comparison-evidence-v1"
YAHOO_CANDIDATE_SOURCE = "YAHOO_FINANCE_1DAY"
ALPACA_WITNESS_SOURCE = "ALPACA_SIP_1DAY"
PRICE_MATCH_PCT = 0.5
PRICE_WARN_PCT = 1.0
VOLUME_MATCH_PCT = 10.0
VOLUME_WARN_PCT = 25.0
# Free historical SIP requires end >=15 minutes old; keep 5 minutes for clock skew.
FREE_SIP_QUERY_DELAY = timedelta(minutes=20)
_US_EQUITY_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")


def market_witness_policy() -> dict[str, Any]:
    return {
        "price_match_pct": PRICE_MATCH_PCT,
        "price_warn_pct": PRICE_WARN_PCT,
        "volume_match_pct": VOLUME_MATCH_PCT,
        "volume_warn_pct": VOLUME_WARN_PCT,
        "admission_mode": "FAIL_CLOSED",
    }


def fetch_alpaca_daily_bars(
    symbols: Iterable[str],
    as_of: str,
    credentials: Mapping[str, str],
    *,
    request_json: Callable[[str, Mapping[str, str]], dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    day = date.fromisoformat(str(as_of)[:10])
    return fetch_alpaca_daily_bar_range(
        symbols,
        day.isoformat(),
        (day + timedelta(days=1)).isoformat(),
        credentials,
        request_json=request_json,
    )


def fetch_alpaca_daily_bar_range(
    symbols: Iterable[str],
    start: str,
    end: str,
    credentials: Mapping[str, str],
    *,
    request_json: Callable[[str, Mapping[str, str]], dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, list[dict[str, Any]]]:
    ordered = sorted({str(symbol).upper() for symbol in symbols if is_alpaca_supported_symbol(symbol)})
    if not ordered:
        return {}
    start_day = date.fromisoformat(str(start)[:10])
    end_day = date.fromisoformat(str(end)[:10])
    if end_day <= start_day:
        raise ValueError("Alpaca daily bar range end must be after start")
    requested_end = datetime.combine(end_day, datetime.min.time(), tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    safe_end = current.astimezone(timezone.utc) - FREE_SIP_QUERY_DELAY
    effective_end = min(requested_end, safe_end).replace(microsecond=0)
    start_at = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc)
    if effective_end <= start_at:
        raise ValueError("Alpaca daily bar range has no safely queryable SIP window")
    params = {
        "symbols": ",".join(ordered),
        "timeframe": "1Day",
        "start": f"{start_day.isoformat()}T00:00:00Z",
        "end": effective_end.isoformat().replace("+00:00", "Z"),
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
    seen_page_tokens: set[str] = set()
    page_count = 0
    while True:
        page_count += 1
        if page_count > 100:
            raise RuntimeError("Alpaca daily bars exceeded 100 pages")
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
        page_token = str(page_token)
        if page_token in seen_page_tokens:
            raise RuntimeError("Alpaca daily bars returned a repeated page token")
        seen_page_tokens.add(page_token)


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
        if not is_alpaca_supported_symbol(symbol):
            rows[symbol] = {
                "status": "NO_WITNESS",
                "supported": False,
                "reason": "symbol is not supported by Alpaca US equities SIP",
            }
            continue
        local = local_bars.get(symbol)
        remote = list(witness_bars.get(symbol) or [])
        rows[symbol] = compare_market_bar(local, remote[-1] if remote else None)

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


def market_admission_field_inventory(config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Describe decision-relevant fields without changing admission behavior.

    The inventory is research evidence for the 30-session field-aware review.
    Production admission remains full-row fail-closed. Symbols used by scoring
    or component-flow calculations conservatively require OHLCV; routing and
    execution-reference symbols require a coherent OHLC price bar even when
    their current decision path consumes only close-derived values.
    """

    trade_symbols = {str(symbol).upper() for symbol in (config.get("symbols") or {})}
    component_symbols = {
        str(symbol).upper()
        for values in (config.get("component_proxies") or {}).values()
        for symbol in values
    }
    full_ohlcv = trade_symbols | component_symbols | {"QQQ"}
    routing = config.get("routing") or {}
    defcon1 = routing.get("defcon1") or {}
    defcon2 = routing.get("defcon2") or {}
    defcon3 = routing.get("defcon3") or {}
    route_destinations = {
        str(symbol).upper()
        for symbol in defcon3.values()
        if symbol
    }
    route_destinations.update(
        str(symbol).upper()
        for symbol, weight in defcon1.items()
        if symbol not in {"TREND", "trend_symbol", "extra_legs"}
        and isinstance(weight, (int, float))
    )
    if defcon1.get("trend_symbol"):
        route_destinations.add(str(defcon1["trend_symbol"]).upper())
    route_destinations.update(
        str(symbol).upper() for symbol in (defcon1.get("extra_legs") or {})
    )
    route_destinations.update(
        str(defcon2.get(key)).upper()
        for key in ("primary", "fallback")
        if defcon2.get(key)
    )

    inventory: dict[str, dict[str, Any]] = {}
    for raw_symbol in market_witness_symbols(dict(config)):
        symbol = str(raw_symbol).upper()
        roles: list[str] = []
        if symbol in trade_symbols:
            roles.append("scored_symbol")
        if symbol in component_symbols:
            roles.append("component_flow")
        if symbol == "QQQ":
            roles.append("macro_and_flow_context")
        if symbol == str(defcon2.get("primary") or "").upper():
            roles.append("defcon2_route")
        elif symbol in route_destinations:
            roles.append("capital_route")
        if symbol in route_destinations:
            roles.append("execution_reference")
        if not roles:
            roles.append("market_context")

        if symbol == "BTC-USD":
            channel = "coinbase_spot"
        elif is_alpaca_supported_symbol(symbol):
            channel = "alpaca_sip"
        else:
            channel = "not_applicable"
        volume_required = symbol in full_ohlcv
        inventory[symbol] = {
            "admission_channel": channel,
            "decision_fields": (
                ["open", "high", "low", "close", "volume"]
                if volume_required
                else ["close"]
            ),
            "certification_fields": (
                ["open", "high", "low", "close", "volume"]
                if volume_required
                else ["open", "high", "low", "close"]
            ),
            "volume_required": volume_required,
            "roles": roles,
        }
    return inventory


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
        _atomic_write_text(path, encoded)
    out = dict(payload)
    out["cache_path"] = str(exact)
    return out


def _atomic_write_text(path: Path, content: str) -> None:
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, temp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        temp.chmod(mode)
        temp.replace(path)
    except BaseException:
        try:
            temp.unlink()
        except OSError:
            pass
        raise


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


def compare_market_bar(
    local: Mapping[str, Any] | None,
    witness: Mapping[str, Any] | None,
    *,
    require_complete: bool = False,
) -> dict[str, Any]:
    if not local:
        return _attach_raw_comparison(
            {
                "status": "DATE_MISMATCH",
                "supported": True,
                "reason": "canonical bar missing for as_of",
            },
            local,
            witness,
        )
    if not witness:
        return _attach_raw_comparison(
            {
                "status": "NO_WITNESS",
                "supported": True,
                "reason": "Alpaca SIP returned no daily bar for as_of",
                "local_sha256": _hash_mapping(local),
            },
            local,
            witness,
        )
    local_date = str(local.get("date") or "")[:10]
    witness_date = str(witness.get("t") or "")[:10]
    if not local_date or not witness_date or local_date != witness_date:
        return _attach_raw_comparison(
            {
                "status": "DATE_MISMATCH",
                "supported": True,
                "reason": f"canonical date {local_date or 'NA'} != witness date {witness_date or 'NA'}",
                "local_sha256": _hash_mapping(local),
                "witness_sha256": _hash_mapping(witness),
            },
            local,
            witness,
        )
    price_diffs = {
        field: _relative_diff_pct(local.get(field), witness.get(field[0]))
        for field in ("open", "high", "low", "close")
    }
    finite_price_diffs = [value for value in price_diffs.values() if value is not None]
    max_price_diff = max(finite_price_diffs) if finite_price_diffs else None
    volume_diff = _relative_diff_pct(local.get("volume"), witness.get("v"))
    price_evidence_status = _evidence_band(
        max_price_diff,
        match_pct=PRICE_MATCH_PCT,
        warn_pct=PRICE_WARN_PCT,
    )
    if require_complete and len(finite_price_diffs) != 4:
        price_evidence_status = "MISSING"
    volume_evidence_status = _evidence_band(
        volume_diff,
        match_pct=VOLUME_MATCH_PCT,
        warn_pct=VOLUME_WARN_PCT,
    )
    if require_complete and len(finite_price_diffs) != 4:
        status = "PRICE_MISMATCH"
        reason = "all raw OHLC fields must be comparable"
    elif max_price_diff is None:
        status = "PRICE_MISMATCH"
        reason = "comparable OHLC fields unavailable"
    elif max_price_diff > PRICE_WARN_PCT:
        status = "PRICE_MISMATCH"
        reason = "raw OHLC difference exceeds witness policy"
    elif require_complete and volume_diff is None:
        status = "VOLUME_MISMATCH"
        reason = "raw volume must be comparable"
    elif volume_diff is not None and volume_diff > VOLUME_WARN_PCT:
        status = "VOLUME_MISMATCH"
        reason = "raw volume difference exceeds witness policy"
    else:
        status = "MATCH"
        reason = "raw OHLC and volume agree within witness policy"
    result = {
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
        "price_evidence_status": price_evidence_status,
        "volume_evidence_status": volume_evidence_status,
        "policy": market_witness_policy(),
        "local_sha256": _hash_mapping(local),
        "witness_sha256": _hash_mapping(witness),
    }
    return _attach_raw_comparison(result, local, witness)


def normalize_yahoo_candidate_bar(
    value: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not value:
        return None
    return {
        "date": str(value.get("date") or "")[:10] or None,
        "open": _number(value.get("open")),
        "high": _number(value.get("high")),
        "low": _number(value.get("low")),
        "close": _number(value.get("close")),
        "volume": _number(value.get("volume")),
    }


def normalize_alpaca_witness_bar(
    value: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not value:
        return None
    timestamp = str(value.get("t") or "") or None
    return {
        "date": timestamp[:10] if timestamp else None,
        "timestamp": timestamp,
        "open": _number(value.get("o")),
        "high": _number(value.get("h")),
        "low": _number(value.get("l")),
        "close": _number(value.get("c")),
        "volume": _number(value.get("v")),
    }


def _attach_raw_comparison(
    result: dict[str, Any],
    local: Mapping[str, Any] | None,
    witness: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if result.get("status") == "MATCH":
        return result
    candidate_bar = normalize_yahoo_candidate_bar(local)
    witness_bar = normalize_alpaca_witness_bar(witness)
    result["raw_comparison"] = {
        "schema_version": RAW_COMPARISON_SCHEMA_VERSION,
        "candidate": {
            "source": YAHOO_CANDIDATE_SOURCE,
            "auto_adjust": False,
            "bar": candidate_bar,
            "sha256": _hash_mapping(candidate_bar) if candidate_bar else None,
        },
        "witness": {
            "source": ALPACA_WITNESS_SOURCE,
            "source_url": DATA_URL,
            "timeframe": "1Day",
            "feed": "sip",
            "adjustment": "raw",
            "bar": witness_bar,
            "sha256": _hash_mapping(witness_bar) if witness_bar else None,
        },
    }
    return result


def _evidence_band(
    value: float | None,
    *,
    match_pct: float,
    warn_pct: float,
) -> str:
    if value is None:
        return "MISSING"
    if value > warn_pct:
        return "MISMATCH"
    if value > match_pct:
        return "WARNING_BAND"
    return "MATCH"


def is_alpaca_supported_symbol(symbol: Any) -> bool:
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
