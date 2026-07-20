from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from hermes_escape_top.scripts import (
    backfill_cot,
    backfill_crypto_micro,
    backfill_occ_pcr,
    refresh_cboe_daily_pcr,
)

from .clock import shanghai_today
from .provenance import source_provenance
from .registry import ExternalSourceSpec


@dataclass(frozen=True)
class CboePcrAdapter:
    seed_path: Path
    fetch_text: Callable[[], str] = field(
        default_factory=lambda: refresh_cboe_daily_pcr.fetch_page
    )

    def fetch_raw(self) -> dict[str, Any]:
        return {
            "source_url": refresh_cboe_daily_pcr.URL,
            "provenance": source_provenance("cboe_daily_html"),
            "html": self.fetch_text(),
        }

    def parse(self, raw: dict[str, Any]) -> pd.DataFrame:
        record = refresh_cboe_daily_pcr.parse_page(str((raw or {}).get("html") or ""))
        seed = _read_seed(self.seed_path)
        observation = date.fromisoformat(record["date"])
        row = {
            "date": observation,
            "publish_date": observation + timedelta(days=1),
            "equity_pcr": float(record["ratio"]),
            "source": "CBOE_DAILY_HTML",
            "is_proxy": False,
        }
        frame = pd.concat([seed, pd.DataFrame([row])], ignore_index=True)
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = refresh_cboe_daily_pcr._dedup_real_wins(frame)
        frame["publish_date"] = frame["date"] + pd.Timedelta(days=1)
        frame["equity_pcr"] = pd.to_numeric(frame["equity_pcr"], errors="coerce")
        frame["equity_pcr_pctl"] = (
            frame["equity_pcr"]
            .rolling(refresh_cboe_daily_pcr.PCTL_WINDOW, min_periods=60)
            .apply(lambda values: float((values <= values.iloc[-1]).mean() * 100.0), raw=False)
        )
        frame = frame.dropna(subset=["date", "equity_pcr"]).sort_values("date")
        frame["date"] = frame["date"].dt.date.astype(str)
        frame["publish_date"] = pd.to_datetime(
            frame["publish_date"], errors="coerce"
        ).dt.date.astype(str)
        frame.attrs["cboe_record"] = record
        return frame[
            ["date", "publish_date", "equity_pcr", "equity_pcr_pctl", "source", "is_proxy"]
        ]


def cboe_pcr_spec(*, target_path: Path, min_rows: int = 60) -> ExternalSourceSpec:
    return ExternalSourceSpec(
        source_id="cboe_equity_pcr",
        target_path=target_path,
        required_columns=(
            "date",
            "publish_date",
            "equity_pcr",
            "equity_pcr_pctl",
            "source",
            "is_proxy",
        ),
        min_rows=min_rows,
        semantic_validator=_validate_cboe,
        pit_rule="observation_date_plus_one_day",
        source_url=refresh_cboe_daily_pcr.URL,
    )


def _validate_cboe(frame: pd.DataFrame) -> str | None:
    record = frame.attrs.get("cboe_record") or {}
    if record:
        error = refresh_cboe_daily_pcr.validate(record, None)
        if error:
            return error
    values = pd.to_numeric(frame["equity_pcr"], errors="coerce")
    if values.isna().any() or not values.between(*refresh_cboe_daily_pcr.RATIO_BOUNDS).all():
        return "equity PCR outside policy bounds"
    raw_percentiles = frame["equity_pcr_pctl"]
    percentiles = pd.to_numeric(raw_percentiles, errors="coerce")
    if (raw_percentiles.notna() & percentiles.isna()).any():
        return "equity PCR percentile contains non-numeric values"
    if not percentiles.dropna().between(0.0, 100.0).all():
        return "equity PCR percentile outside [0, 100]"
    return _validate_publish_lag(frame, observation_column="date", lag_days=1)


