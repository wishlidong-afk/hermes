from __future__ import annotations

import glob
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

from .clock import shanghai_today, timestamp_to_shanghai_date

DECISION_ROLES = frozenset({"strategy", "hard_gate", "auxiliary", "research"})


@dataclass(frozen=True)
class ExternalSourceProfile:
    source_id: str
    label: str
    cadence: str
    max_age_days: int
    warn_age_days: int
    primary: str
    fallback: str
    decision_role: str
    soft_record_names: tuple[str, ...] = ()
    import_globs: tuple[str, ...] = ()
    feature_flag: str | None = None
    decision_weight: float = 0.0
    automation_mode: str = "api"
    pit_rule: str = "observation_date"
    migration_deadline: str | None = None
    slo_key: str | None = None
    active: bool = True
    feature_default: bool = False
    publication_schedule: str = "publisher schedule; checked by the 06:45/07:05 pre-daily jobs"
    refresh_group: str = "common"
    refresh_order: int = 100
    warn_only_stale_after_refresh: bool = False
    depends_on: str | None = None
    expected_release_weekdays: tuple[int, ...] = ()
    expected_advance_grace_days: int = 1
    expected_release_policy: str = "weekday"
    publisher_release_ids: tuple[str, ...] = ()
    publisher_availability_lag_days: int = 0
    lifecycle_policy: str = "ACTIVE"
    lifecycle_effective_date: str | None = None
    lifecycle_reason: str = ""
    probe_weekdays: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.decision_role not in DECISION_ROLES:
            raise ValueError(
                f"unsupported decision_role for {self.source_id}: {self.decision_role}"
            )

    @property
    def grace_days(self) -> int:
        return max(0, int(self.max_age_days) - int(self.warn_age_days))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("soft_record_names")
        payload["import_globs"] = list(self.import_globs)
        payload["expected_release_weekdays"] = list(self.expected_release_weekdays)
        payload["publisher_release_ids"] = list(self.publisher_release_ids)
        payload["probe_weekdays"] = list(self.probe_weekdays)
        payload["grace_days"] = self.grace_days
        return payload


