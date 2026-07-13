from __future__ import annotations

import glob
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExternalSourceProfile:
    source_id: str
    label: str
    cadence: str
    max_age_days: int
    warn_age_days: int
    primary: str
    fallback: str
    import_globs: tuple[str, ...] = ()
    feature_flag: str | None = None
    decision_weight: float = 0.0
    automation_mode: str = "api"
    pit_rule: str = "observation_date"
    migration_deadline: str | None = None
    slo_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["import_globs"] = list(self.import_globs)
        return payload


PROFILES: dict[str, ExternalSourceProfile] = {
    "dollar": ExternalSourceProfile(
        source_id="dollar",
        label="DXY / Dollar",
        cadence="weekly",
        max_age_days=10,
        warn_age_days=8,
        primary="FRED DTWEXBGS API",
        fallback="rerun FRED external source",
        feature_flag="data_dollar",
        decision_weight=4.0,
        pit_rule="observation_date_plus_one_day",
    ),
    "real_rate": ExternalSourceProfile(
        source_id="real_rate",
        label="10Y Real Rate",
        cadence="daily",
        max_age_days=6,
        warn_age_days=4,
        primary="FRED DFII10 API",
        fallback="rerun FRED external source",
        feature_flag="data_real_rate",
        decision_weight=4.0,
        pit_rule="observation_date_plus_one_day",
    ),
    "fred_net_liquidity": ExternalSourceProfile(
        source_id="fred_net_liquidity",
        label="FRED Net Liquidity",
        cadence="daily",
        max_age_days=6,
        warn_age_days=4,
        primary="FRED WALCL/WTREGEN/RRP APIs",
        fallback="rerun FRED external source",
        feature_flag="data_net_liquidity",
        decision_weight=4.0,
        pit_rule="observation_date_plus_one_day",
        slo_key="net_liquidity",
    ),
    "naaim_exposure": ExternalSourceProfile(
        source_id="naaim_exposure",
        label="NAAIM Exposure",
        cadence="weekly",
        max_age_days=13,
        warn_age_days=10,
        primary="NAAIM official XLSX",
        fallback="official workbook import",
        feature_flag="data_naaim",
        decision_weight=2.0,
        automation_mode="official_file",
        pit_rule="issue_date_plus_one_day",
        migration_deadline="2026-08-01",
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
        primary="AAII official sentiment.xls",
        fallback="browser download + official file import",
        feature_flag="data_aaii",
        decision_weight=2.0,
        automation_mode="browser_assisted",
        pit_rule="issue_date",
        import_globs=(
            "~/.hermes/external_imports/sentiment*.xls",
            "~/.hermes/external_imports/sentiment*.xlsx",
            "~/.hermes/external_imports/sentiment*.csv",
            "~/Downloads/sentiment*.xls",
            "~/Downloads/sentiment*.xlsx",
            "~/Downloads/sentiment*.csv",
        ),
    ),
}


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
    if configured is None:
        return profile
    max_age = max(0, int(configured))
    return replace(
        profile,
        max_age_days=max_age,
        warn_age_days=max(0, max_age - 2),
    )


def enrich_source_status(
    row: dict[str, Any],
    *,
    today: date | None = None,
    profile: ExternalSourceProfile | None = None,
) -> dict[str, Any]:
    source_id = str(row.get("source_id") or "")
    profile = profile or profile_for(source_id)
    out = dict(row)
    if profile is None:
        return out
    out.update(profile.to_dict())
    latest = str(
        row.get("latest_promoted_as_of")
        or row.get("latest_normalized_as_of")
        or ""
    )[:10]
    age_days = _age_days(latest, today or date.today())
    out["age_days"] = age_days
    out["freshness_status"] = _freshness_status(age_days, profile)
    out["failure_kind"] = _failure_kind(row)
    if (
        _same_day_successful_check(out, today or date.today())
        and out["freshness_status"] in {"DUE_SOON", "STALE"}
    ):
        out["publisher_status"] = "UNCHANGED_AFTER_REFRESH"
        out["publisher_note"] = "official source checked today; publisher has not posted a newer observation"
    out["next_action"] = _next_action(out, profile)
    return out


def latest_import_file(profile: ExternalSourceProfile) -> Path | None:
    matches: list[Path] = []
    for pattern in profile.import_globs:
        matches.extend(Path(path).expanduser() for path in glob.glob(str(Path(pattern).expanduser())))
    matches = [path for path in matches if path.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


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


def _date_from_timestamp(value: Any) -> date | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _next_action(row: dict[str, Any], profile: ExternalSourceProfile) -> str:
    source_id = profile.source_id
    failure = str(row.get("failure_kind") or "")
    freshness = str(row.get("freshness_status") or "")
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
    return f"run refresh_external --source {source_id}"