@dataclass(frozen=True)
class CotNqAdapter:
    fetch_frame: Callable[[], pd.DataFrame] = field(
        default_factory=lambda: backfill_cot._fetch_all
    )

    def fetch_raw(self) -> dict[str, Any]:
        frame = self.fetch_frame()
        return {
            "source_url": backfill_cot._API_BASE,
            "provenance": source_provenance("cftc_public_api"),
            "rows": _frame_records(frame),
        }

    def parse(self, raw: dict[str, Any]) -> pd.DataFrame:
        frame = pd.DataFrame((raw or {}).get("rows") or [])
        if frame.empty:
            return pd.DataFrame(columns=_COT_COLUMNS)
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        computed = backfill_cot._compute(frame)
        computed = computed.rename(columns={"date": "observation_date"})
        computed["date"] = computed["observation_date"] + pd.Timedelta(days=3)
        computed["publish_date"] = computed["date"]
        for column in ("observation_date", "date", "publish_date"):
            computed[column] = pd.to_datetime(computed[column]).dt.date.astype(str)
        return computed[_COT_COLUMNS]


_COT_COLUMNS = [
    "date",
    "publish_date",
    "observation_date",
    "asset_mgr_net",
    "levered_net",
    "combined_net",
    "open_interest",
    "combined_net_oi_pct",
]


def cot_nq_spec(*, target_path: Path, min_rows: int = 52) -> ExternalSourceSpec:
    return ExternalSourceSpec(
        source_id="cot_nq",
        target_path=target_path,
        required_columns=tuple(_COT_COLUMNS),
        min_rows=min_rows,
        semantic_validator=_validate_cot,
        pit_rule="tuesday_observation_friday_publication",
        source_url=backfill_cot._API_BASE,
    )


def _validate_cot(frame: pd.DataFrame) -> str | None:
    open_interest = pd.to_numeric(frame.get("open_interest"), errors="coerce")
    ratio = pd.to_numeric(frame.get("combined_net_oi_pct"), errors="coerce")
    if open_interest.isna().any() or (open_interest <= 0).any():
        return "COT open interest must be positive"
    if ratio.isna().any() or not ratio.between(-2.0, 2.0).all():
        return "COT combined net/OI outside policy bounds"
    return _validate_publish_lag(
        frame,
        observation_column="observation_date",
        lag_days=3,
        require_date_equals_publish=True,
    )


@dataclass(frozen=True)
class OccPcrAdapter:
    seed_path: Path
    weeks: int = 3
    today: date | None = None
    fetch_week: Callable[[date], dict[str, Any] | None] = field(
        default_factory=lambda: backfill_occ_pcr.fetch_week
    )

    def fetch_raw(self) -> dict[str, Any]:
        current = self.today or shanghai_today()
        friday = current - timedelta(days=(current.weekday() - 4) % 7)
        rows = []
        for offset in range(max(1, self.weeks)):
            record = self.fetch_week(friday - timedelta(weeks=offset))
            if record:
                rows.append(record)
        return {
            "source_url": backfill_occ_pcr.URL,
            "provenance": source_provenance("occ_weekly_report"),
            "rows": rows,
        }

    def parse(self, raw: dict[str, Any]) -> pd.DataFrame:
        seed = _read_seed(self.seed_path)
        incoming = pd.DataFrame((raw or {}).get("rows") or [])
        frame = pd.concat([seed, incoming], ignore_index=True)
        if frame.empty:
            return pd.DataFrame(columns=_OCC_COLUMNS)
        observation = (
            pd.to_datetime(frame["observation_date"], errors="coerce")
            if "observation_date" in frame
            else pd.to_datetime(frame["date"], errors="coerce")
        )
        frame["observation_date"] = observation
        frame["date"] = observation + pd.Timedelta(days=1)
        frame["publish_date"] = frame["date"]
        for column in backfill_occ_pcr.FIELDS[1:]:
            frame[column] = pd.to_numeric(frame.get(column), errors="coerce")
        frame = frame.dropna(subset=["observation_date", "calls_total", "puts_total"])
        frame = frame.sort_values("observation_date").drop_duplicates("observation_date", keep="last")
        for column in ("date", "publish_date", "observation_date"):
            frame[column] = pd.to_datetime(frame[column]).dt.date.astype(str)
        return frame[_OCC_COLUMNS]


_OCC_COLUMNS = [
    "date",
    "publish_date",
    "observation_date",
    "calls_total",
    "puts_total",
    "pcr_total",
    "calls_cust",
    "puts_cust",
    "pcr_cust",
]