PROFILES: dict[str, ExternalSourceProfile] = {
    "fred_vintages": ExternalSourceProfile(
        source_id="fred_vintages",
        label="FRED/ALFRED Vintage Events",
        cadence="daily",
        max_age_days=6,
        warn_age_days=4,
        primary="FRED API output_type=3 exact vintage events",
        fallback="freeze certified vintage store and all FRED-derived canonicals",
        decision_role="hard_gate",
        feature_flag="use_fred_vintage_pit",
        decision_weight=0.0,
        pit_rule="exact_realtime_start_vintage",
        publication_schedule="daily ALFRED vintage events available after the source release",
        refresh_group="exact_fred",
        refresh_order=10,
    ),
    "dollar_vintage": ExternalSourceProfile(
        source_id="dollar_vintage",
        label="DXY / Dollar · exact vintage",
        cadence="weekly",
        max_age_days=10,
        warn_age_days=8,
        primary="FRED/ALFRED exact vintage event store",
        fallback="freeze last certified exact-vintage Dollar canonical",
        decision_role="strategy",
        soft_record_names=("dollar",),
        feature_flag="use_fred_vintage_pit",
        decision_weight=4.0,
        pit_rule="exact_realtime_start_vintage",
        slo_key="dollar",
        publication_schedule="after the parent ALFRED event-store promotion",
        refresh_group="exact_fred",
        refresh_order=11,
        depends_on="fred_vintages",
    ),
    "real_rate_vintage": ExternalSourceProfile(
        source_id="real_rate_vintage",
        label="10Y Real Rate · exact vintage",
        cadence="daily",
        max_age_days=6,
        warn_age_days=4,
        primary="FRED/ALFRED exact vintage event store",
        fallback="freeze last certified exact-vintage Real Rate canonical",
        decision_role="strategy",
        soft_record_names=("real_rate",),
        feature_flag="use_fred_vintage_pit",
        decision_weight=4.0,
        pit_rule="exact_realtime_start_vintage",
        slo_key="real_rate",
        publication_schedule="after the parent ALFRED event-store promotion",
        refresh_group="exact_fred",
        refresh_order=12,
        depends_on="fred_vintages",
    ),
    "fred_net_liquidity_vintage": ExternalSourceProfile(
        source_id="fred_net_liquidity_vintage",
        label="FRED Net Liquidity · exact vintage",
        cadence="daily",
        max_age_days=6,
        warn_age_days=4,
        primary="FRED/ALFRED exact vintage event store",
        fallback="freeze last certified exact-vintage Net Liquidity canonical",
        decision_role="strategy",
        soft_record_names=("net_liquidity",),
        feature_flag="use_fred_vintage_pit",
        decision_weight=4.0,
        pit_rule="exact_realtime_start_vintage",
        slo_key="net_liquidity",
        publication_schedule="after the parent ALFRED event-store promotion",
        refresh_group="exact_fred",
        refresh_order=13,
        depends_on="fred_vintages",
    ),
    "dollar": ExternalSourceProfile(
        source_id="dollar",
        label="DXY / Dollar",
        cadence="weekly",
        max_age_days=10,
        warn_age_days=8,
        primary="FRED DTWEXBGS API cross-checked against Federal Reserve Board H.10",
        fallback="freeze last certified Dollar canonical when either official path disagrees or is unavailable",
        decision_role="strategy",
        soft_record_names=("dollar",),
        feature_flag="data_dollar",
        decision_weight=4.0,
        pit_rule="observation_date_plus_one_day",
        publication_schedule="FRED DTWEXBGS weekly publisher calendar",
        expected_release_policy="fred_release_calendar",
        publisher_release_ids=("17",),
        publisher_availability_lag_days=1,
        refresh_group="legacy_fred",
        refresh_order=20,
        warn_only_stale_after_refresh=True,
    ),
    "real_rate": ExternalSourceProfile(
        source_id="real_rate",
        label="10Y Real Rate",
        cadence="daily",
        max_age_days=6,
        warn_age_days=4,
        primary="FRED DFII10 API",
        fallback="rerun FRED external source",
        decision_role="strategy",
        soft_record_names=("real_rate",),
        feature_flag="data_real_rate",
        decision_weight=4.0,
        pit_rule="observation_date_plus_one_day",
        publication_schedule="FRED DFII10 on US business days",
        expected_release_policy="fred_release_calendar",
        publisher_release_ids=("18",),
        publisher_availability_lag_days=1,
        refresh_group="legacy_fred",
        refresh_order=21,
    ),
    "fred_net_liquidity": ExternalSourceProfile(
        source_id="fred_net_liquidity",
        label="FRED Net Liquidity",
        cadence="daily",
        max_age_days=6,
        warn_age_days=4,
        primary="FRED WALCL/WTREGEN/RRP APIs",
        fallback="rerun FRED external source",
        decision_role="strategy",
        soft_record_names=("net_liquidity",),
        feature_flag="data_net_liquidity",
        decision_weight=4.0,
        pit_rule="observation_date_plus_one_day",
        slo_key="net_liquidity",
        publication_schedule="daily RRP plus weekly WALCL and WTREGEN releases",
        expected_release_policy="fred_release_calendar",
        publisher_release_ids=("20", "379"),
        publisher_availability_lag_days=1,
        refresh_group="legacy_fred",
        refresh_order=22,
    ),
    "naaim_exposure": ExternalSourceProfile(
        source_id="naaim_exposure",
        label="NAAIM Exposure",
        cadence="weekly",
        max_age_days=13,
        warn_age_days=10,
        primary="NAAIM authorized subscriber XLSX, then public official XLSX",
        fallback="official workbook import",
        decision_role="strategy",
        soft_record_names=("naaim",),
        feature_flag="data_naaim",
        decision_weight=2.0,
        automation_mode="subscriber_or_official_file",
        pit_rule="issue_date_plus_one_day",
        migration_deadline="2026-08-01",
        publication_schedule="weekly NAAIM issue, normally Wednesday US time",
        expected_release_weekdays=(3,),
        lifecycle_policy="RETIRED_PAYWALL",
        lifecycle_effective_date="2026-08-01",
        lifecycle_reason=(
            "NAAIM retired current public workbook access behind a paid subscription; "
            "certified history remains frozen"
        ),
        probe_weekdays=(4,),
        refresh_order=45,
        import_globs=(
            "~/.hermes/external_imports/*naaim*.xlsx",
            "~/.hermes/external_imports/*NAAIM*.xlsx",
            "~/.hermes/external_imports/USE_Data*.xlsx",
            "~/Downloads/*naaim*.xlsx",
            "~/Downloads/*NAAIM*.xlsx",
            "~/Downloads/USE_Data*.xlsx",
        ),
    ),
    "aaii_sentiment": ExternalSourceProfile(
        source_id="aaii_sentiment",
        label="AAII Sentiment",
        cadence="weekly",
        max_age_days=13,
        warn_age_days=10,
        primary="AAII results page, then official Insights RSS",
        fallback="browser download + official file import",
        decision_role="strategy",
        soft_record_names=("aaii",),
        feature_flag="data_aaii",
        decision_weight=2.0,
        automation_mode="official_rss_with_file_fallback",
        pit_rule="official_publish_date_or_reported_plus_one_day",
        publication_schedule="weekly AAII issue, normally Thursday US time",
        expected_release_policy="publisher_issue_sequence",
        publisher_availability_lag_days=1,
        refresh_order=46,
        import_globs=(
            "~/.hermes/external_imports/sentiment*.xls",
            "~/.hermes/external_imports/sentiment*.xlsx",
            "~/.hermes/external_imports/sentiment*.csv",
            "~/Downloads/sentiment*.xls",
            "~/Downloads/sentiment*.xlsx",
            "~/Downloads/sentiment*.csv",
        ),
    ),
    "cboe_vix": ExternalSourceProfile(
        source_id="cboe_vix",
        label="CBOE VIX",
        cadence="daily",
        max_age_days=6,
        warn_age_days=4,
        primary="CBOE official VIX history CSV",
        fallback="freeze last certified CBOE history; Yahoo is witness only",
        decision_role="strategy",
        soft_record_names=("cboe_indices",),
        feature_flag="use_cboe_official_indices",
        decision_weight=4.0,
        pit_rule="completed_us_session_plus_yahoo_witness",
        slo_key="cboe_indices",
        publication_schedule="after each completed US options session",
        expected_release_weekdays=(1, 2, 3, 4, 5),
        refresh_group="cboe_indices",
        refresh_order=50,
    ),
    "cboe_vix3m": ExternalSourceProfile(
        source_id="cboe_vix3m",
        label="CBOE VIX3M",
        cadence="daily",
        max_age_days=6,
        warn_age_days=4,
        primary="CBOE official VIX3M history CSV",
        fallback="freeze last certified CBOE history; Yahoo is witness only",
        decision_role="strategy",
        soft_record_names=("cboe_indices",),
        feature_flag="use_cboe_official_indices",
        decision_weight=4.0,
        pit_rule="completed_us_session_plus_yahoo_witness",
        slo_key="cboe_indices",
        publication_schedule="after each completed US options session",
        expected_release_weekdays=(1, 2, 3, 4, 5),
        refresh_group="cboe_indices",
        refresh_order=51,
    ),
    "cboe_vix9d": ExternalSourceProfile(
        source_id="cboe_vix9d",
        label="CBOE VIX9D",
        cadence="daily",
        max_age_days=6,
        warn_age_days=4,
        primary="CBOE official VIX9D history CSV",
        fallback="freeze last certified CBOE history; Yahoo is witness only",
        decision_role="auxiliary",
        soft_record_names=("cboe_indices",),
        feature_flag="use_cboe_official_indices",
        decision_weight=0.0,
        pit_rule="completed_us_session_plus_yahoo_witness",
        slo_key="cboe_indices",
        publication_schedule="after each completed US options session",
        expected_release_weekdays=(1, 2, 3, 4, 5),
        refresh_group="cboe_indices",
        refresh_order=52,
    ),
    "cboe_skew": ExternalSourceProfile(
        source_id="cboe_skew",
        label="CBOE SKEW",
        cadence="daily",
        max_age_days=6,
        warn_age_days=4,
        primary="CBOE official SKEW history CSV",
        fallback="freeze last certified CBOE history; Yahoo is witness only",
        decision_role="strategy",
        soft_record_names=("cboe_indices",),
        feature_flag="use_cboe_official_indices",
        decision_weight=6.0,
        pit_rule="completed_us_session_plus_yahoo_witness",
        slo_key="cboe_indices",
        publication_schedule="after each completed US options session",
        expected_release_weekdays=(1, 2, 3, 4, 5),
        refresh_group="cboe_indices",
        refresh_order=53,
    ),
    "cboe_vvix": ExternalSourceProfile(
        source_id="cboe_vvix",
        label="CBOE VVIX",
        cadence="daily",
        max_age_days=6,
        warn_age_days=4,
        primary="CBOE official VVIX history CSV",
        fallback="freeze last certified CBOE history; Yahoo is witness only",
        decision_role="strategy",
        soft_record_names=("cboe_indices",),
        feature_flag="use_cboe_official_indices",
        decision_weight=6.0,
        pit_rule="completed_us_session_plus_yahoo_witness",
        slo_key="cboe_indices",
        publication_schedule="after each completed US options session",
        expected_release_weekdays=(1, 2, 3, 4, 5),
        refresh_group="cboe_indices",
        refresh_order=54,
    ),
    "cboe_equity_pcr": ExternalSourceProfile(
        source_id="cboe_equity_pcr",
        label="CBOE Equity Put/Call",
        cadence="daily",
        max_age_days=6,
        warn_age_days=4,
        primary="CBOE daily market statistics",
        fallback="keep last validated CBOE observation",
        decision_role="strategy",
        soft_record_names=("cboe_pcr",),
        feature_flag="data_cboe_pcr",
        decision_weight=2.0,
        pit_rule="observation_date_plus_one_day",
        slo_key="cboe_pcr",
        publication_schedule="after each completed US options session",
        expected_release_weekdays=(1, 2, 3, 4, 5),
        refresh_order=40,
    ),
    "cot_nq": ExternalSourceProfile(
        source_id="cot_nq",
        label="CFTC NQ Commitments of Traders",
        cadence="weekly",
        max_age_days=13,
        warn_age_days=10,
        primary="CFTC public reporting API",
        fallback="keep last validated weekly report",
        decision_role="strategy",
        soft_record_names=("cot_nq",),
        feature_flag="data_cot_nq",
        decision_weight=4.0,
        pit_rule="tuesday_observation_friday_publication",
        publication_schedule="Friday publication for Tuesday CFTC positions",
        expected_release_weekdays=(5,),
        refresh_order=41,
    ),
    "occ_equity_pcr": ExternalSourceProfile(
        source_id="occ_equity_pcr",
        label="OCC Weekly Equity Put/Call",
        cadence="weekly",
        max_age_days=13,
        warn_age_days=10,
        primary="OCC weekly volume report",
        fallback="keep local immutable history",
        decision_role="research",
        decision_weight=0.0,
        pit_rule="week_ending_friday_plus_one_day",
        active=False,
        publication_schedule="weekly after the Friday OCC volume report",
        expected_release_weekdays=(5,),
        refresh_order=42,
    ),
    "btc_funding_basis": ExternalSourceProfile(
        source_id="btc_funding_basis",
        label="BTC Funding / Basis / DVOL",
        cadence="daily",
        max_age_days=6,
        warn_age_days=4,
        primary="Deribit public API",
        fallback="OKX funding API",
        decision_role="research",
        soft_record_names=("btc_funding_basis",),
        feature_flag="data_btc_funding",
        decision_weight=0.0,
        pit_rule="exchange_timestamp_utc_day",
        feature_default=True,
        publication_schedule="continuous exchange feed, certified once per UTC day",
        expected_release_weekdays=(0, 1, 2, 3, 4, 5, 6),
        refresh_order=43,
    ),
}


