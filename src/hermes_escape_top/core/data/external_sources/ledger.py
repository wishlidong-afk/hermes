from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from ..jsonl import append_jsonl_records
from .registry import latest_frame_date
from .clock import shanghai_today, timestamp_to_shanghai_date


LEDGER_NAME = "external_source_runs.jsonl"
CANONICAL_EVIDENCE_OK_STATUSES = frozenset({"", "MATCH"})
CANONICAL_EVIDENCE_CRITICAL_STATUSES = frozenset({"EVIDENCE_DRIFT", "MISSING_CANONICAL"})
STAGE_FIELDS = {
    "transport": "transport_status",
    "parse": "parse_status",
    "validation": "validation_status",
    "promotion": "promotion_status",
}
MIN_RELIABILITY_SAMPLES = 5
MIN_EXPECTED_RELEASE_SAMPLES = 5


def canonical_evidence_issue(row: dict[str, Any]) -> str:
    """Return the evidence problem for an active source, if any."""
    if row.get("active") is False:
        return ""
    status = str(row.get("evidence_status") or "")
    return "" if status in CANONICAL_EVIDENCE_OK_STATUSES else status


def certified_canonical_is_current(row: dict[str, Any]) -> bool:
    return (
        str(row.get("status") or "") == "OK"
        and str(row.get("freshness_status") or "") in {"OK", "DUE_SOON"}
        and str(row.get("evidence_status") or "") == "MATCH"
    )


def ledger_path(archive_dir: Path) -> Path:
    return Path(archive_dir) / "external_sources" / LEDGER_NAME


def append_source_run(archive_dir: Path, record: dict[str, Any]) -> Path:
    path = ledger_path(archive_dir)
    append_jsonl_records(path, [record])
    return path


def iter_source_runs(archive_dir: Path) -> Iterable[dict[str, Any]]:
    path = ledger_path(archive_dir)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def latest_source_run(archive_dir: Path, source_id: str) -> dict[str, Any] | None:
    latest = None
    for row in iter_source_runs(archive_dir):
        if row.get("source_id") == source_id:
            latest = row
    return latest


def latest_successful_source_run(archive_dir: Path, source_id: str) -> dict[str, Any] | None:
    invalidated_inputs: set[str] = set()
    for row in reversed(list(iter_source_runs(archive_dir))):
        if row.get("source_id") != source_id:
            continue
        input_hash = str(row.get("input_hash") or "")
        if str(row.get("status") or "") == "OK":
            if input_hash and input_hash in invalidated_inputs:
                continue
            return row
        if input_hash:
            invalidated_inputs.add(input_hash)
    return None


