from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SCHEMA_VERSION = "hermes-decision-certification-v1"
MAX_DECISION_REVISIONS = 2
MAX_AUDIT_TAIL_BYTES = 64 * 1024 * 1024
SHANGHAI = ZoneInfo("Asia/Shanghai")


class DecisionRevisionConflict(RuntimeError):
    """Raised when a same-date official decision exceeds its revision budget."""


def build_scheduled_decision_evidence(
    payload: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    archive_dir: Path,
    package_root: Path,
    certified_at: datetime | None = None,
) -> dict[str, Any]:
    if str(payload.get("run_type") or "") != "scheduled":
        raise ValueError("decision certification requires run_type=scheduled")
    as_of = date.fromisoformat(str(payload.get("as_of") or "")[:10]).isoformat()
    snapshot_hash = str(payload.get("input_hash") or "")
    if not snapshot_hash:
        raise ValueError("decision certification requires input_hash")

    archive_dir = Path(archive_dir)
    package_root = Path(package_root)
    certified_at = certified_at or datetime.now(timezone.utc).astimezone(SHANGHAI)
    if certified_at.tzinfo is None:
        raise ValueError("decision certification timestamp must be timezone-aware")
    local_certified_at = certified_at.astimezone(SHANGHAI)
    finality = _bar_finality(as_of, local_certified_at)
    admission = payload.get("market_admission_status") or {}
    soft_data = payload.get("soft_data")
    soft_records = soft_data.get("records") if isinstance(soft_data, Mapping) else {}
    if not isinstance(soft_records, Mapping):
        soft_records = {}
    identity = {
        "as_of": as_of,
        "snapshot_hash": snapshot_hash,
        "soft_input_evidence_hash": _stable_hash(soft_records),
        "canonical_market_evidence_hash": _market_manifest_id(archive_dir),
        "config_hash": _stable_hash(config),
        "policy_hash": _policy_hash(package_root),
        "scorer_release_hash": _release_hash(package_root),
        "market_admission_operation_id": str(admission.get("operation_id") or ""),
        "market_admission_completed_through": str(admission.get("completed_through") or ""),
    }
    decision_hash = _stable_hash(identity)
    previous = _latest_scheduled_record(archive_dir / "audit_log.jsonl", as_of)
    revision, decision_id, supersedes, reason, previous_hash = _allocate_revision(
        as_of=as_of,
        decision_hash=decision_hash,
        finality=finality,
        previous=previous,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        **identity,
        "decision_hash": decision_hash,
        "decision_id": decision_id,
        "decision_revision": revision,
        "supersedes_decision_id": supersedes,
        "previous_decision_hash": previous_hash,
        "revision_reason": reason,
        "bar_finality": finality,
        "certified_at": local_certified_at.isoformat(),
        "revision_budget": MAX_DECISION_REVISIONS,
    }


def _allocate_revision(
    *,
    as_of: str,
    decision_hash: str,
    finality: str,
    previous: dict[str, Any] | None,
) -> tuple[int, str, str | None, str, str | None]:
    if previous is None:
        revision = 1
        return revision, _decision_id(as_of, decision_hash, revision, finality), None, "INITIAL_CERTIFICATION", None

    payload = previous["payload"]
    prior = payload.get("decision_evidence")
    if not isinstance(prior, dict) or prior.get("schema_version") != SCHEMA_VERSION:
        revision = 2
        legacy_id = _legacy_decision_id(as_of, previous)
        return (
            revision,
            _decision_id(as_of, decision_hash, revision, finality),
            legacy_id,
            "LEGACY_CERTIFICATION_SUPERSEDED",
            str(payload.get("input_hash") or "") or None,
        )

    previous_revision = int(prior.get("decision_revision") or 0)
    previous_id = str(prior.get("decision_id") or "")
    previous_hash = str(prior.get("decision_hash") or "")
    previous_finality = str(prior.get("bar_finality") or "")
    if previous_revision < 1 or not previous_id or not previous_hash:
        raise DecisionRevisionConflict("prior decision certification is incomplete")
    if previous_finality == "FINAL" and finality != "FINAL":
        raise DecisionRevisionConflict("bar finality cannot regress from FINAL")
    if previous_hash == decision_hash and previous_finality == finality:
        supersedes = str(prior.get("supersedes_decision_id") or "") or None
        reason = str(prior.get("revision_reason") or "") or "REPEAT_CERTIFICATION"
        raw_previous_hash = prior.get("previous_decision_hash")
        prior_previous_hash = str(raw_previous_hash) if raw_previous_hash is not None else None
        return previous_revision, previous_id, supersedes, reason, prior_previous_hash
    if previous_revision >= MAX_DECISION_REVISIONS:
        raise DecisionRevisionConflict(
            f"same-date decision revision budget exhausted for {as_of}: r{previous_revision}"
        )

    revision = previous_revision + 1
    if previous_hash != decision_hash and previous_finality == "PROVISIONAL" and finality == "FINAL":
        reason = "CANONICAL_EVIDENCE_CHANGED_AND_FINALIZED"
    elif previous_hash != decision_hash:
        reason = "CANONICAL_EVIDENCE_CHANGED"
    else:
        reason = "BAR_FINALITY_ADVANCED"
    return (
        revision,
        _decision_id(as_of, decision_hash, revision, finality),
        previous_id,
        reason,
        previous_hash,
    )


