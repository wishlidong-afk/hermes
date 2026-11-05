"""Read run-bound auxiliary declarations, not current broker cache validity."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from ..data.transaction_evidence import SCHEMA_V2, checked_path, validate_input_evidence, validate_inventory


def read_broker_publication_status(
    *, archive_dir: Path, run_id: str, expected_journal_sha256: str,
    decision_id: str, input_hash: str,
) -> dict[str, Any]:
    """Read an unsigned local declaration against an externally anchored v2 run.

    UNKNOWN means evidence was not accepted, not that publication failed. Even
    OK does not attest to current cache contents, freshness, or broker access.
    No lock, recovery, publication, or other writer is invoked here.
    """
    if not isinstance(run_id, str) or len(run_id) != 32 or UUID(hex=run_id).hex != run_id:
        raise ValueError("invalid publication run identity")
    archive = Path(archive_dir).resolve()
    report: dict[str, Any] = {
        "schema_version": "hermes-broker-publication-observation-v1",
        "status": "UNKNOWN", "publication_status": "UNVERIFIED", "reason": "TRANSACTION_UNVERIFIED",
        "scope": "OPERATIONS", "strategy_blocking": False, "cache_contents_verified": False,
        "run_id": run_id, "capture_id": None, "business_status": None,
        "journal_sha256": None, "receipt_sha256": None, "caches": {},
    }
    try:
        record = _committed_record(archive, run_id, expected_journal_sha256, decision_id, input_hash)
        tape = _frozen_tape(archive, record["capture_id"])
    # The existing validator consumes nested JSON; shape errors are unverified evidence.
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return report
    report.update(capture_id=record["capture_id"], business_status="COMMITTED",
                  journal_sha256=expected_journal_sha256, publication_status="MISSING", reason="RECEIPT_MISSING")
    try:
        raw_receipt = _raw_file(archive, f"broker_cache_publications/{run_id}.json")
    except FileNotFoundError:
        return report
    except (OSError, ValueError):
        report.update(publication_status="INVALID", reason="RECEIPT_INVALID")
        return report
    try:
        caches = _receipt_statuses(_object(raw_receipt), run_id, record["capture_id"], tape)
    except (ValueError, TypeError, KeyError):
        report.update(publication_status="INVALID", reason="RECEIPT_INVALID")
        return report
    states = set(caches.values())
    report.update({
        "status": "WARN" if "FAILED" in states else ("OK" if states == {"PUBLISHED"} else "INFO"),
        "publication_status": next(iter(states)) if len(states) == 1 else "PARTIAL",
        "reason": "MATCHING_RECEIPT",
        "receipt_sha256": hashlib.sha256(raw_receipt).hexdigest(),
        "caches": caches,
    })
    return report


def _committed_record(archive: Path, run_id: str, anchor: str, decision_id: str, input_hash: str) -> dict[str, Any]:
    raw = _raw_file(archive, f".score_run_transactions/runs/{run_id}/manifest.json")
    if hashlib.sha256(raw).hexdigest() != anchor:
        raise ValueError("publication journal digest mismatch")
    record = _object(raw)
    if (record.get("schema_version") != SCHEMA_V2
            or record.get("status") != "COMMITTED" or record.get("run_id") != run_id):
        raise ValueError("publication requires a matching COMMITTED v2 transaction")
    binding = record.get("input_binding")
    if (not isinstance(binding, dict) or binding.get("decision_id") != decision_id
            or binding.get("input_hash") != input_hash):
        raise ValueError("publication decision binding mismatch")
    _, evidence = validate_inventory(record)
    for relative in evidence:
        if not checked_path(archive.parent, relative).is_file():
            raise ValueError("publication input evidence must be a regular file")
    validate_input_evidence(record, archive.parent)
    return record


def _raw_file(root: Path, relative: str) -> bytes:
    path = checked_path(root, relative)
    if not path.is_file():
        if not path.exists():
            raise FileNotFoundError("publication evidence file missing")
        raise ValueError("publication evidence must be a regular file")
    return path.read_bytes()


def _object(raw: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate publication evidence key")
            result[key] = value
        return result

    result = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(result, dict):
        raise ValueError("publication evidence must be an object")
    return result


def _frozen_tape(archive: Path, capture_id: str) -> dict[str, Any]:
    tape = _object(_raw_file(archive, f"decision_inputs/{capture_id}/broker.json"))
    if tape.get("schema_version") != "hermes-broker-input-tape-v1":
        raise ValueError("unsupported publication tape")
    reads, targets = tape.get("reads"), tape.get("cache_targets")
    if (not isinstance(reads, dict) or set(reads) != {"positions", "executions"}
            or not isinstance(targets, dict) or set(targets) != set(reads)):
        raise ValueError("invalid publication tape inventory")
    for name, row in reads.items():
        if not isinstance(targets[name], str) or not Path(targets[name]).is_absolute():
            raise ValueError("invalid frozen cache target")
        if (not isinstance(row, dict) or set(row) != {"status", "snapshot", "reason", "error"}
                or row["status"] not in {"RETURNED", "NOT_READ", "ERROR"}
                or any(row[key] is not None and not isinstance(row[key], str) for key in ("reason", "error"))):
            raise ValueError("invalid frozen broker read")
        snapshot = row["snapshot"]
        if (row["status"] == "RETURNED" and not isinstance(snapshot, dict)
                or row["status"] != "RETURNED" and snapshot is not None):
            raise ValueError("invalid frozen broker read")
    return tape


def _receipt_statuses(receipt: dict[str, Any], run_id: str, capture_id: str, tape: dict[str, Any]) -> dict[str, str]:
    if (set(receipt) != {"schema_version", "run_id", "capture_id", "business_status", "caches"}
            or receipt["schema_version"] != "hermes-broker-cache-publication-v1"
            or receipt["run_id"] != run_id or receipt["capture_id"] != capture_id
            or receipt["business_status"] != "COMMITTED"):
        raise ValueError("publication receipt binding mismatch")
    rows = receipt["caches"]
    if not isinstance(rows, dict) or set(rows) != {"positions", "executions"}:
        raise ValueError("publication cache inventory mismatch")
    caches = {}
    for name, row in rows.items():
        if not isinstance(row, dict):
            raise ValueError("invalid publication row")
        status = row.get("status")
        if not isinstance(status, str):
            raise ValueError("invalid publication status type")
        field = {"PUBLISHED": "target", "FAILED": "error", "NOT_PUBLISHED": "reason"}.get(status)
        if (not field or set(row) != {"status", field}
                or not isinstance(row[field], str) or not row[field].strip()):
            raise ValueError("invalid publication row declaration")
        read = tape["reads"][name]
        eligible = read["status"] == "RETURNED" and read["snapshot"].get("source") == "tws"
        if ((status != "NOT_PUBLISHED") != eligible
                or (status == "PUBLISHED" and row["target"] != tape["cache_targets"][name])
                or (status == "NOT_PUBLISHED" and row["reason"] != (read["reason"] or read["error"] or "not a live response"))):
            raise ValueError("publication declaration contradicts frozen intent")
        caches[name] = status
    return caches