def occ_pcr_spec(*, target_path: Path, min_rows: int = 1) -> ExternalSourceSpec:
    return ExternalSourceSpec(
        source_id="occ_equity_pcr",
        target_path=target_path,
        required_columns=tuple(_OCC_COLUMNS),
        min_rows=min_rows,
        semantic_validator=_validate_occ,
        pit_rule="week_ending_friday_plus_one_day",
        source_url=backfill_occ_pcr.URL,
    )


def _validate_occ(frame: pd.DataFrame) -> str | None:
    calls = pd.to_numeric(frame.get("calls_total"), errors="coerce")
    ratios = pd.to_numeric(frame.get("pcr_total"), errors="coerce")
    if calls.isna().any() or (calls <= 0).any():
        return "OCC total calls must be positive"
    if ratios.isna().any() or not ratios.between(0.1, 5.0).all():
        return "OCC put/call ratio outside policy bounds"
    return _validate_publish_lag(
        frame,
        observation_column="observation_date",
        lag_days=1,
        require_date_equals_publish=True,
    )


@dataclass(frozen=True)
class BtcMicroAdapter:
    seed_path: Path
    fetch_bundle: Callable[[Path], dict[str, Any]] = field(
        default_factory=lambda: _fetch_btc_bundle
    )

    def fetch_raw(self) -> dict[str, Any]:
        raw = dict(self.fetch_bundle(Path(self.seed_path)))
        raw.setdefault("source_url", backfill_crypto_micro.DERIBIT)
        funding_source = str(raw.get("funding_source") or "unknown")
        selected_source = "okx" if funding_source == "okx_failover" else funding_source
        primary_failure = str(raw.get("primary_failure") or "").strip() or None
        if selected_source == "okx" and primary_failure is None:
            primary_failure = "empty_funding_response"
        if selected_source == "none" and primary_failure is None:
            primary_failure = "no_provider_observations"
        raw["provenance"] = source_provenance(
            selected_source,
            primary_source="deribit",
            fallback_used=selected_source in {"okx", "none"},
            primary_failure=primary_failure,
        )
        return raw

    def parse(self, raw: dict[str, Any]) -> pd.DataFrame:
        funding = pd.DataFrame((raw or {}).get("funding") or [])
        dvol = pd.DataFrame((raw or {}).get("dvol") or [])
        for frame in (funding, dvol):
            if not frame.empty:
                frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        seed = _read_seed(self.seed_path, parse_dates=["date"])
        prior_sources: dict[str, str] = {}
        if not seed.empty and "funding_source" in seed:
            prior_sources = {
                pd.Timestamp(row["date"]).date().isoformat(): str(row["funding_source"])
                for row in seed[["date", "funding_source"]].to_dict("records")
                if pd.notna(row.get("date")) and pd.notna(row.get("funding_source"))
            }
        unified = backfill_crypto_micro.build_unified(funding, dvol, seed)
        unified["is_proxy"] = unified["is_proxy"].fillna(True).astype(bool)
        source = str((raw or {}).get("funding_source") or "unknown")
        unified["date"] = pd.to_datetime(unified["date"]).dt.date.astype(str)
        unified["funding_source"] = unified["date"].map(prior_sources).astype("object")
        unified.loc[
            (unified["is_proxy"] == True) & unified["funding_source"].isna(),
            "funding_source",
        ] = "proxy"
        unified.loc[
            (unified["is_proxy"] == False) & unified["funding_source"].isna(),
            "funding_source",
        ] = source
        unified["publish_date"] = pd.to_datetime(unified["publish_date"]).dt.date.astype(str)
        unified.attrs["btc_fetch_evidence"] = {
            "provider_row_count": int(len(funding) + len(dvol)),
            "funding_provider_row_count": int(len(funding)),
            "dvol_provider_row_count": int(len(dvol)),
            "no_new_data_expected": bool((raw or {}).get("no_new_data_expected")),
            "expected_through": (raw or {}).get("expected_through"),
            "last_real_date": (raw or {}).get("last_real_date"),
        }
        return unified


def btc_micro_spec(*, target_path: Path, min_rows: int = 1) -> ExternalSourceSpec:
    return ExternalSourceSpec(
        source_id="btc_funding_basis",
        target_path=target_path,
        required_columns=(
            "date",
            "publish_date",
            "btc_funding_8h_avg",
            "btc_funding_pctl",
            "btc_basis_annual",
            "btc_basis_pctl",
            "is_proxy",
            "funding_source",
        ),
        min_rows=min_rows,
        semantic_validator=_validate_btc,
        pit_rule="exchange_timestamp_utc_day",
        source_url=backfill_crypto_micro.DERIBIT,
    )