def all_source_ids() -> tuple[str, ...]:
    return tuple(
        profile.source_id
        for profile in sorted(
            PROFILES.values(),
            key=lambda value: (value.refresh_order, value.source_id),
        )
    )


def configured_refresh_source_ids(config: dict[str, Any]) -> tuple[str, ...]:
    features = (config or {}).get("features") or {}
    fred_group = "exact_fred" if bool(features.get("use_fred_vintage_pit", False)) else "legacy_fred"
    include_cboe = bool(features.get("use_cboe_official_indices", False))
    allowed_groups = {fred_group, "common"}
    if include_cboe:
        allowed_groups.add("cboe_indices")
    return tuple(
        source_id
        for source_id in all_source_ids()
        if PROFILES[source_id].refresh_group in allowed_groups
    )


def import_source_ids() -> tuple[str, ...]:
    return tuple(
        source_id
        for source_id in all_source_ids()
        if PROFILES[source_id].import_globs
    )


def display_source_ids() -> tuple[str, ...]:
    return all_source_ids()


def profile_for(source_id: str) -> ExternalSourceProfile | None:
    return PROFILES.get(str(source_id))


def effective_source_profile(
    config: dict[str, Any],
    source_id: str,
) -> ExternalSourceProfile | None:
    """Return source metadata with its runtime SLO resolved from config."""
    profile = profile_for(source_id)
    if profile is None:
        return None
    slo = (config or {}).get("soft_data_slo") or {}
    per_source = slo.get("max_age_days") or {}
    key = profile.slo_key or profile.source_id
    configured = per_source.get(key, slo.get("default_max_age_days"))
    max_age = profile.max_age_days if configured is None else max(0, int(configured))
    active = profile.active
    if profile.feature_flag:
        active = bool(
            ((config or {}).get("features") or {}).get(
                profile.feature_flag,
                profile.feature_default,
            )
        )
    resolved = replace(
        profile,
        max_age_days=max_age,
        warn_age_days=max(0, max_age - 2),
        active=active,
    )
    if (
        source_id in {"dollar", "real_rate", "fred_net_liquidity"}
        and bool(((config or {}).get("features") or {}).get("use_fred_vintage_pit", False))
    ):
        resolved = replace(
            resolved,
            primary="FRED/ALFRED exact vintage event store",
            fallback="freeze last certified exact-vintage canonical",
            pit_rule="exact_realtime_start_vintage",
        )
    return resolved


