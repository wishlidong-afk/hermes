from __future__ import annotations

import argparse
import json
import math
import os
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ...config import load_config, resolve_path
from .store import LocalStore


SCHEMA_VERSION = "alpaca-sip-daily-flow-v1"
DATA_URL = "https://data.alpaca.markets/v2/stocks/bars"
DEFAULT_CREDENTIALS_PATH = Path("~/.hermes/secrets/alpaca.env").expanduser()
REGULAR_SESSION_MINUTES = 390


class AlpacaFlowError(RuntimeError):
    pass


def load_alpaca_credentials(path: Optional[Path] = None) -> Dict[str, str]:
    key = os.environ.get("APCA_API_KEY_ID", "").strip()
    secret = os.environ.get("APCA_API_SECRET_KEY", "").strip()
    if key and secret:
        return {"key": key, "secret": secret}

    values: Dict[str, str] = {}
    credentials_path = path or Path(os.environ.get("ALPACA_CREDENTIALS_FILE", DEFAULT_CREDENTIALS_PATH))
    try:
        for raw_line in credentials_path.expanduser().read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip().strip("'\"")
    except OSError as exc:
        raise AlpacaFlowError(f"Alpaca credentials unavailable: {credentials_path}") from exc

    key = values.get("APCA_API_KEY_ID", "")
    secret = values.get("APCA_API_SECRET_KEY", "")
    if not key or not secret:
        raise AlpacaFlowError(f"Alpaca credentials incomplete: {credentials_path}")
    return {"key": key, "secret": secret}


def fetch_sip_minute_bars(
    symbols: Iterable[str],
    as_of: str,
    credentials: Mapping[str, str],
    request_json: Optional[Callable[[str, Mapping[str, str]], Dict[str, Any]]] = None,
) -> Dict[str, list[Dict[str, Any]]]:
    ordered_symbols = sorted({str(symbol).upper() for symbol in symbols if str(symbol).strip()})
    if not ordered_symbols:
        return {}
    start, end = _regular_session_utc(as_of)
    params = {
        "symbols": ",".join(ordered_symbols),
        "timeframe": "1Min",
        "start": start,
        "end": end,
        "limit": "10000",
        "feed": "sip",
        "adjustment": "raw",
        "sort": "asc",
    }
    headers = {
        "APCA-API-KEY-ID": str(credentials.get("key", "")),
        "APCA-API-SECRET-KEY": str(credentials.get("secret", "")),
        "Accept": "application/json",
        "User-Agent": "Hermes-Alpaca-Flow/1.0",
    }
    transport = request_json or _request_json
    result: Dict[str, list[Dict[str, Any]]] = {symbol: [] for symbol in ordered_symbols}
    page_token: Optional[str] = None
    while True:
        query = dict(params)
        if page_token:
            query["page_token"] = page_token
        payload = transport(f"{DATA_URL}?{urlencode(query)}", headers)
        for symbol, rows in (payload.get("bars") or {}).items():
            if symbol in result and isinstance(rows, list):
                result[symbol].extend(row for row in rows if isinstance(row, dict))
        page_token = payload.get("next_page_token")
        if not page_token:
            return result


def estimate_symbol_flow(symbol: str, bars: Iterable[Mapping[str, Any]], as_of: str) -> Dict[str, Any]:
    buy_notional = 0.0
    sell_notional = 0.0
    trade_count = 0
    accepted = []
    previous_close: Optional[float] = None
    for bar in bars:
        volume = _number(bar.get("v"))
        vwap = _number(bar.get("vw"))
        open_price = _number(bar.get("o"))
        high = _number(bar.get("h"))
        low = _number(bar.get("l"))
        close = _number(bar.get("c"))
        if volume is None or volume <= 0 or close is None:
            continue
        reference_price = vwap if vwap is not None and vwap > 0 else close
        total = reference_price * volume
        multiplier = _bar_flow_multiplier(open_price, high, low, close, previous_close)
        buy_notional += total * (1.0 + multiplier) / 2.0
        sell_notional += total * (1.0 - multiplier) / 2.0
        trade_count += int(_number(bar.get("n")) or 0)
        accepted.append(bar)
        previous_close = close

    total_notional = buy_notional + sell_notional
    net_notional = buy_notional - sell_notional
    buy_share = buy_notional / total_notional if total_notional > 0 else None
    net_share = net_notional / total_notional if total_notional > 0 else None
    return {
        "symbol": symbol,
        "as_of": str(as_of)[:10],
        "buy_notional": buy_notional,
        "sell_notional": sell_notional,
        "net_notional": net_notional,
        "total_notional": total_notional,
        "buy_share": buy_share,
        "net_share": net_share,
        "bar_count": len(accepted),
        "coverage": min(1.0, len(accepted) / REGULAR_SESSION_MINUTES),
        "trade_count": trade_count,
        "first_bar": accepted[0].get("t") if accepted else None,
        "last_bar": accepted[-1].get("t") if accepted else None,
        "direction": _flow_direction(net_share),
    }


