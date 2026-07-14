from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from ..risk_signals import _last_percentile
from .registry import ExternalSourceSpec


FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_VINTAGE_DATES_URL = "https://api.stlouisfed.org/fred/series/vintagedates"

_EVENT_COLUMNS = (
    "series_id",
    "observation_date",
    "realtime_start",
    "vintage_date",
    "value",
    "is_missing",
    "fetched_at",
    "source_url",
    "response_sha256",
)
_DEFAULT_SERIES_STARTS = {
    "DTWEXBGS": "1990-01-01",
    "DFII10": "1990-01-01",
    "WALCL": "2015-01-01",
    "WTREGEN": "2015-01-01",
    "RRPONTSYD": "2015-01-01",
}

RequestJson = Callable[[str, Mapping[str, str]], Any]


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _request_json(endpoint: str, params: Mapping[str, str]) -> tuple[Any, bytes]:
    url = endpoint + "?" + urlencode(params)
    request = Request(url, headers={"User-Agent": "Hermes/1.0 FRED-vintage-PIT"})
    with urlopen(request, timeout=45) as response:
        body = response.read()
    return json.loads(body.decode("utf-8")), body


def _payload_and_bytes(result: Any) -> tuple[Any, bytes]:
    if isinstance(result, tuple) and len(result) == 2:
        payload, body = result
        if not isinstance(body, bytes):
            raise TypeError("FRED response body must be bytes")
        return payload, body
    return result, _canonical_json_bytes(result)


def _date_chunks(start: str, end: str) -> list[tuple[str, str]]:
    cursor = pd.Timestamp(start).normalize()
    final = pd.Timestamp(end).normalize()
    chunks: list[tuple[str, str]] = []
    while cursor <= final:
        chunk_end = min(cursor + pd.DateOffset(years=4) - pd.Timedelta(days=1), final)
        chunks.append((cursor.date().isoformat(), chunk_end.date().isoformat()))
        cursor = chunk_end + pd.Timedelta(days=1)
    return chunks


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _event_value(row: Mapping[str, Any]) -> tuple[bool, float | None]:
    missing = _as_bool(row.get("is_missing", False))
    value = pd.to_numeric(pd.Series([row.get("value")]), errors="coerce").iloc[0]
    if missing or pd.isna(value):
        return True, None
    return False, float(value)