def enrich_source_status(
    row: dict[str, Any],
    *,
    today: date | None = None,
    profile: ExternalSourceProfile | None = None,
    official_artifact_ready: bool = False,
) -> dict[str, Any]:
    source_id = str(row.get("source_id") or "")
    profile = profile or profile_for(source_id)
    out = dict(row)
    if profile is None:
        return out
    day = today or shanghai_today()
    out.update(profile.to_dict())
    latest = str(
        row.get("latest_promoted_as_of")
        or row.get("latest_normalized_as_of")
        or ""
    )[:10]
    age_days = _age_days(latest, day)
    out["age_days"] = age_days
    out["freshness_status"] = _freshness_status(age_days, profile)
    out["failure_kind"] = _failure_kind(row)
    out["official_artifact_ready"] = bool(official_artifact_ready)
    out["migration_readiness"] = _migration_readiness(out, profile)
    out["lifecycle_status"] = _lifecycle_status(out, profile, day)
    out["migration_status"] = _migration_status(
        out,
        profile,
        day,
    )
    if (
        _same_day_successful_check(out, day)
        and out["freshness_status"] in {"DUE_SOON", "STALE"}
    ):
        out["publisher_status"] = "UNCHANGED_AFTER_REFRESH"
        out["publisher_note"] = "official source checked today; publisher has not posted a newer observation"
    out["next_action"] = _next_action(out, profile)
    return out


