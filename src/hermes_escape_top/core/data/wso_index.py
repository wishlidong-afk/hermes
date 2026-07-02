from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional

import pandas as pd


WSO_INDEX_SPECS: Dict[str, Dict[str, Any]] = {
    "FANG3X": {
        "instrument_id": "341241317",
        "market_id": "98",
        "url_slug": "nyse-fang-daily-3x-leveraged-index",
        "name": "NYSE FANG+ Daily 3x Leveraged Index",
    },
    "FANGT3X": {
        "instrument_id": "341241323",
        "market_id": "98",
        "url_slug": "nyse-fang-daily-3x-leveraged-index-total-return",
        "name": "NYSE FANG+ Daily 3x Leveraged Index (Total Return)",
    },
}


@dataclass(frozen=True)
class WsoIndexFetchResult:
    symbol: str
    source: str
    frame: pd.DataFrame


HttpGet = Callable[[str, Dict[str, str], Dict[str, str]], Dict[str, Any]]


def parse_wso_chart_payload(payload: Dict[str, Any], symbol: str) -> pd.DataFrame:
    """Parse wallstreetONLINE highstock payload into an OHLCV history frame.

    The payload stores exchange dates as Unix timestamps near the end of the
    European session. Adding a few hours rolls those stamps to the intended US
    market date without depending on local machine timezone settings.
    """

    rows = []
    for raw in payload.get("data", []) or []:
        if not isinstance(raw, list) or len(raw) < 7 or raw[4] is None:
            continue
        day = (pd.to_datetime(int(raw[6]), unit="s") + pd.Timedelta(hours=6)).normalize()
        rows.append(
            {
                "Date": day,
                "Open": raw[1],
                "High": raw[2],
                "Low": raw[3],
                "Close": raw[4],
                "Adj Close": raw[4],
                "Volume": raw[5] or 0,
                "source": "wallstreet_online_ice_index",
                "symbol": symbol,
            }
        )
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).dropna(subset=["Date"]).set_index("Date").sort_index()
    out = out[~out.index.duplicated(keep="last")]
    for col in ["Open", "High", "Low", "Close", "Adj Close", "Volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def fetch_wso_index(symbol: str, http_get: Optional[HttpGet] = None) -> WsoIndexFetchResult:
    spec = WSO_INDEX_SPECS[symbol]
    getter = http_get or _requests_json
    params = {
        "q[instId]": str(spec["instrument_id"]),
        "q[marketId]": str(spec["market_id"]),
        "q[mode]": "hist",
        "q[ts]": str(int(pd.Timestamp.now(tz="UTC").timestamp()) // 60 * 60),
    }
    referer = f"https://www.wallstreet-online.de/indizes/{spec['url_slug']}"
    payload = getter(
        "https://www.wallstreet-online.de/_rpc/json/instrument/chartdata/loadRawData",
        params,
        {"User-Agent": "Mozilla/5.0", "Referer": referer},
    )
    frame = parse_wso_chart_payload(payload, symbol)
    return WsoIndexFetchResult(symbol=symbol, source=referer, frame=frame)


def available_wso_indices() -> Iterable[str]:
    return WSO_INDEX_SPECS.keys()


def _requests_json(url: str, params: Dict[str, str], headers: Dict[str, str]) -> Dict[str, Any]:
    import requests  # type: ignore

    response = requests.get(url, params=params, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()