@dataclass
class FredVintageAdapter:
    target_path: Path
    api_key: str | None = None
    series_starts: Mapping[str, str] | None = None
    request_json: RequestJson | None = None
    now: datetime | None = None

    def __post_init__(self) -> None:
        self.target_path = Path(self.target_path)

    def _series_starts(self) -> dict[str, str]:
        return dict(self.series_starts or _DEFAULT_SERIES_STARTS)

    def _call(
        self,
        endpoint: str,
        params: Mapping[str, str],
        *,
        request_evidence: list[list[Any]],
    ) -> tuple[Any, str, dict[str, str]]:
        safe_params = {key: str(value) for key, value in params.items() if key != "api_key"}
        transport_params = dict(safe_params)
        transport_params["api_key"] = str(self.api_key)
        request_evidence.append([endpoint, safe_params])
        result = (self.request_json or _request_json)(endpoint, transport_params)
        payload, body = _payload_and_bytes(result)
        return payload, hashlib.sha256(body).hexdigest(), safe_params

    def fetch_raw(self) -> dict[str, Any]:
        if not str(self.api_key or "").strip():
            raise ValueError("FRED API key is required for exact vintage replay")

        fetched_at = (self.now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        seed_rows: list[dict[str, Any]] = []
        seed_max: dict[str, str] = {}
        if self.target_path.exists():
            seed = pd.read_csv(self.target_path)
            if not seed.empty:
                seed_rows = seed.to_dict("records")
                if {"series_id", "vintage_date"}.issubset(seed.columns):
                    vintages = pd.to_datetime(seed["vintage_date"], errors="coerce")
                    local = seed.assign(_vintage=vintages).dropna(subset=["_vintage"])
                    for series_id, group in local.groupby("series_id"):
                        seed_max[str(series_id)] = group["_vintage"].max().date().isoformat()

        request_evidence: list[list[Any]] = []
        responses: list[dict[str, Any]] = []
        for series_id, observation_start in self._series_starts().items():
            common = {
                "series_id": series_id,
                "file_type": "json",
                "limit": "1",
            }
            latest_payload, _, _ = self._call(
                FRED_VINTAGE_DATES_URL,
                {**common, "sort_order": "desc"},
                request_evidence=request_evidence,
            )
            latest_dates = list((latest_payload or {}).get("vintage_dates") or [])
            if not latest_dates:
                raise ValueError(f"FRED returned no vintage dates for {series_id}")
            latest = str(latest_dates[0])[:10]
            start = seed_max.get(series_id)
            if start is None:
                earliest_payload, _, _ = self._call(
                    FRED_VINTAGE_DATES_URL,
                    {**common, "sort_order": "asc"},
                    request_evidence=request_evidence,
                )
                earliest_dates = list((earliest_payload or {}).get("vintage_dates") or [])
                if not earliest_dates:
                    raise ValueError(f"FRED returned no earliest vintage date for {series_id}")
                start = str(earliest_dates[0])[:10]
            if start > latest:
                raise ValueError(f"stored FRED vintage is later than official latest for {series_id}")
            if seed_max.get(series_id) == latest:
                continue

            for realtime_start, realtime_end in _date_chunks(start, latest):
                params = {
                    "series_id": series_id,
                    "file_type": "json",
                    "output_type": "3",
                    "limit": "100000",
                    "observation_start": str(observation_start)[:10],
                    "realtime_start": realtime_start,
                    "realtime_end": realtime_end,
                }
                payload, response_sha, safe_params = self._call(
                    FRED_OBSERVATIONS_URL,
                    params,
                    request_evidence=request_evidence,
                )
                observations = list((payload or {}).get("observations") or [])
                try:
                    total_count = int((payload or {}).get("count", len(observations)))
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"invalid FRED response count for {series_id}") from exc
                if total_count > len(observations):
                    raise ValueError(
                        f"truncated FRED vintage response for {series_id}: "
                        f"count={total_count} rows={len(observations)}"
                    )
                responses.append(
                    {
                        "series_id": series_id,
                        "source_url": FRED_OBSERVATIONS_URL,
                        "params": safe_params,
                        "response_sha256": response_sha,
                        "payload": payload,
                    }
                )

        return {
            "metadata": {
                "transport": "fred_api_output_type_3",
                "pit_rule": "exact_realtime_start_vintage",
                "fetched_at": fetched_at,
                "series_ids": list(self._series_starts()),
            },
            "request_evidence": request_evidence,
            "responses": responses,
            "seed_rows": seed_rows,
            "source_url": FRED_OBSERVATIONS_URL,
        }

    def parse(self, raw: Mapping[str, Any]) -> pd.DataFrame:
        fetched_at = str((raw.get("metadata") or {}).get("fetched_at") or "")
        incoming: list[dict[str, Any]] = []
        for response in raw.get("responses") or []:
            series_id = str(response.get("series_id") or "")
            response_sha = str(response.get("response_sha256") or "")
            source_url = str(response.get("source_url") or FRED_OBSERVATIONS_URL)
            observations = (response.get("payload") or {}).get("observations") or []
            prefix = series_id + "_"
            for observation in observations:
                observation_date = str(observation.get("date") or "")[:10]
                for field, raw_value in observation.items():
                    if not str(field).startswith(prefix):
                        continue
                    suffix = str(field)[len(prefix) :]
                    try:
                        vintage_date = datetime.strptime(suffix, "%Y%m%d").date().isoformat()
                    except ValueError as exc:
                        raise ValueError(f"invalid FRED vintage field: {field}") from exc
                    missing = raw_value in (None, ".", "")
                    value = None if missing else float(raw_value)
                    incoming.append(
                        {
                            "series_id": series_id,
                            "observation_date": observation_date,
                            "realtime_start": vintage_date,
                            "vintage_date": vintage_date,
                            "value": value,
                            "is_missing": missing,
                            "fetched_at": fetched_at,
                            "source_url": source_url,
                            "response_sha256": response_sha,
                        }
                    )

        merged: dict[tuple[str, str, str], dict[str, Any]] = {}
        for origin, rows in (("stored", raw.get("seed_rows") or []), ("incoming", incoming)):
            for source_row in rows:
                row = {column: source_row.get(column) for column in _EVENT_COLUMNS}
                row["series_id"] = str(row["series_id"] or "")
                row["observation_date"] = str(row["observation_date"] or "")[:10]
                row["vintage_date"] = str(row["vintage_date"] or "")[:10]
                row["realtime_start"] = str(row["realtime_start"] or row["vintage_date"])[:10]
                missing, value = _event_value(row)
                row["is_missing"] = missing
                row["value"] = value
                key = (row["series_id"], row["observation_date"], row["vintage_date"])
                previous = merged.get(key)
                if previous is not None:
                    previous_missing, previous_value = _event_value(previous)
                    same_value = previous_missing == missing and (
                        missing or math.isclose(float(previous_value), float(value), rel_tol=0.0, abs_tol=0.0)
                    )
                    if not same_value:
                        raise ValueError(f"conflicting ALFRED event for {key}")
                    if origin == "stored":
                        merged[key] = row
                    continue
                merged[key] = row

        frame = pd.DataFrame(merged.values(), columns=_EVENT_COLUMNS)
        if frame.empty:
            return frame
        return frame.sort_values(
            ["vintage_date", "series_id", "observation_date"], kind="stable"
        ).reset_index(drop=True)