def source_reliability(
    archive_dir: Path,
    source_id: str,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Aggregate one outcome per Asia/Shanghai operating day.

    A successful retry makes that day's outcome successful; repeated attempts
    never inflate the sample count.
    """
    day = today or shanghai_today()
    daily_rows: dict[date, list[dict[str, Any]]] = {}
    for row in iter_source_runs(archive_dir):
        if row.get("source_id") != source_id:
            continue
        timestamp = row.get("finished_at") or row.get("started_at")
        operating_day = _operating_day(timestamp)
        if operating_day is None or operating_day > day:
            continue
        daily_rows.setdefault(operating_day, []).append(row)

    daily_successes = sorted(
        (operating_day, _successful_day_row(rows))
        for operating_day, rows in daily_rows.items()
    )
    outcomes = [(operating_day, row is not None) for operating_day, row in daily_successes]
    latest_ok = latest_successful_source_run(archive_dir, source_id)
    last_success_at = None
    if latest_ok is not None:
        last_success_at = str(latest_ok.get("finished_at") or latest_ok.get("started_at") or "") or None
    rate_30, samples_30 = _window_success_rate(outcomes, day - timedelta(days=29))
    rate_90, samples_90 = _window_success_rate(outcomes, day - timedelta(days=89))
    consecutive_failures = 0
    for _outcome_day, ok in reversed(outcomes):
        if ok:
            break
        consecutive_failures += 1
    last_recovery_at = None
    previous_ok: bool | None = None
    for _day_value, successful_row in daily_successes:
        current_ok = successful_row is not None
        if current_ok and previous_ok is False:
            last_recovery_at = str(
                successful_row.get("finished_at")
                or successful_row.get("started_at")
                or ""
            ) or None
        previous_ok = current_ok

    stage_reliability: dict[str, dict[str, Any]] = {}
    for stage, field in STAGE_FIELDS.items():
        stage_outcomes = [
            (operating_day, outcome)
            for operating_day, rows in sorted(daily_rows.items())
            if (outcome := _stage_day_outcome(rows, field)) is not None
        ]
        stage_rate_30, stage_samples_30 = _window_success_rate(
            stage_outcomes,
            day - timedelta(days=29),
        )
        stage_rate_90, stage_samples_90 = _window_success_rate(
            stage_outcomes,
            day - timedelta(days=89),
        )
        stage_failures = 0
        for _outcome_day, ok in reversed(stage_outcomes):
            if ok:
                break
            stage_failures += 1
        stage_reliability[stage] = {
            "success_rate_30d": stage_rate_30,
            "success_rate_90d": stage_rate_90,
            "samples_30d": stage_samples_30,
            "samples_90d": stage_samples_90,
            "consecutive_failures": stage_failures,
            "evidence_status_30d": _sample_evidence_status(stage_samples_30),
            "evidence_status_90d": _sample_evidence_status(stage_samples_90),
        }

    advancement_outcomes = [
        (operating_day, bool(row.get("advanced")))
        for operating_day, row in daily_successes
        if row is not None and isinstance(row.get("advanced"), bool)
    ]
    advancement_rate_30, advancement_samples_30 = _window_success_rate(
        advancement_outcomes,
        day - timedelta(days=29),
    )
    advancement_rate_90, advancement_samples_90 = _window_success_rate(
        advancement_outcomes,
        day - timedelta(days=89),
    )
    last_advanced_at = None
    for _day_value, row in reversed(daily_successes):
        if row is not None and row.get("advanced") is True:
            last_advanced_at = str(row.get("finished_at") or row.get("started_at") or "") or None
            break
    expected_release = _expected_release_metrics(
        source_id,
        daily_rows,
        daily_successes,
        day,
    )
    start_30 = day - timedelta(days=29)
    channel_successes: dict[str, int] = {}
    for operating_day, row in daily_successes:
        if operating_day < start_30 or row is None:
            continue
        channel = str(row.get("source_channel") or "").strip()
        if channel:
            channel_successes[channel] = channel_successes.get(channel, 0) + 1
    fallback_rescues_7d = sum(
        1
        for operating_day, row in daily_successes
        if operating_day >= day - timedelta(days=6)
        and row is not None
        and row.get("fallback_used") is True
    )
    primary_rate = None
    instrumented = [
        (operating_day, row)
        for operating_day, row in daily_successes
        if operating_day >= start_30
        and row is not None
        and (
            row.get("primary_source")
            or (source_id == "aaii_sentiment" and row.get("source_channel"))
        )
    ]
    primary_samples = len(instrumented)
    if primary_samples:
        primary_rate = round(
            sum(
                1
                for _day_value, row in instrumented
                if row is not None
                and str(row.get("source_channel") or "")
                == str(
                    row.get("primary_source")
                    or ("public_html" if source_id == "aaii_sentiment" else "")
                )
            )
            / primary_samples
            * 100.0,
            2,
        )
    result = {
        "success_rate_30d": rate_30,
        "success_rate_90d": rate_90,
        "samples_30d": samples_30,
        "samples_90d": samples_90,
        "reliability_evidence_status_30d": _sample_evidence_status(samples_30),
        "reliability_evidence_status_90d": _sample_evidence_status(samples_90),
        "consecutive_failures": consecutive_failures,
        "last_success_at": last_success_at,
        "last_recovery_at": last_recovery_at,
        "stage_reliability": stage_reliability,
        "advancement_rate_30d": advancement_rate_30,
        "advancement_rate_90d": advancement_rate_90,
        "advancement_samples_30d": advancement_samples_30,
        "advancement_samples_90d": advancement_samples_90,
        "advancement_evidence_status_30d": _sample_evidence_status(advancement_samples_30),
        "advancement_evidence_status_90d": _sample_evidence_status(advancement_samples_90),
        "last_advanced_at": last_advanced_at,
        "channel_successes_30d": dict(sorted(channel_successes.items())),
        "fallback_rescues_7d": fallback_rescues_7d,
        "primary_success_rate_30d": primary_rate,
        "primary_samples_30d": primary_samples,
        "primary_evidence_status_30d": _sample_evidence_status(primary_samples),
        "latest_source_channel": (
            str(latest_ok.get("source_channel") or "") or None
            if latest_ok is not None
            else None
        ),
        "latest_primary_source": (
            str(latest_ok.get("primary_source") or "") or None
            if latest_ok is not None
            else None
        ),
        "latest_fallback_used": (
            latest_ok.get("fallback_used")
            if latest_ok is not None and "fallback_used" in latest_ok
            else None
        ),
        "latest_primary_failure": (
            str(latest_ok.get("primary_failure") or "") or None
            if latest_ok is not None
            else None
        ),
    }
    result.update(expected_release)
    for stage, metrics in stage_reliability.items():
        for key, value in metrics.items():
            result[f"{stage}_{key}"] = value
    return result


def _sample_evidence_status(samples: int, minimum: int = MIN_RELIABILITY_SAMPLES) -> str:
    return "SUFFICIENT" if int(samples) >= int(minimum) else "INSUFFICIENT_EVIDENCE"


def _day_succeeded(rows: list[dict[str, Any]]) -> bool:
    return _successful_day_row(rows) is not None


def _successful_day_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    invalidated_inputs: set[str] = set()
    for row in reversed(rows):
        input_hash = str(row.get("input_hash") or "")
        if str(row.get("status") or "").upper() == "OK":
            if not input_hash or input_hash not in invalidated_inputs:
                return row
        elif input_hash:
            invalidated_inputs.add(input_hash)
    return None


def _stage_day_outcome(rows: list[dict[str, Any]], field: str) -> bool | None:
    statuses = [str(row.get(field) or "").upper() for row in rows]
    attempted = [status for status in statuses if status not in {"", "NOT_RUN"}]
    if not attempted:
        return None
    successful = {"OK"}
    if field == "promotion_status":
        successful.add("UNCHANGED")
    return any(status in successful for status in attempted)


def _expected_release_metrics(
    source_id: str,
    daily_rows: dict[date, list[dict[str, Any]]],
    daily_successes: list[tuple[date, dict[str, Any] | None]],
    day: date,
) -> dict[str, Any]:
    from .profiles import profile_for

    profile = profile_for(source_id)
    weekdays = tuple(getattr(profile, "expected_release_weekdays", ()) or ())
    policy = str(getattr(profile, "expected_release_policy", "weekday") or "weekday")
    instrumented_days = sorted(
        operating_day
        for operating_day, rows in daily_rows.items()
        if any("advanced" in row for row in rows)
    )
    empty = {
        "expected_release_samples_30d": 0,
        "expected_release_samples_90d": 0,
        "expected_release_advanced_30d": 0,
        "expected_release_advanced_90d": 0,
        "expected_release_advance_rate_30d": None,
        "expected_release_advance_rate_90d": None,
        "expected_release_evidence_status_30d": "INSUFFICIENT_EVIDENCE",
        "expected_release_evidence_status_90d": "INSUFFICIENT_EVIDENCE",
        "latest_expected_release_date": None,
        "latest_expected_release_status": "UNINSTRUMENTED",
        "latest_expected_release_grace_status": "UNINSTRUMENTED",
        "latest_publisher_release_id": None,
        "latest_publisher_content_fingerprint": None,
        "latest_publisher_calendar_status": "UNINSTRUMENTED",
        "latest_publisher_recovery_evidence": None,
        "expected_release_enforcement": "WARNING_ONLY",
    }
    if profile is None:
        return empty
    evidence_rows = [
        (operating_day, row)
        for operating_day, rows in sorted(daily_rows.items())
        for row in rows
        if str(row.get("publisher_calendar_status") or "") == "VERIFIED"
        and isinstance(
            row.get("publisher_expected_release_dates"),
            (list, tuple),
        )
    ]
    latest_evidence = evidence_rows[-1][1] if evidence_rows else None
    availability_lag = max(
        0,
        int(getattr(profile, "publisher_availability_lag_days", 0) or 0),
    )
    tolerance_days = max(
        availability_lag,
        max(0, int(getattr(profile, "expected_advance_grace_days", 0))),
    )
    if policy in {"fred_release_calendar", "publisher_issue_sequence"}:
        if not evidence_rows:
            return empty
        all_publisher_days = sorted(
            {
                parsed
                for _operating_day, row in evidence_rows
                for value in row.get("publisher_expected_release_dates") or []
                if (parsed := _parse_date(value)) is not None and parsed <= day
            }
        )
        if not all_publisher_days:
            return empty
        first_instrumented = evidence_rows[0][0]
        latest_due = all_publisher_days[-1]
        expected_days = [
            expected_day
            for expected_day in all_publisher_days
            if expected_day + timedelta(days=tolerance_days) >= first_instrumented
            or expected_day == latest_due
        ]
    else:
        if not weekdays or not instrumented_days:
            return empty
        start = instrumented_days[0]
        expected_days = []
        cursor = start
        while cursor <= day:
            if cursor.weekday() in weekdays:
                expected_days.append(cursor)
            cursor += timedelta(days=1)
    if not expected_days:
        return empty

    grace_days = max(0, int(getattr(profile, "expected_advance_grace_days", 0)))
    tolerance_days = max(availability_lag, grace_days)
    advanced_days = {
        operating_day
        for operating_day, row in daily_successes
        if row is not None and row.get("advanced") is True
    }
    matches: dict[date, date] = {}
    unused_advanced = set(advanced_days)
    for expected_day in expected_days:
        candidates = sorted(
            advanced_day
            for advanced_day in unused_advanced
            if expected_day
            <= advanced_day
            <= expected_day + timedelta(days=tolerance_days)
        )
        if candidates:
            matches[expected_day] = candidates[0]
            unused_advanced.remove(candidates[0])

    matured = [
        expected_day
        for expected_day in expected_days
        if expected_day
        + timedelta(days=tolerance_days)
        < day
    ]

    def window(days: int) -> tuple[int, int, float | None]:
        lower = day - timedelta(days=days - 1)
        selected = [expected_day for expected_day in matured if expected_day >= lower]
        advanced = sum(1 for expected_day in selected if expected_day in matches)
        rate = round(advanced / len(selected) * 100.0, 2) if selected else None
        return len(selected), advanced, rate

    samples_30, advanced_30, rate_30 = window(30)
    samples_90, advanced_90, rate_90 = window(90)
    latest_expected = expected_days[-1]
    if latest_expected in matches:
        latest_status = "ADVANCED"
    elif latest_expected + timedelta(days=tolerance_days) >= day:
        latest_status = "PENDING"
    else:
        latest_status = "MISSED"
    if latest_status == "ADVANCED":
        grace_status = "MATCHED"
    elif latest_status == "PENDING":
        grace_status = "IN_GRACE"
    else:
        grace_status = "EXPIRED"
    return {
        "expected_release_samples_30d": samples_30,
        "expected_release_samples_90d": samples_90,
        "expected_release_advanced_30d": advanced_30,
        "expected_release_advanced_90d": advanced_90,
        "expected_release_advance_rate_30d": rate_30,
        "expected_release_advance_rate_90d": rate_90,
        "expected_release_evidence_status_30d": _sample_evidence_status(
            samples_30,
            MIN_EXPECTED_RELEASE_SAMPLES,
        ),
        "expected_release_evidence_status_90d": _sample_evidence_status(
            samples_90,
            MIN_EXPECTED_RELEASE_SAMPLES,
        ),
        "latest_expected_release_date": latest_expected.isoformat(),
        "latest_expected_release_status": latest_status,
        "latest_expected_release_grace_status": grace_status,
        "latest_publisher_release_id": (
            str(latest_evidence.get("publisher_release_id") or "") or None
            if latest_evidence is not None
            else None
        ),
        "latest_publisher_content_fingerprint": (
            str(latest_evidence.get("publisher_content_fingerprint") or "") or None
            if latest_evidence is not None
            else None
        ),
        "latest_publisher_calendar_status": (
            str(latest_evidence.get("publisher_calendar_status") or "")
            if latest_evidence is not None
            else "UNINSTRUMENTED"
        ),
        "latest_publisher_recovery_evidence": (
            latest_evidence.get("publisher_recovery_evidence")
            if latest_evidence is not None
            else None
        ),
        "expected_release_enforcement": "WARNING_ONLY",
    }


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def source_status(
    archive_dir: Path,
    specs: Iterable[Any],
    *,
    today: date | None = None,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for spec in specs:
        latest = latest_source_run(archive_dir, spec.source_id)
        latest_ok = latest_successful_source_run(archive_dir, spec.source_id)
        if latest_ok is not None and latest is not None and str(latest.get("status") or "") != "OK":
            row = dict(latest_ok)
            row["latest_attempt_status"] = latest.get("status")
            row["latest_attempt_started_at"] = latest.get("started_at")
            row["latest_attempt_finished_at"] = latest.get("finished_at")
            row["latest_attempt_error_type"] = latest.get("error_type")
            row["latest_attempt_error_message"] = latest.get("error_message") or latest.get("error")
        else:
            row = latest or {"source_id": spec.source_id, "status": "MISSING"}
        row.update(_canonical_evidence(spec, latest_ok))
        row.update(source_reliability(archive_dir, spec.source_id, today=today))
        out[spec.source_id] = row
    return out


def _window_success_rate(outcomes: list[tuple[date, bool]], start: date) -> tuple[float | None, int]:
    selected = [ok for operating_day, ok in outcomes if operating_day >= start]
    if not selected:
        return None, 0
    return round(sum(1 for ok in selected if ok) / len(selected) * 100.0, 2), len(selected)


def _operating_day(value: Any) -> date | None:
    return timestamp_to_shanghai_date(value)


def _canonical_evidence(spec: Any, latest_ok: dict[str, Any] | None) -> dict[str, str]:
    target = Path(spec.target_path)
    if latest_ok is None:
        return {
            "evidence_status": "NO_LEDGER",
            "evidence_detail": "no successful promotion is recorded",
        }
    if not target.exists():
        return {
            "evidence_status": "MISSING_CANONICAL",
            "evidence_detail": f"canonical target missing: {target}",
        }
    expected_hash = str(latest_ok.get("canonical_sha256") or "")
    if not expected_hash:
        return {
            "evidence_status": "UNBOUND_LEGACY",
            "evidence_detail": "latest successful promotion has no canonical sha256; controlled runner migration required",
        }
    try:
        current_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    except OSError as exc:
        return {
            "evidence_status": "EVIDENCE_DRIFT",
            "evidence_detail": f"canonical target unreadable: {exc}",
        }
    if current_hash != expected_hash:
        return {
            "evidence_status": "EVIDENCE_DRIFT",
            "evidence_detail": f"canonical sha256 {current_hash} != promoted {expected_hash}",
        }
    expected_latest = str(
        latest_ok.get("canonical_latest_as_of")
        or latest_ok.get("latest_promoted_as_of")
        or ""
    )
    try:
        current_latest = latest_frame_date(spec, pd.read_csv(target)) or ""
    except Exception as exc:
        return {
            "evidence_status": "EVIDENCE_DRIFT",
            "evidence_detail": f"canonical target cannot be validated: {exc}",
        }
    if expected_latest and current_latest != expected_latest:
        return {
            "evidence_status": "EVIDENCE_DRIFT",
            "evidence_detail": f"canonical latest {current_latest} != promoted {expected_latest}",
        }
    return {
        "evidence_status": "MATCH",
        "evidence_detail": "canonical sha256 and latest date match promotion",
    }