def import_files(profile: ExternalSourceProfile) -> list[Path]:
    matches: list[Path] = []
    for pattern in profile.import_globs:
        matches.extend(Path(path).expanduser() for path in glob.glob(str(Path(pattern).expanduser())))
    unique = {path.resolve(): path for path in matches if path.is_file()}
    matches = list(unique.values())
    matches.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return matches


def latest_import_file(profile: ExternalSourceProfile) -> Path | None:
    matches = import_files(profile)
    if not matches:
        return None
    return matches[0]


def _age_days(value: str, today: date) -> int | None:
    if not value:
        return None
    try:
        return max(0, (today - date.fromisoformat(value)).days)
    except ValueError:
        return None


def _freshness_status(age_days: int | None, profile: ExternalSourceProfile) -> str:
    if age_days is None:
        return "UNKNOWN"
    if age_days > profile.max_age_days:
        return "STALE"
    if age_days >= profile.warn_age_days:
        return "DUE_SOON"
    return "OK"


def _failure_kind(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "").upper()
    if status == "OK":
        return "NONE"
    text = " ".join(
        str(row.get(key) or "")
        for key in ("status", "error_type", "error_message", "error", "message")
    ).lower()
    if any(token in text for token in ("auth", "blocked", "imperva", "subscription", "login", "member")):
        return "AUTH_REQUIRED"
    if status == "MISSING":
        return "NO_LEDGER"
    return "FETCH_OR_PARSE"


