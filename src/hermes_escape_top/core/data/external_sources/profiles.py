from __future__ import annotations

import glob
from dataclasses import asdict, dataclass
from datetime import date
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
    ),
    "real_rate": ExternalSourceProfile(
        source_id="real_rate",
        label="10Y Real Rate",
        cadence="daily",
        max_age_days=6,
        warn_age_days=4,
        primary="FRED DFII10 API",
        fallback="rerun FRED external source",
    ),
    "fred_net_liquidity": ExternalSourceProfile(
        source_id="fred_net_liquidity",
        label="FRED Net Liquidity",
        cadence="daily",
        max_age_days=6,
        warn_age_days=4,
        primary="FRED WALCL/WTREGEN/RRP APIs",
        fallback="rerun FRED external source",
    ),
    "naaim_exposure": ExternalSourceProfile(
        source_id="naaim_exposure",
        label="NAAIM Exposure",
        cadence="weekly",
        max_age_days=13,
        warn_age_days=10,
        primary="NAAIM official XLSX",
        fallback="official workbook import",
        import_globs=(
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
        import_globs=(
            "~/Downloads/sentiment*.xls",
            "~/Downloads/sentiment*.xlsx",
            "~/Downloads/sentiment*.csv",
        ),
    ),
}


def profile_for(source_id: str) -> ExternalSourceProfile | None:
    return PROFILES.get(str(source_id))


def enrich_source_status(row: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    source_id = str(row.get("source_id") or "")
    profile = profile_for(source_id)
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


def _next_action(row: dict[str, Any], profile: ExternalSourceProfile) -> str:
    source_id = profile.source_id
    failure = str(row.get("failure_kind") or "")
    freshness = str(row.get("freshness_status") or "")
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