def _bar_finality(as_of: str, certified_at: datetime) -> str:
    decision_day = date.fromisoformat(as_of)
    certified_day = certified_at.date()
    first_weekend_certification = certified_day.weekday() == 5 and (certified_day - decision_day).days == 1
    return "PROVISIONAL" if first_weekend_certification else "FINAL"


def _decision_id(as_of: str, decision_hash: str, revision: int, finality: str) -> str:
    suffix = _stable_hash(
        {
            "as_of": as_of,
            "decision_hash": decision_hash,
            "decision_revision": revision,
            "bar_finality": finality,
        }
    )[:20]
    return f"decision-{as_of}-r{revision}-{suffix}"


def _legacy_decision_id(as_of: str, record: Mapping[str, Any]) -> str:
    raw_payload = record.get("payload")
    payload: Mapping[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}
    suffix = _stable_hash(
        {
            "as_of": as_of,
            "input_hash": payload.get("input_hash"),
            "payload_hash": record.get("payload_hash"),
            "run_ts": payload.get("run_ts"),
        }
    )[:20]
    return f"legacy-{as_of}-{suffix}"


def _latest_scheduled_record(path: Path, as_of: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        start = max(0, size - MAX_AUDIT_TAIL_BYTES)
        handle.seek(start)
        data = handle.read()
    lines = data.split(b"\n")
    if start:
        lines = lines[1:]
    for raw in reversed(lines):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        payload = record.get("payload") if isinstance(record, dict) else None
        if not isinstance(payload, dict):
            continue
        if str(payload.get("run_type") or "") != "scheduled":
            continue
        if str(payload.get("as_of") or "")[:10] == as_of:
            return record
    return None


def _market_manifest_id(archive_dir: Path) -> str:
    path = archive_dir / "data_manifest_latest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"canonical market manifest unavailable: {path}") from exc
    manifest_id = str(payload.get("manifest_id") or "")
    if not manifest_id:
        raise ValueError(f"canonical market manifest has no manifest_id: {path}")
    return manifest_id


def _policy_hash(package_root: Path) -> str:
    path = package_root / "governance" / "approved_live_config.json"
    if not path.is_file():
        raise ValueError(f"approved live-config policy unavailable: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _release_hash(package_root: Path) -> str:
    version_path = package_root / "VERSION"
    if version_path.is_file():
        fields = version_path.read_text(encoding="utf-8").splitlines()[0].split()
        if fields and fields[0]:
            return fields[0]
        raise ValueError(f"invalid VERSION: {version_path}")
    digest = hashlib.sha256()
    source_files = sorted(
        path
        for path in package_root.rglob("*.py")
        if "tests" not in path.relative_to(package_root).parts
    )
    if not source_files:
        raise ValueError(f"cannot identify scorer release: {package_root}")
    for path in source_files:
        relative = path.relative_to(package_root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"source-{digest.hexdigest()}"


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