def _same_day_successful_check(row: dict[str, Any], today: date) -> bool:
    if str(row.get("status") or "") != "OK":
        return False
    checked = _date_from_timestamp(row.get("finished_at") or row.get("latest_finished_at"))
    return checked == today


def _migration_status(
    row: dict[str, Any],
    profile: ExternalSourceProfile,
    today: date,
) -> str:
    if profile.source_id == "naaim_exposure" and profile.migration_deadline:
        try:
            deadline = date.fromisoformat(profile.migration_deadline)
        except ValueError:
            deadline = today
        readiness = str(row.get("migration_readiness") or "")
        if readiness == "AUTOMATIC_PRIMARY":
            return "SUBSCRIBER_READY"
        if today < deadline:
            return "MIGRATION_DUE"
        if str(row.get("lifecycle_status") or "") == "RETIRED_PAYWALL":
            return "RETIRED_PAYWALL"
        checked = _date_from_timestamp(row.get("finished_at") or row.get("latest_finished_at"))
        if readiness == "AUTOMATIC_PUBLIC" and checked is not None and checked > deadline:
            return "PUBLIC_OFFICIAL_STABLE"
        return "ACTION_REQUIRED"
    if profile.source_id == "aaii_sentiment":
        if row.get("official_artifact_ready"):
            return "OFFICIAL_FILE_READY"
        if str(row.get("freshness_status") or "") == "STALE":
            return "ACTION_REQUIRED"
        return "MONITORED"
    return "STABLE"


