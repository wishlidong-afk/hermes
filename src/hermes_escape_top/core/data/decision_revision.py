from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .decision_identity import decision_outputs, semantic_identity

SCHEMA_VERSION = "hermes-decision-certification-v1"
IDENTITY_SCHEMA_VERSION = "hermes-decision-identity-v2"
LEGACY_SCHEMA_VERSION = "hermes-decision-certification-v1"
MAX_DECISION_REVISIONS = 2
SHANGHAI = ZoneInfo("Asia/Shanghai")
# One explicit migration, not a blanket assertion that all releases are equal.
# The candidate fingerprint includes pipeline.py; later scoring edits invalidate it.
V1_EQUIVALENT_RELEASES = {
    "25073bb": "42d207d6b6c84001bf85324ea6af84b5947c7748b7217d72f0d715b21232ad8a",
    "source-fa1012f8ef18a0cf51ecc2de55366feb8798d2ad65adb0afce42fe45fd757b1c":
        "42d207d6b6c84001bf85324ea6af84b5947c7748b7217d72f0d715b21232ad8a",
}
V1_IDENTITY_FIELDS = (
    "as_of", "snapshot_hash", "soft_input_evidence_hash",
    "canonical_market_evidence_hash", "config_hash", "policy_hash",
    "scorer_release_hash", "market_admission_operation_id", "market_admission_completed_through",
)


class DecisionRevisionConflict(RuntimeError):
    """Raised when a same-date official decision exceeds its revision budget."""


