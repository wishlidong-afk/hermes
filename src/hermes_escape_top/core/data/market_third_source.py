from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..safe_io import atomic_write_text
from .external_sources.clock import timestamp_to_shanghai_date
from .market_witness import compare_market_bar, is_alpaca_supported_symbol


SCHEMA_VERSION = "hermes-market-admission-third-source-shadow-v1"
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
ALPHA_VANTAGE_SOURCE = "ALPHA_VANTAGE_TIME_SERIES_DAILY"
DEFAULT_CREDENTIALS_PATH = Path(
    "~/.hermes/secrets/alpha_vantage.env"
).expanduser()
_SYMBOL_MAP = {"BRK.B": "BRK-B"}
_COMPARISON_FIELDS = (
    "status",
    "reason",
    "close_diff_pct",
    "max_ohlc_diff_pct",
    "volume_diff_pct",
    "price_evidence_status",
    "volume_evidence_status",
)


class MarketThirdSourceError(RuntimeError):
    pass


def load_alpha_vantage_api_key(path: Path | None = None) -> str:
    env_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "").strip()
    if env_key:
        return env_key
    credentials_path = Path(
        os.environ.get(
            "ALPHA_VANTAGE_CREDENTIALS_FILE",
            path or DEFAULT_CREDENTIALS_PATH,
        )
    ).expanduser()
    try:
        lines = credentials_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise MarketThirdSourceError(
            f"Alpha Vantage credentials unavailable: {credentials_path}"
        ) from exc
    values: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip("'\"")
    key = values.get("ALPHA_VANTAGE_API_KEY", "")
    if not key:
        raise MarketThirdSourceError(
            f"Alpha Vantage credentials incomplete: {credentials_path}"
        )
    return key