def _lifecycle_status(
    row: dict[str, Any],
    profile: ExternalSourceProfile,
    today: date,
) -> str:
    if profile.lifecycle_policy != "RETIRED_PAYWALL":
        return "ACTIVE"
    try:
        effective = date.fromisoformat(str(profile.lifecycle_effective_date or ""))
    except ValueError:
        effective = today
    if today < effective:
        return "ACTIVE"
    readiness = str(row.get("migration_readiness") or "")
    if readiness == "AUTOMATIC_PRIMARY":
        return "ACTIVE_SUBSCRIBER"
    checked = _date_from_timestamp(row.get("finished_at") or row.get("latest_finished_at"))
    if (
        readiness == "AUTOMATIC_PUBLIC"
        and checked is not None
        and checked > effective
        and str(row.get("freshness_status") or "") in {"OK", "DUE_SOON"}
    ):
        return "ACTIVE_PUBLIC"
    return "RETIRED_PAYWALL"


def _migration_readiness(
    row: dict[str, Any],
    profile: ExternalSourceProfile,
) -> str:
    if profile.source_id != "naaim_exposure":
        return "NOT_APPLICABLE"
    if str(row.get("status") or "").upper() != "OK":
        return "NOT_EVIDENCED"
    if str(row.get("freshness_status") or "") in {"STALE", "UNKNOWN"}:
        return "NOT_EVIDENCED"
    channel = str(
        row.get("latest_source_channel")
        or row.get("source_channel")
        or ""
    )
    if channel == "naaim_subscriber":
        return "AUTOMATIC_PRIMARY"
    if channel == "naaim_public_workbook":
        return "AUTOMATIC_PUBLIC"
    if channel == "manual_official_file":
        return "MANUAL_FALLBACK"
    return "NOT_EVIDENCED"


def _date_from_timestamp(value: Any) -> date | None:
    return timestamp_to_shanghai_date(value)


def _next_action(row: dict[str, Any], profile: ExternalSourceProfile) -> str:
    source_id = profile.source_id
    failure = str(row.get("failure_kind") or "")
    freshness = str(row.get("freshness_status") or "")
    migration = str(row.get("migration_status") or "")
    if migration == "ACTION_REQUIRED" and source_id == "aaii_sentiment":
        return "download the current official sentiment file and import it through ExternalSourceRunner"
    if migration == "ACTION_REQUIRED" and source_id == "naaim_exposure":
        return "NAAIM migration deadline passed; verify official workbook access and import the current issue"
    if migration == "RETIRED_PAYWALL" and source_id == "naaim_exposure":
        return "NAAIM public feed retired behind paywall; certified history frozen; weekly official-access probe only"
    if migration == "SUBSCRIBER_READY":
        return "NAAIM subscriber workbook is certified; monitor weekly automatic refresh"
    if migration == "PUBLIC_OFFICIAL_STABLE":
        return "NAAIM public official workbook remains automated after the migration deadline; retain import fallback"
    if migration == "OFFICIAL_FILE_READY":
        return f"validate and import the staged official file for {source_id}"
    if str(row.get("publisher_status") or "") == "UNCHANGED_AFTER_REFRESH":
        return f"official source checked today; wait for publisher update for {source_id}"
    if failure == "AUTH_REQUIRED" and profile.import_globs:
        if source_id == "aaii_sentiment":
            return "download official sentiment.xls, then run refresh_external --source aaii_sentiment --import-file PATH"
        if source_id == "naaim_exposure":
            return "download official NAAIM workbook, then run refresh_external --source naaim_exposure --import-file PATH"
    if freshness == "STALE":
        return f"run refresh_external --source {source_id}; if still stale use {profile.fallback}"
    if freshness == "DUE_SOON":
        return f"watch next publication; run refresh_external --source {source_id} if tomorrow still unchanged"
    if migration == "MIGRATION_DUE" and source_id == "naaim_exposure":
        return f"before {profile.migration_deadline}, verify official workbook automation and retained import fallback"
    return f"run refresh_external --source {source_id}"
