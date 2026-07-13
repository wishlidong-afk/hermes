from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .registry import latest_frame_date
from .clock import shanghai_today, timestamp_to_shanghai_date


LEDGER_NAME = "external_source_runs.jsonl"


def ledger_path(archive_dir: Path) -> Path:
    return Path(archive_dir) / "external_sources" / LEDGER_NAME


def append_source_run(archive_dir: Path, record: dict[str, Any]) -> Path:
    path = ledger_path(archive_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
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

    outcomes = sorted(
        (operating_day, _day_succeeded(rows))
        for operating_day, rows in daily_rows.items()
    )
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
    return {
        "success_rate_30d": rate_30,
        "success_rate_90d": rate_90,
        "samples_30d": samples_30,
        "samples_90d": samples_90,
        "consecutive_failures": consecutive_failures,
        "last_success_at": last_success_at,
    }


def _day_succeeded(rows: list[dict[str, Any]]) -> bool:
    invalidated_inputs: set[str] = set()
    for row in reversed(rows):
        input_hash = str(row.get("input_hash") or "")
        if str(row.get("status") or "").upper() == "OK":
            if not input_hash or input_hash not in invalidated_inputs:
                return True
        elif input_hash:
            invalidated_inputs.add(input_hash)
    return False


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