def _validate_vintage_events(frame: pd.DataFrame) -> str | None:
    keys = ["series_id", "observation_date", "vintage_date"]
    if frame.duplicated(keys).any():
        return "duplicate ALFRED event keys"
    observations = pd.to_datetime(frame["observation_date"], errors="coerce")
    realtime = pd.to_datetime(frame["realtime_start"], errors="coerce")
    vintages = pd.to_datetime(frame["vintage_date"], errors="coerce")
    if observations.isna().any() or realtime.isna().any() or vintages.isna().any():
        return "unparseable ALFRED event dates"
    if not realtime.equals(vintages):
        return "realtime_start must equal vintage_date"
    if (observations > vintages).any():
        return "observation_date cannot be after vintage_date"
    if not frame["response_sha256"].astype(str).str.fullmatch(r"[0-9a-f]{64}").all():
        return "invalid response_sha256"
    missing = frame["is_missing"].map(_as_bool)
    values = pd.to_numeric(frame["value"], errors="coerce")
    if ((~missing) & (~values.map(math.isfinite))).any():
        return "non-missing ALFRED values must be finite"
    if (missing & values.notna()).any():
        return "missing ALFRED events must not contain a value"
    return None


def fred_vintage_spec(*, target_path: Path) -> ExternalSourceSpec:
    return ExternalSourceSpec(
        source_id="fred_vintages",
        target_path=target_path,
        date_column="vintage_date",
        required_columns=_EVENT_COLUMNS,
        min_rows=1,
        semantic_validator=_validate_vintage_events,
        pit_rule="exact_realtime_start_vintage",
        source_url=FRED_OBSERVATIONS_URL,
        allow_duplicate_dates=True,
    )


def _validate_derived_vintage_frame(frame: pd.DataFrame) -> str | None:
    observed = pd.to_datetime(frame["date"], errors="coerce")
    published = pd.to_datetime(frame["publish_date"], errors="coerce")
    vintage = pd.to_datetime(frame["vintage_date"], errors="coerce")
    realtime = pd.to_datetime(frame["realtime_start"], errors="coerce")
    if observed.isna().any() or published.isna().any() or vintage.isna().any() or realtime.isna().any():
        return "unparseable exact-vintage derived dates"
    if not published.equals(vintage) or not published.equals(realtime):
        return "publish_date, realtime_start, and vintage_date must match"
    if (observed > published).any():
        return "derived observation date cannot be after publish date"
    return None


def fred_vintage_percentile_spec(
    *,
    source_id: str,
    target_path: Path,
    field: str,
) -> ExternalSourceSpec:
    return ExternalSourceSpec(
        source_id=source_id,
        target_path=target_path,
        date_column="publish_date",
        required_columns=(
            "date",
            "publish_date",
            "realtime_start",
            "vintage_date",
            "fetched_at",
            field,
            f"{field}_pctl",
        ),
        min_rows=1,
        semantic_validator=_validate_derived_vintage_frame,
        pit_rule="exact_realtime_start_vintage",
        source_url=FRED_OBSERVATIONS_URL,
    )


def fred_vintage_net_liquidity_spec(*, target_path: Path) -> ExternalSourceSpec:
    return ExternalSourceSpec(
        source_id="fred_net_liquidity_vintage",
        target_path=target_path,
        date_column="publish_date",
        required_columns=(
            "date",
            "publish_date",
            "realtime_start",
            "vintage_date",
            "fetched_at",
            "walcl",
            "wtregen",
            "rrp",
            "net_liq",
            "net_liq_chg10",
            "net_liq_chg10_pctl",
            "walcl_realtime_start",
            "wtregen_realtime_start",
            "rrp_realtime_start",
        ),
        min_rows=1,
        semantic_validator=_validate_derived_vintage_frame,
        pit_rule="exact_realtime_start_vintage",
        source_url=FRED_OBSERVATIONS_URL,
    )


