from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import date
from types import MappingProxyType
from typing import Any

import pandas as pd

CFTC_TFF_DATASET_ID = "gpe5-46if"
CFTC_TFF_SOURCE_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
SUPPORTED_MARKETS = MappingProxyType({"13874A": "ES", "209742": "NQ"})
CANDIDATE_SPEC = MappingProxyType(
    {
        "candidate_id": "CFTC_TFF_ASSET_MANAGER_EQUITY_EXPOSURE",
        "status": "OFFLINE_RESEARCH_ONLY",
        "production_source_id": None,
        "production_weight": 0.0,
        "proposed_max_points": 2.0,
        "displaces": "A2_NAAIM",
        "distinct_from_rejected": "data_cot_nq",
        "source_url": CFTC_TFF_SOURCE_URL,
        "pit_requirement": "EXACT_RELEASE",
    }
)

_NORMALIZED_COLUMNS = [
    "market",
    "market_code",
    "market_name",
    "observation_date",
    "publish_date",
    "open_interest",
    "asset_manager_long",
    "asset_manager_short",
    "asset_manager_spread",
    "asset_manager_net",
    "asset_manager_net_oi_pct",
    "pit_status",
]


def normalize_tff_asset_manager_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    release_dates: Mapping[date | str, date | str] | None = None,
) -> pd.DataFrame:
    exact_releases = _normalize_release_dates(release_dates or {})
    records: list[dict[str, Any]] = []
    for raw in rows:
        market_code = str(raw.get("cftc_contract_market_code") or "").strip().upper()
        market = SUPPORTED_MARKETS.get(market_code)
        if market is None:
            continue
        observation = _parse_date(
            raw.get("report_date_as_yyyy_mm_dd"),
            field="report_date_as_yyyy_mm_dd",
        )
        publish_date = exact_releases.get(observation)
        if publish_date is None:
            raise ValueError(f"exact CFTC release date missing for {observation.isoformat()}")
        if publish_date < observation:
            raise ValueError(
                f"release date precedes observation for {observation.isoformat()}"
            )
        open_interest = _numeric(raw.get("open_interest_all"), "open interest")
        if open_interest <= 0:
            raise ValueError("open interest must be positive")
        asset_long = _position(raw.get("asset_mgr_positions_long"))
        asset_short = _position(raw.get("asset_mgr_positions_short"))
        asset_spread = _position(raw.get("asset_mgr_positions_spread"))
        asset_net = asset_long - asset_short
        records.append(
            {
                "market": market,
                "market_code": market_code,
                "market_name": str(raw.get("market_and_exchange_names") or "").strip(),
                "observation_date": observation.isoformat(),
                "publish_date": publish_date.isoformat(),
                "open_interest": open_interest,
                "asset_manager_long": asset_long,
                "asset_manager_short": asset_short,
                "asset_manager_spread": asset_spread,
                "asset_manager_net": asset_net,
                "asset_manager_net_oi_pct": asset_net / open_interest,
                "pit_status": "EXACT_RELEASE",
            }
        )
    if not records:
        raise ValueError("no supported CFTC TFF equity-index market rows")
    frame = pd.DataFrame(records, columns=_NORMALIZED_COLUMNS)
    duplicates = frame.duplicated(subset=["market_code", "observation_date"], keep=False)
    if duplicates.any():
        raise ValueError("duplicate CFTC market/date rows")
    return frame.sort_values(["observation_date", "market"]).reset_index(drop=True)


def aggregate_equity_asset_manager_exposure(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "market",
        "observation_date",
        "publish_date",
        "asset_manager_net",
        "open_interest",
        "pit_status",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError("normalized CFTC frame missing columns: " + ", ".join(missing))
    if frame.empty:
        raise ValueError("normalized CFTC frame is empty")
    if set(frame["pit_status"].astype(str)) != {"EXACT_RELEASE"}:
        raise ValueError("formal candidate rows require PIT status EXACT_RELEASE")

    records = []
    for (observation, publish_date), group in frame.groupby(
        ["observation_date", "publish_date"],
        sort=True,
    ):
        markets = sorted(set(group["market"].astype(str)))
        if markets != ["ES", "NQ"]:
            raise ValueError(
                f"equity candidate requires stable ES,NQ coverage; got {','.join(markets)}"
            )
        open_interest = float(pd.to_numeric(group["open_interest"], errors="raise").sum())
        asset_net = float(pd.to_numeric(group["asset_manager_net"], errors="raise").sum())
        if not math.isfinite(open_interest) or open_interest <= 0:
            raise ValueError("aggregate open interest must be positive")
        records.append(
            {
                "date": str(publish_date),
                "publish_date": str(publish_date),
                "observation_date": str(observation),
                "asset_manager_net": asset_net,
                "open_interest": open_interest,
                "asset_manager_net_oi_pct": round(asset_net / open_interest, 10),
                "markets_used": ",".join(markets),
                "pit_status": "EXACT_RELEASE",
            }
        )
    return pd.DataFrame(records)


def _normalize_release_dates(
    values: Mapping[date | str, date | str],
) -> dict[date, date]:
    return {
        _parse_date(observation, field="release observation date"): _parse_date(
            published,
            field="release date",
        )
        for observation, published in values.items()
    }


def _parse_date(value: Any, *, field: str) -> date:
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"{field} is invalid")
    return parsed.date()


def _numeric(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be numeric") from None
    if not math.isfinite(number):
        raise ValueError(f"{label} must be numeric")
    return number


def _position(value: Any) -> float:
    number = _numeric(value, "position fields")
    if number < 0:
        raise ValueError("position fields must be non-negative")
    return number


__all__ = [
    "CANDIDATE_SPEC",
    "CFTC_TFF_DATASET_ID",
    "CFTC_TFF_SOURCE_URL",
    "SUPPORTED_MARKETS",
    "aggregate_equity_asset_manager_exposure",
    "normalize_tff_asset_manager_rows",
]