def fetch_alpha_vantage_daily_bar(
    symbol: str,
    day: str,
    api_key: str,
    *,
    request_json: Callable[[str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    requested_symbol = str(symbol).upper()
    vendor_symbol = _SYMBOL_MAP.get(requested_symbol, requested_symbol)
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": vendor_symbol,
        "outputsize": "compact",
        "apikey": str(api_key),
    }
    url = f"{ALPHA_VANTAGE_URL}?{urlencode(params)}"
    payload = dict((request_json or _request_json)(url))
    series = payload.get("Time Series (Daily)") or {}
    raw = series.get(str(day)[:10]) if isinstance(series, Mapping) else None
    if not isinstance(raw, Mapping):
        reason = (
            payload.get("Error Message")
            or payload.get("Information")
            or payload.get("Note")
            or f"daily bar unavailable for {requested_symbol} {str(day)[:10]}"
        )
        raise MarketThirdSourceError(str(reason))
    bar = {
        "date": str(day)[:10],
        "open": _number(raw.get("1. open")),
        "high": _number(raw.get("2. high")),
        "low": _number(raw.get("3. low")),
        "close": _number(raw.get("4. close")),
        "volume": _number(raw.get("5. volume")),
    }
    if any(bar[field] is None for field in ("open", "high", "low", "close", "volume")):
        raise MarketThirdSourceError(
            f"incomplete Alpha Vantage daily bar for {requested_symbol} {str(day)[:10]}"
        )
    return {
        "source": ALPHA_VANTAGE_SOURCE,
        "source_url": ALPHA_VANTAGE_URL,
        "requested_symbol": requested_symbol,
        "vendor_symbol": vendor_symbol,
        "bar": bar,
        "bar_sha256": _hash_mapping(bar),
    }


def collect_market_admission_third_source_shadow(
    admission_payload: Mapping[str, Any],
    *,
    api_key: str | None = None,
    request_json: Callable[[str], Mapping[str, Any]] | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    candidates = [
        row
        for row in (admission_payload.get("rows") or [])
        if isinstance(row, Mapping)
        and row.get("admitted") is False
        and row.get("blocking") is not False
        and str(row.get("status") or "") in {"PRICE_MISMATCH", "VOLUME_MISMATCH"}
        and is_alpaca_supported_symbol(str(row.get("symbol") or ""))
        and isinstance((row.get("raw_comparison") or {}).get("candidate"), Mapping)
        and isinstance((row.get("raw_comparison") or {}).get("witness"), Mapping)
    ]
    requested_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in candidates:
        key = (
            str(row.get("symbol") or "").upper(),
            str(row.get("date") or "")[:10],
        )
        requested_by_key.setdefault(key, row)
    requested = list(requested_by_key.values())
    generated = fetched_at or datetime.now(timezone.utc).isoformat()
    base = {
        "schema_version": SCHEMA_VERSION,
        "research_only": True,
        "admission_operation_id": admission_payload.get("operation_id"),
        "completed_through": admission_payload.get("completed_through"),
        "fetched_at": generated,
        "requested_rows": len(requested),
        "rows": [],
    }
    if not requested:
        return {**base, "status": "NOT_NEEDED"}

    key = api_key or load_alpha_vantage_api_key()
    rows: list[dict[str, Any]] = []
    failures = 0
    for rejection in requested:
        symbol = str(rejection.get("symbol") or "").upper()
        day = str(rejection.get("date") or "")[:10]
        raw_comparison = rejection.get("raw_comparison") or {}
        candidate = ((raw_comparison.get("candidate") or {}).get("bar"))
        witness = ((raw_comparison.get("witness") or {}).get("bar"))
        try:
            third = fetch_alpha_vantage_daily_bar(
                symbol,
                day,
                key,
                request_json=request_json,
            )
            third_bar = third["bar"]
            candidate_comparison = compare_market_bar(
                candidate,
                _as_witness_bar(third_bar),
                require_complete=True,
            )
            witness_comparison = compare_market_bar(
                _as_local_bar(witness),
                _as_witness_bar(third_bar),
                require_complete=True,
            )
            rows.append(
                {
                    "symbol": symbol,
                    "date": day,
                    "admission_status_unchanged": rejection.get("status"),
                    "third_source_support": _support_label(
                        candidate_comparison,
                        witness_comparison,
                    ),
                    "candidate_vs_third": _comparison_summary(candidate_comparison),
                    "witness_vs_third": _comparison_summary(witness_comparison),
                    "third_source": third,
                }
            )
        except Exception as exc:
            failures += 1
            rows.append(
                {
                    "symbol": symbol,
                    "date": day,
                    "admission_status_unchanged": rejection.get("status"),
                    "third_source_support": "UNAVAILABLE",
                    "error_type": exc.__class__.__name__,
                    "error": _redact_error(exc, secret=key)[:240],
                }
            )
    status = "OK" if failures == 0 else "ERROR" if failures == len(rows) else "PARTIAL"
    return {**base, "status": status, "rows": rows}


def write_market_admission_third_source_shadow(
    archive_dir: Path,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    archive = Path(archive_dir)
    archive.mkdir(parents=True, exist_ok=True)
    operating_day = timestamp_to_shanghai_date(payload.get("fetched_at"))
    if operating_day is None:
        raise ValueError("third-source shadow payload missing fetched_at")
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    exact = archive / f"market_admission_third_source_{operating_day.isoformat()}.json"
    latest = archive / "market_admission_third_source_latest.json"
    atomic_write_text(exact, encoded)
    atomic_write_text(latest, encoded)
    return {**dict(payload), "cache_path": str(exact)}


def _support_label(
    candidate_comparison: Mapping[str, Any],
    witness_comparison: Mapping[str, Any],
) -> str:
    candidate_match = str(candidate_comparison.get("status") or "") == "MATCH"
    witness_match = str(witness_comparison.get("status") or "") == "MATCH"
    if witness_match and not candidate_match:
        return "ALPACA_WITNESS"
    if candidate_match and not witness_match:
        return "YAHOO_CANDIDATE"
    if candidate_match and witness_match:
        return "BOTH_WITHIN_POLICY"
    return "NEITHER_WITHIN_POLICY"


def _comparison_summary(comparison: Mapping[str, Any]) -> dict[str, Any]:
    return {field: comparison.get(field) for field in _COMPARISON_FIELDS}


def _as_witness_bar(bar: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "t": f"{str(bar.get('date') or '')[:10]}T00:00:00Z",
        "o": bar.get("open"),
        "h": bar.get("high"),
        "l": bar.get("low"),
        "c": bar.get("close"),
        "v": bar.get("volume"),
    }


def _as_local_bar(bar: Mapping[str, Any] | None) -> dict[str, Any]:
    value = bar or {}
    return {
        "date": str(value.get("date") or "")[:10],
        "open": value.get("open"),
        "high": value.get("high"),
        "low": value.get("low"),
        "close": value.get("close"),
        "volume": value.get("volume"),
    }


def _request_json(url: str) -> Mapping[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Hermes-Market-Third-Source/1.0",
        },
    )
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number == number else None
    except (TypeError, ValueError):
        return None


def _hash_mapping(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _redact_error(exc: BaseException, *, secret: str) -> str:
    message = str(exc)
    if secret:
        message = message.replace(secret, "[REDACTED]")
    return re.sub(
        r"(?i)(apikey=)[^&\s]+",
        r"\1[REDACTED]",
        message,
    )
