from __future__ import annotations

import hashlib
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


COINBASE_CANDLES_URL = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
COINBASE_SOURCE = "COINBASE_EXCHANGE_BTC_USD_1DAY"
MAX_CANDLES_PER_REQUEST = 299
PRICE_MATCH_PCT = 0.5
PRICE_WARN_PCT = 1.0

RequestJson = Callable[[str, Mapping[str, str]], Any]


def latest_completed_utc_day(now: datetime | None = None) -> date:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).date() - timedelta(days=1)


def fetch_coinbase_daily_bar_range(
    start: str,
    end: str,
    *,
    request_json: RequestJson | None = None,
) -> dict[str, Any]:
    start_day = date.fromisoformat(str(start)[:10])
    end_day = date.fromisoformat(str(end)[:10])
    if end_day <= start_day:
        raise ValueError("Coinbase daily bar range end must be after start")

    transport = request_json or _request_json
    headers = {
        "Accept": "application/json",
        "User-Agent": "Hermes-BTC-Spot-Witness/1.0",
    }
    requests: list[dict[str, Any]] = []
    rows_by_date: dict[str, dict[str, Any]] = {}
    chunk_start = start_day
    while chunk_start < end_day:
        chunk_end = min(end_day, chunk_start + timedelta(days=MAX_CANDLES_PER_REQUEST))
        params = {
            "granularity": "86400",
            "start": f"{chunk_start.isoformat()}T00:00:00Z",
            "end": f"{chunk_end.isoformat()}T00:00:00Z",
        }
        url = f"{COINBASE_CANDLES_URL}?{urlencode(params)}"
        payload = transport(url, headers)
        if not isinstance(payload, list):
            raise ValueError("Coinbase candles response must be a list")
        stable = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        requests.append(
            {
                "url": url,
                "start": chunk_start.isoformat(),
                "end": chunk_end.isoformat(),
                "row_count": len(payload),
                "content_sha256": hashlib.sha256(stable.encode("utf-8")).hexdigest(),
            }
        )
        for raw in payload:
            normalized = _normalize_candle(raw)
            if normalized is None:
                continue
            day = str(normalized["t"])[:10]
            if start_day.isoformat() <= day < end_day.isoformat():
                rows_by_date[day] = normalized
        chunk_start = chunk_end

    return {
        "source": COINBASE_SOURCE,
        "source_url": COINBASE_CANDLES_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "requested_start": start_day.isoformat(),
        "requested_end": end_day.isoformat(),
        "requests": requests,
        "bars": [rows_by_date[day] for day in sorted(rows_by_date)],
    }


def compare_btc_spot_close(
    local: Mapping[str, Any] | None,
    witness: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not local:
        return {
            "status": "DATE_MISMATCH",
            "supported": True,
            "reason": "Yahoo BTC candidate is missing",
        }
    if not witness:
        return {
            "status": "NO_WITNESS",
            "supported": True,
            "reason": "Coinbase Exchange returned no completed BTC-USD daily candle",
            "local_sha256": _hash_mapping(local),
        }
    local_date = str(local.get("date") or "")[:10]
    witness_date = str(witness.get("t") or "")[:10]
    if not local_date or not witness_date or local_date != witness_date:
        return {
            "status": "DATE_MISMATCH",
            "supported": True,
            "reason": (
                f"Yahoo BTC date {local_date or 'NA'} != "
                f"Coinbase date {witness_date or 'NA'}"
            ),
            "local_sha256": _hash_mapping(local),
            "witness_sha256": _hash_mapping(witness),
        }
    close_diff = _relative_diff_pct(local.get("close"), witness.get("c"))
    if close_diff is None:
        status = "PRICE_MISMATCH"
        reason = "Yahoo and Coinbase BTC closes must both be numeric"
    elif close_diff > PRICE_WARN_PCT:
        status = "PRICE_MISMATCH"
        reason = "Yahoo BTC close differs from Coinbase by more than 1.0%"
    else:
        status = "MATCH"
        reason = "Yahoo BTC close agrees with Coinbase completed UTC-day close"
    return {
        "status": status,
        "supported": True,
        "reason": reason,
        "warning_band": bool(close_diff is not None and close_diff > PRICE_MATCH_PCT),
        "close_diff_pct": close_diff,
        "local_sha256": _hash_mapping(local),
        "witness_sha256": _hash_mapping(witness),
    }


def _normalize_candle(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) < 6:
        return None
    try:
        timestamp = datetime.fromtimestamp(float(raw[0]), timezone.utc)
        low, high, open_, close, volume = (float(value) for value in raw[1:6])
    except (TypeError, ValueError, OSError, OverflowError):
        return None
    values = (low, high, open_, close, volume)
    if not all(pd.notna(value) for value in values):
        return None
    return {
        "t": timestamp.strftime("%Y-%m-%dT00:00:00Z"),
        "o": open_,
        "h": high,
        "l": low,
        "c": close,
        "v": volume,
    }


def _request_json(url: str, headers: Mapping[str, str]) -> Any:
    request = Request(url, headers=dict(headers), method="GET")
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code not in {408, 429, 500, 502, 503, 504} or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(float(2**attempt))
    raise RuntimeError("unreachable Coinbase retry state")


def _relative_diff_pct(left: Any, right: Any) -> float | None:
    try:
        a = float(left)
        b = float(right)
    except (TypeError, ValueError):
        return None
    if not pd.notna(a) or not pd.notna(b) or b == 0:
        return None
    return round(abs(a - b) / abs(b) * 100.0, 4)


def _hash_mapping(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(value), sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