def build_scheduled_decision_evidence(
    payload: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    archive_dir: Path,
    package_root: Path,
    histories: Mapping[str, pd.DataFrame | None],
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
    semantic = semantic_identity(payload, config, histories, package_root)
    semantic_hash = _stable_hash(semantic)
    previous = _latest_scheduled_record(archive_dir / "audit_log.jsonl", as_of)
    migration = None
    if previous is not None:
        prior = previous["payload"].get("decision_evidence")
        if (isinstance(prior, dict) and prior.get("schema_version") == LEGACY_SCHEMA_VERSION
                and "identity_schema_version" not in prior):
            previous, migration = _migrate_v1(previous, payload, identity, semantic)
    revision, decision_id, supersedes, reason, previous_hash = _allocate_revision(
        as_of=as_of,
        decision_hash=semantic_hash,
        finality=finality,
        previous=previous,
    )
    prior = previous["payload"].get("decision_evidence", {}) if previous else {}
    repeated = prior.get("decision_id") == decision_id
    # A verified v1 no-op keeps the existing consumer binding and revision.
    decision_hash = prior["decision_hash"] if repeated else semantic_hash
    result = {
        "schema_version": SCHEMA_VERSION,
        "identity_schema_version": IDENTITY_SCHEMA_VERSION,
        **identity,
        "decision_hash": decision_hash,
        "semantic_identity": semantic,
        "semantic_hash": semantic_hash,
        "decision_id": decision_id,
        "decision_revision": revision,
        "supersedes_decision_id": supersedes,
        "previous_decision_hash": previous_hash,
        "revision_reason": reason,
        "bar_finality": finality,
        "certified_at": local_certified_at.isoformat(),
        "revision_budget": MAX_DECISION_REVISIONS,
    }
    if migration or (repeated and prior.get("identity_migration")):
        result["identity_migration"] = migration or prior["identity_migration"]
    return result


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
    if prior is None:
        revision = 2
        legacy_id = _legacy_decision_id(as_of, previous)
        return (
            revision,
            _decision_id(as_of, decision_hash, revision, finality),
            legacy_id,
            "LEGACY_CERTIFICATION_SUPERSEDED",
            str(payload.get("input_hash") or "") or None,
        )

    if (not isinstance(prior, dict) or prior.get("schema_version") != SCHEMA_VERSION
            or prior.get("identity_schema_version") != IDENTITY_SCHEMA_VERSION):
        raise DecisionRevisionConflict("prior decision certification schema is unsupported")
    if _stable_hash(prior.get("semantic_identity")) != prior.get("semantic_hash"):
        raise DecisionRevisionConflict("prior semantic identity hash mismatch")
    if prior.get("decision_hash") != prior.get("semantic_hash"):
        migration = prior.get("identity_migration") or {}
        legacy = migration.get("legacy_evidence") or {}
        if (migration.get("semantic_hash") != prior.get("semantic_hash")
                or legacy.get("decision_hash") != prior.get("decision_hash")
                or legacy.get("decision_id") != prior.get("decision_id")
                or _stable_hash({key: legacy.get(key) for key in V1_IDENTITY_FIELDS}) != prior.get("decision_hash")):
            raise DecisionRevisionConflict("prior migrated identity binding is invalid")

    previous_revision = int(prior.get("decision_revision") or 0)
    previous_id = str(prior.get("decision_id") or "")
    previous_hash = str(prior.get("decision_hash") or "")
    previous_finality = str(prior.get("bar_finality") or "")
    if previous_revision not in {1, 2} or not previous_id or not previous_hash or previous_finality not in {"PROVISIONAL", "FINAL"}:
        raise DecisionRevisionConflict("prior decision certification is incomplete")
    if previous_id != _decision_id(as_of, previous_hash, previous_revision, previous_finality):
        raise DecisionRevisionConflict("prior decision ID binding mismatch")
    if previous_finality == "FINAL" and finality != "FINAL":
        raise DecisionRevisionConflict("bar finality cannot regress from FINAL")
    prior_semantic_hash = prior["semantic_hash"]
    if prior_semantic_hash == decision_hash and previous_finality == finality:
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
    if prior_semantic_hash != decision_hash and previous_finality == "PROVISIONAL" and finality == "FINAL":
        reason = "CANONICAL_EVIDENCE_CHANGED_AND_FINALIZED"
    elif prior_semantic_hash != decision_hash:
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


def _migrate_v1(
    previous: dict[str, Any], payload: Mapping[str, Any],
    observation: Mapping[str, Any], semantic: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    prior_payload = previous["payload"]
    prior = prior_payload["decision_evidence"]
    old_identity = {key: prior.get(key) for key in V1_IDENTITY_FIELDS}
    if _stable_hash(old_identity) != prior.get("decision_hash"):
        raise DecisionRevisionConflict("v1 migration: legacy identity hash mismatch")
    if V1_EQUIVALENT_RELEASES.get(prior.get("scorer_release_hash")) != semantic["scoring_logic_hash"]:
        raise DecisionRevisionConflict("v1 migration: scoring release equivalence not evidenced")
    # v1 stored no as-of history projection. A changed full manifest cannot prove
    # what its old score consumed; never invent historical hashes from today's data.
    verified_fields = (
        "as_of", "snapshot_hash", "soft_input_evidence_hash",
        "canonical_market_evidence_hash", "config_hash", "policy_hash",
    )
    for key in verified_fields:
        if prior.get(key) != observation[key]:
            raise DecisionRevisionConflict(f"v1 migration: unchanged {key} not evidenced")
    old_snapshots = prior_payload.get("snapshots")
    old_soft = (prior_payload.get("soft_data") or {}).get("records") or {}
    if (not old_snapshots or _stable_hash(old_snapshots) != prior.get("snapshot_hash")
            or _stable_hash(old_soft) != prior.get("soft_input_evidence_hash")
            or decision_outputs(prior_payload) != decision_outputs(payload)):
        raise DecisionRevisionConflict("v1 migration: scored payload equivalence not evidenced")
    semantic_hash = _stable_hash(semantic)
    migration = {
        "schema_version": "hermes-decision-identity-migration-v1",
        "from_schema": LEGACY_SCHEMA_VERSION,
        "to_identity_schema": IDENTITY_SCHEMA_VERSION,
        "legacy_evidence": prior,
        "semantic_hash": semantic_hash,
        "verified_observation_fields": list(verified_fields),
        "proof": "UNCHANGED_FULL_MANIFEST_INPUTS_AND_APPROVED_SCORING_RELEASE",
    }
    converted = {
        **prior, "schema_version": SCHEMA_VERSION,
        "identity_schema_version": IDENTITY_SCHEMA_VERSION,
        "semantic_hash": semantic_hash, "semantic_identity": semantic,
        "identity_migration": migration,
    }
    return {**previous, "payload": {**prior_payload, "decision_evidence": converted}}, migration


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
        _reject_unavailable_audit(path, as_of)
        return None
    latest = None
    latest_key = (-1, "")
    # Streaming uses bounded memory and does not mistake a 64 MiB tail miss for
    # a new chain. Corruption is not a license to recreate revision one.
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
                payload = record["payload"]
                if not isinstance(payload, dict):
                    raise ValueError("invalid payload")
            except (KeyError, TypeError, ValueError) as exc:
                raise DecisionRevisionConflict("scheduled audit is malformed") from exc
            if payload.get("run_type") != "scheduled" or str(payload.get("as_of") or "")[:10] != as_of:
                continue
            if record.get("payload_hash") != _stable_hash(payload):
                raise DecisionRevisionConflict("scheduled audit payload hash mismatch")
            evidence = payload.get("decision_evidence")
            try:
                revision = int(evidence["decision_revision"]) if evidence is not None else 0
            except (KeyError, TypeError, ValueError) as exc:
                raise DecisionRevisionConflict("prior decision certification is incomplete") from exc
            key = (revision, str(payload.get("run_ts") or ""))
            if key >= latest_key:
                latest, latest_key = record, key
    if latest is None:
        _reject_unavailable_audit(path, as_of)
    return latest


def _reject_unavailable_audit(path: Path, as_of: str) -> None:
    state = path.parent / "hermes_state.sqlite"
    if not state.is_file():
        return
    with sqlite3.connect(f"{state.as_uri()}?mode=ro", uri=True) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "score_runs" not in tables:
            return
        for (raw,) in conn.execute("SELECT payload_json FROM score_runs WHERE as_of = ?", (as_of,)):
            payload = json.loads(raw)
            if payload.get("run_type") == "scheduled":
                raise DecisionRevisionConflict("prior scheduled state exists but audit is unavailable")


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