def _validate_btc(frame: pd.DataFrame) -> str | None:
    fetch_evidence = frame.attrs.get("btc_fetch_evidence") or {}
    if (
        int(fetch_evidence.get("funding_provider_row_count") or 0) == 0
        and not bool(fetch_evidence.get("no_new_data_expected"))
    ):
        return "BTC funding provider returned no new observations and canonical is not current through the conservative completion date"
    proxy = frame.get("is_proxy")
    if proxy is None:
        real = frame
    elif pd.api.types.is_bool_dtype(proxy):
        real = frame.loc[~proxy.fillna(True)]
    else:
        is_proxy = proxy.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})
        real = frame.loc[~is_proxy]
    funding = pd.to_numeric(real.get("btc_funding_8h_avg"), errors="coerce").dropna()
    basis = pd.to_numeric(real.get("btc_basis_annual"), errors="coerce").dropna()
    if funding.empty or (funding.abs() > 0.1).any():
        return "BTC funding outside policy bounds"
    if basis.empty or (basis.abs() > 10.0).any():
        return "BTC annualized basis outside policy bounds"
    return _validate_publish_lag(frame, observation_column="date", lag_days=0)


def _validate_publish_lag(
    frame: pd.DataFrame,
    *,
    observation_column: str,
    lag_days: int,
    require_date_equals_publish: bool = False,
) -> str | None:
    observation = pd.to_datetime(frame.get(observation_column), errors="coerce")
    published = pd.to_datetime(frame.get("publish_date"), errors="coerce")
    expected = observation + pd.Timedelta(days=lag_days)
    if observation.isna().any() or published.isna().any() or not published.equals(expected):
        return f"publish_date violates {observation_column}+{lag_days}d PIT policy"
    if require_date_equals_publish:
        canonical = pd.to_datetime(frame.get("date"), errors="coerce")
        if canonical.isna().any() or not canonical.equals(published):
            return "canonical date must equal publish_date"
    return None


def _fetch_btc_bundle(seed_path: Path) -> dict[str, Any]:
    existing = _read_seed(seed_path, parse_dates=["date"])
    real_rows = existing
    if not existing.empty and "is_proxy" in existing:
        real_rows = existing[existing["is_proxy"].astype(str).str.lower().isin({"false", "0"})]
    last_real = pd.to_datetime(real_rows["date"], errors="coerce").max() if not real_rows.empty else pd.NaT
    if pd.isna(last_real):
        start_ms = backfill_crypto_micro.DVOL_LAUNCH_MS
    else:
        start_ms = int(pd.Timestamp(last_real).timestamp() * 1000) + 86_400_000
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    dvol = backfill_crypto_micro.fetch_deribit_dvol(
        max(start_ms, backfill_crypto_micro.DVOL_LAUNCH_MS), end_ms
    )
    funding = backfill_crypto_micro.fetch_deribit_funding(start_ms, end_ms)
    source = "deribit"
    if funding.empty:
        funding = backfill_crypto_micro.fetch_okx_funding_recent()
        source = "okx_failover"
    expected_through = datetime.now(timezone.utc).date() - timedelta(days=1)
    last_real_date = None if pd.isna(last_real) else pd.Timestamp(last_real).date()
    no_new_data_expected = bool(
        funding.empty
        and dvol.empty
        and last_real_date is not None
        and last_real_date >= expected_through
    )
    return {
        "source_url": backfill_crypto_micro.DERIBIT,
        "funding_source": source,
        "primary_failure": (
            "empty_funding_response" if source == "okx_failover" else None
        ),
        "funding": _frame_records(funding),
        "dvol": _frame_records(dvol),
        "expected_through": expected_through.isoformat(),
        "last_real_date": last_real_date.isoformat() if last_real_date else None,
        "no_new_data_expected": no_new_data_expected,
    }


def _read_seed(path: Path, **kwargs: Any) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, **kwargs)


def _frame_records(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    local = frame.copy()
    for column in local.columns:
        if pd.api.types.is_datetime64_any_dtype(local[column]):
            local[column] = pd.to_datetime(local[column]).dt.date.astype(str)
    return local.to_dict("records")