def _normalized_events(events: pd.DataFrame) -> pd.DataFrame:
    frame = events.copy()
    for column in ("observation_date", "vintage_date", "realtime_start"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.date.astype(str)
    frame["series_id"] = frame["series_id"].astype(str)
    frame["is_missing"] = frame["is_missing"].map(_as_bool)
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    return frame.sort_values(["vintage_date", "series_id", "observation_date"], kind="stable")


def _percentile(values: pd.Series, *, window: int, min_periods: int) -> float:
    local = pd.to_numeric(values, errors="coerce").dropna().tail(window)
    if len(local) < min_periods:
        return float("nan")
    return float(_last_percentile(local))


def _signature(values: list[Any]) -> tuple[Any, ...]:
    return tuple(None if isinstance(value, float) and math.isnan(value) else value for value in values)


def build_vintage_percentile_frame(
    events: pd.DataFrame,
    *,
    series_id: str,
    field: str,
    window: int = 252,
    min_periods: int = 60,
) -> pd.DataFrame:
    selected = _normalized_events(events)
    selected = selected.loc[selected["series_id"] == series_id]
    output_columns = [
        "date",
        "publish_date",
        "realtime_start",
        "vintage_date",
        "fetched_at",
        field,
        f"{field}_pctl",
    ]
    state: dict[str, tuple[float, str]] = {}
    rows: list[dict[str, Any]] = []
    previous_signature: tuple[Any, ...] | None = None
    for vintage_date, group in selected.groupby("vintage_date", sort=True):
        for event in group.to_dict("records"):
            observation_date = str(event["observation_date"])
            if event["is_missing"] or pd.isna(event["value"]):
                state.pop(observation_date, None)
            else:
                state[observation_date] = (float(event["value"]), str(vintage_date))
        if not state:
            continue
        visible = pd.Series({date: value for date, (value, _vintage) in state.items()}).sort_index()
        current_date = str(visible.index[-1])
        current_value = float(visible.iloc[-1])
        percentile = _percentile(visible, window=window, min_periods=min_periods)
        signature = _signature([current_date, current_value, percentile])
        if signature == previous_signature:
            continue
        previous_signature = signature
        rows.append(
            {
                "date": current_date,
                "publish_date": str(vintage_date),
                "realtime_start": str(vintage_date),
                "vintage_date": str(vintage_date),
                "fetched_at": str(group.iloc[-1].get("fetched_at") or ""),
                field: current_value,
                f"{field}_pctl": percentile,
            }
        )
    return pd.DataFrame(rows, columns=output_columns)


def build_vintage_net_liquidity_frame(
    events: pd.DataFrame,
    *,
    percentile_window: int = 252,
    min_periods: int = 60,
    change_periods: int = 10,
) -> pd.DataFrame:
    selected = _normalized_events(events)
    required = ("WALCL", "WTREGEN", "RRPONTSYD")
    selected = selected.loc[selected["series_id"].isin(required)]
    output_columns = [
        "date",
        "publish_date",
        "realtime_start",
        "vintage_date",
        "fetched_at",
        "walcl",
        "wtregen",
        "rrp",
        "net_liq",
        "net_liq_chg10",
        "net_liq_chg10_pctl",
        "walcl_realtime_start",
        "wtregen_realtime_start",
        "rrp_realtime_start",
    ]
    states: dict[str, dict[str, tuple[float, str]]] = {series_id: {} for series_id in required}
    rows: list[dict[str, Any]] = []
    previous_signature: tuple[Any, ...] | None = None
    for vintage_date, group in selected.groupby("vintage_date", sort=True):
        for event in group.to_dict("records"):
            series_id = str(event["series_id"])
            observation_date = str(event["observation_date"])
            if event["is_missing"] or pd.isna(event["value"]):
                states[series_id].pop(observation_date, None)
            else:
                states[series_id][observation_date] = (float(event["value"]), str(vintage_date))
        union_dates: set[str] = set()
        for series_id in required:
            union_dates.update(states[series_id])
        if not union_dates:
            continue
        ordered_dates = sorted(union_dates)
        value_columns: dict[str, pd.Series] = {}
        vintage_columns: dict[str, pd.Series] = {}
        for series_id in required:
            values = pd.Series(
                {date: value for date, (value, _seen_at) in states[series_id].items()},
                dtype="float64",
            )
            seen_at = pd.Series(
                {date: seen for date, (_value, seen) in states[series_id].items()},
                dtype="object",
            )
            value_columns[series_id] = values.reindex(ordered_dates).ffill()
            vintage_columns[series_id] = seen_at.reindex(ordered_dates).ffill()
        aligned = pd.DataFrame(value_columns, index=ordered_dates).dropna()
        if aligned.empty:
            continue
        net_frame = aligned.rename(
            columns={"WALCL": "walcl", "WTREGEN": "wtregen", "RRPONTSYD": "rrp"}
        ).reset_index(names="date")
        net_frame["net_liq"] = net_frame["walcl"] - net_frame["wtregen"] - net_frame["rrp"]
        net_frame["net_liq_chg10"] = net_frame["net_liq"].diff(change_periods)
        current = net_frame.iloc[-1]
        if pd.isna(current["net_liq_chg10"]):
            continue
        percentile = _percentile(
            net_frame["net_liq_chg10"],
            window=percentile_window,
            min_periods=min_periods,
        )
        current_date = str(current["date"])
        signature = _signature(
            [
                current_date,
                float(current["walcl"]),
                float(current["wtregen"]),
                float(current["rrp"]),
                float(current["net_liq"]),
                float(current["net_liq_chg10"]),
                percentile,
            ]
        )
        if signature == previous_signature:
            continue
        previous_signature = signature
        rows.append(
            {
                "date": current_date,
                "publish_date": str(vintage_date),
                "realtime_start": str(vintage_date),
                "vintage_date": str(vintage_date),
                "fetched_at": str(group.iloc[-1].get("fetched_at") or ""),
                "walcl": float(current["walcl"]),
                "wtregen": float(current["wtregen"]),
                "rrp": float(current["rrp"]),
                "net_liq": float(current["net_liq"]),
                "net_liq_chg10": float(current["net_liq_chg10"]),
                "net_liq_chg10_pctl": percentile,
                "walcl_realtime_start": str(vintage_columns["WALCL"].loc[current_date]),
                "wtregen_realtime_start": str(vintage_columns["WTREGEN"].loc[current_date]),
                "rrp_realtime_start": str(vintage_columns["RRPONTSYD"].loc[current_date]),
            }
        )
    return pd.DataFrame(rows, columns=output_columns)


@dataclass(frozen=True)
class FredVintagePercentileAdapter:
    vintage_path: Path
    series_id: str
    field: str
    window: int = 252
    min_periods: int = 60

    def fetch_raw(self) -> dict[str, Any]:
        body = Path(self.vintage_path).read_bytes()
        return {
            "vintage_path": str(self.vintage_path),
            "vintage_sha256": hashlib.sha256(body).hexdigest(),
            "source_url": FRED_OBSERVATIONS_URL,
        }

    def parse(self, raw: Mapping[str, Any]) -> pd.DataFrame:
        path = Path(str(raw["vintage_path"]))
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != str(raw.get("vintage_sha256") or ""):
            raise ValueError("FRED vintage store SHA256 changed between fetch and parse")
        return build_vintage_percentile_frame(
            pd.read_csv(path),
            series_id=self.series_id,
            field=self.field,
            window=self.window,
            min_periods=self.min_periods,
        )


@dataclass(frozen=True)
class FredVintageNetLiquidityAdapter:
    vintage_path: Path
    percentile_window: int = 252
    min_periods: int = 60
    change_periods: int = 10

    def fetch_raw(self) -> dict[str, Any]:
        body = Path(self.vintage_path).read_bytes()
        return {
            "vintage_path": str(self.vintage_path),
            "vintage_sha256": hashlib.sha256(body).hexdigest(),
            "source_url": FRED_OBSERVATIONS_URL,
        }

    def parse(self, raw: Mapping[str, Any]) -> pd.DataFrame:
        path = Path(str(raw["vintage_path"]))
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != str(raw.get("vintage_sha256") or ""):
            raise ValueError("FRED vintage store SHA256 changed between fetch and parse")
        return build_vintage_net_liquidity_frame(
            pd.read_csv(path),
            percentile_window=self.percentile_window,
            min_periods=self.min_periods,
            change_periods=self.change_periods,
        )