def build_daily_flow_payload(
    as_of: str,
    baskets: Mapping[str, Iterable[str]],
    bars_by_symbol: Mapping[str, Iterable[Mapping[str, Any]]],
) -> Dict[str, Any]:
    normalized_baskets = {basket: list(members) for basket, members in baskets.items()}
    symbols = sorted({symbol for members in normalized_baskets.values() for symbol in members})
    symbol_rows = {
        symbol: estimate_symbol_flow(symbol, bars_by_symbol.get(symbol, []), as_of)
        for symbol in symbols
    }
    if not any(row["bar_count"] > 0 for row in symbol_rows.values()):
        raise AlpacaFlowError(f"Alpaca SIP returned no regular-session bars for {str(as_of)[:10]}")
    basket_rows: Dict[str, Any] = {}
    for basket, members in normalized_baskets.items():
        components = [symbol_rows[symbol] for symbol in members if symbol in symbol_rows]
        available = [row for row in components if row["bar_count"] > 0]
        buy = sum(row["buy_notional"] for row in available)
        sell = sum(row["sell_notional"] for row in available)
        total = buy + sell
        net = buy - sell
        net_share = net / total if total > 0 else None
        basket_rows[basket] = {
            "symbol": basket,
            "as_of": str(as_of)[:10],
            "buy_notional": buy,
            "sell_notional": sell,
            "net_notional": net,
            "total_notional": total,
            "buy_share": buy / total if total > 0 else None,
            "net_share": net_share,
            "direction": _flow_direction(net_share),
            "component_count": len(available),
            "requested_component_count": len(members),
            "components": components,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": str(as_of)[:10],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "ALPACA_SIP_1MIN",
        "methodology": (
            "SIP 1-minute VWAP x volume is observed turnover; buy/sell split is estimated "
            "from each minute close location within its high-low range, with open/tick fallback."
        ),
        "symbols": symbol_rows,
        "baskets": basket_rows,
    }


def refresh_daily_flow(as_of: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = config or load_config()
    day = _resolve_as_of(as_of, cfg)
    baskets = {
        "MSTR": ["MSTR"],
        **{
            basket: [str(symbol).upper() for symbol in members]
            for basket, members in (cfg.get("component_proxies") or {}).items()
        },
    }
    credentials = load_alpaca_credentials()
    symbols = {symbol for members in baskets.values() for symbol in members}
    bars = fetch_sip_minute_bars(symbols, day, credentials)
    payload = build_daily_flow_payload(day, baskets, bars)
    return write_daily_flow_snapshot(resolve_path(cfg, "archive_dir"), payload)


def write_daily_flow_snapshot(archive_dir: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    day = str(payload.get("as_of", ""))[:10]
    if not day:
        raise AlpacaFlowError("daily flow payload missing as_of")
    exact_path = archive_dir / f"alpaca_daily_flow_{day}.json"
    latest_path = archive_dir / "alpaca_daily_flow_latest.json"
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    for path in (exact_path, latest_path):
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(encoded, encoding="utf-8")
        temp_path.replace(path)
    out = dict(payload)
    out["cache_path"] = str(exact_path)
    return out


def load_daily_flow_snapshot(archive_dir: Path, as_of: str) -> Optional[Dict[str, Any]]:
    target = str(as_of or "")[:10]
    candidates = []
    if target:
        exact = archive_dir / f"alpaca_daily_flow_{target}.json"
        if exact.exists():
            candidates.append(exact)
        candidates.extend(
            path for path in sorted(archive_dir.glob("alpaca_daily_flow_????-??-??.json"), reverse=True)
            if path.stem.rsplit("_", 1)[-1] <= target and path not in candidates
        )
    else:
        candidates.append(archive_dir / "alpaca_daily_flow_latest.json")
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("schema_version") != SCHEMA_VERSION:
            continue
        out = dict(payload)
        out["cache_path"] = str(path)
        out["requested_as_of"] = target or "latest"
        return out
    return None


def _regular_session_utc(as_of: str) -> tuple[str, str]:
    day = date.fromisoformat(str(as_of)[:10])
    eastern = ZoneInfo("America/New_York")
    start = datetime.combine(day, time(9, 30), eastern).astimezone(timezone.utc)
    end = datetime.combine(day, time(16, 0), eastern).astimezone(timezone.utc)
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


def _bar_flow_multiplier(
    open_price: Optional[float],
    high: Optional[float],
    low: Optional[float],
    close: float,
    previous_close: Optional[float],
) -> float:
    if high is not None and low is not None and high > low:
        return max(-1.0, min(1.0, ((close - low) - (high - close)) / (high - low)))
    reference = open_price if open_price is not None else previous_close
    if reference is None or close == reference:
        return 0.0
    return 1.0 if close > reference else -1.0


def _flow_direction(net_share: Optional[float]) -> str:
    if net_share is None:
        return "MISSING"
    if net_share >= 0.01:
        return "NET_BUY"
    if net_share <= -0.01:
        return "NET_SELL"
    return "BALANCED"


def _number(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _request_json(url: str, headers: Mapping[str, str]) -> Dict[str, Any]:
    request = Request(url, headers=dict(headers), method="GET")
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            message = json.loads(exc.read().decode("utf-8")).get("message")
        except Exception:
            message = None
        raise AlpacaFlowError(f"Alpaca SIP HTTP {exc.code}: {message or exc.reason}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AlpacaFlowError(f"Alpaca SIP request failed: {exc}") from exc


def _resolve_as_of(as_of: str, config: Dict[str, Any]) -> str:
    if str(as_of).lower() not in {"", "latest", "newest"}:
        return str(as_of)[:10]
    store = LocalStore(config)
    dates = []
    for symbol in ("MSTR", "FNGU", "SOXL"):
        frame = store.load_history(symbol)
        if frame is not None and not frame.empty:
            dates.append(frame.index[-1].date())
    if not dates:
        raise AlpacaFlowError("cannot resolve latest session from local histories")
    return min(dates).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh previous-session Alpaca SIP flow cache")
    parser.add_argument("--as-of", default="latest", help="Trading date or latest")
    args = parser.parse_args()
    payload = refresh_daily_flow(args.as_of)
    summary = {
        "ok": True,
        "as_of": payload.get("as_of"),
        "source": payload.get("source"),
        "cache_path": payload.get("cache_path"),
        "symbols": len(payload.get("symbols") or {}),
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
