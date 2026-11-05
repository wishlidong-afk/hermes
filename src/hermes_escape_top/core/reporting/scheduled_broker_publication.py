"""Offline auxiliary observation for one unique official scheduled run."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..data.transaction_evidence import checked_path
from .broker_publication_status import read_broker_publication_status

_CAPTURE_MARKERS = frozenset({"capture_id", "capture_inputs", "capture_mode", "input_binding", "commit_observation"})


def read_scheduled_broker_publication(*, archive_dir: Path, acceptance_date: date) -> dict[str, Any]:
    """Observe unsigned local declarations, never main health or current caches.

    Selection follows the acceptance day's unique scheduled audit and the
    official finished receipt, but malformed evidence is conservatively UNKNOWN.
    A FAILED official receipt stays FAILED even if its publication is observed.
    """
    report: dict[str, Any] = {
        "schema_version": "hermes-scheduled-broker-publication-v1",
        "status": "UNKNOWN", "publication_status": "UNVERIFIED", "reason": "OFFICIAL_RUN_UNVERIFIED",
        "scope": "OPERATIONS", "strategy_blocking": False, "cache_contents_verified": False,
        "anchor_source": None, "official_receipt_status": None,
    }
    try:
        receipt, audit = _official_run(Path(archive_dir), acceptance_date)
        report["official_receipt_status"] = receipt["status"]
        persistence = audit["persistence"]
        protocol = persistence["protocol"]
        if not _hex(persistence["run_id"], 32) or not _hex(audit["input_hash"], 64):
            raise ValueError("invalid official run identity")
        if ((_CAPTURE_MARKERS - {"commit_observation"}).intersection(receipt)
                or (_CAPTURE_MARKERS - {"capture_id"}).intersection(persistence)):
            raise ValueError("unsupported capture metadata location")
        if protocol == "recoverable-journal-v1":
            if _CAPTURE_MARKERS.intersection(persistence) or _CAPTURE_MARKERS.intersection(receipt):
                raise ValueError("mixed capture metadata in a v1 run")
            report.update(status="INFO", publication_status="NOT_APPLICABLE", reason="CAPTURE_DISABLED")
        elif protocol == "recoverable-journal-v2":
            if not _hex(persistence["capture_id"], 32):
                raise ValueError("invalid official capture identity")
            if "commit_observation" not in receipt:
                report["reason"] = "ANCHOR_UNAVAILABLE"
            else:
                report["reason"] = "ANCHOR_INVALID"
                observation = _observation(Path(archive_dir), receipt, audit)
                report.update(read_broker_publication_status(
                    archive_dir=archive_dir, run_id=persistence["run_id"],
                    expected_journal_sha256=observation["journal_sha256"],
                    decision_id=observation["decision_id"], input_hash=audit["input_hash"],
                ))
                report.update(schema_version="hermes-scheduled-broker-publication-v1",
                              anchor_source="LOCAL_PRODUCER_RECEIPT")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        return report
    return report


def _observation(archive: Path, receipt: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    persistence = audit["persistence"]
    expected = {
        "schema_version": "hermes-score-commit-observation-v1", "protocol": "recoverable-journal-v2",
        "as_of": audit["as_of"], "run_id": persistence["run_id"],
        "capture_id": persistence["capture_id"], "decision_id": audit["decision_evidence"]["decision_id"],
        "input_hash": audit["input_hash"],
    }
    observation = receipt["commit_observation"]
    if (not isinstance(observation, dict) or set(observation) != set(expected) | {"journal_sha256", "committed_at"}
            or any(observation[k] != v for k, v in expected.items())
            or not isinstance(expected["decision_id"], str) or not expected["decision_id"]
            or not _hex(observation["journal_sha256"], 64)):
        raise ValueError("invalid commit observation")
    if not _timestamp(receipt["started_at"]) <= _timestamp(observation["committed_at"]) < (
        _timestamp(receipt["finished_at"]) + timedelta(seconds=1)
    ):
        raise ValueError("commit observation outside official invocation")
    journal = _object(_file(archive, f".score_run_transactions/runs/{persistence['run_id']}/manifest.json").read_text())
    if (journal["metadata"]["as_of"] != audit["as_of"]
            or journal["capture_id"] != persistence["capture_id"]
            or journal["committed_at"] != observation["committed_at"]):
        raise ValueError("commit observation/journal identity mismatch")
    # The unchanged reader verifies bytes against the producer's original digest.
    # No journal self-hash is computed here as a substitute anchor.
    return observation


def _official_run(archive: Path, day: date) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt = _object(_file(archive, "run_receipt.json").read_text())
    if ("schema_version" in receipt or "protocol" in receipt or receipt.get("run_type") != "scheduled"
            or receipt.get("status") not in {"OK", "FAILED"}
            or receipt.get("ok") is not (receipt["status"] == "OK")):
        raise ValueError("a finished official receipt is required")
    finished = _timestamp(receipt["finished_at"])
    started = _timestamp(receipt["started_at"])
    if finished.astimezone(ZoneInfo("Asia/Shanghai")).date() != day or started > finished:
        raise ValueError("official receipt date/window mismatch")
    selected = []
    with _file(archive, "audit_log.jsonl").open() as stream:
        for line in stream:
            if not line.strip():
                continue
            row = _object(line)
            payload = row.get("payload", row)
            if not isinstance(payload, dict):
                raise ValueError("audit payload must be an object")
            if ("payload" in row and row.get("schema_version", "escape-top-greenfield-audit-v1")
                    != "escape-top-greenfield-audit-v1"):
                raise ValueError("unsupported audit envelope schema")
            if (any(k in row and row[k] != payload.get(k) for k in ("as_of", "input_hash"))
                    or payload.get("schema_version", "escape-top-greenfield-phase3-score-v1")
                    != "escape-top-greenfield-phase3-score-v1"):
                raise ValueError("audit envelope/schema mismatch")
            if (payload.get("run_type") == "scheduled"
                    and _timestamp(payload["run_ts"]).astimezone(ZoneInfo("Asia/Shanghai")).date() == day):
                selected.append(payload)
    if len(selected) != 1:
        raise ValueError("official scheduled audit must be unique")
    audit = selected[0]
    if (audit.get("shadow", False) is not False
            or _CAPTURE_MARKERS.intersection(audit)
            or audit.get("as_of") != receipt.get("as_of")
            or date.fromisoformat(audit["as_of"]).isoformat() != audit["as_of"]
            or not started <= _timestamp(audit["run_ts"]) < finished + timedelta(seconds=1)):
        raise ValueError("official receipt/audit binding mismatch")
    return receipt, audit


def _hex(value: Any, length: int) -> bool:
    return isinstance(value, str) and re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is not None


def _timestamp(value: str) -> datetime:
    stamp = datetime.fromisoformat(value)
    if stamp.utcoffset() is None:
        raise ValueError("timezone required for official evidence")
    return stamp


def _file(archive: Path, relative: str) -> Path:
    path = checked_path(archive, relative)
    if not path.is_file():
        raise ValueError("official evidence must be a regular file")
    return path


def _object(raw: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate official evidence key")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("official evidence must be an object")
    return value
