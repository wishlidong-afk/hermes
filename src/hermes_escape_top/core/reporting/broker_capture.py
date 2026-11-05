"""Complete broker responses and best-effort cache publication after commit."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..data.run_transaction import ScoreRunTransaction, load_score_run_transaction
from ..data.transaction_evidence import SCHEMA_V2
from ..safe_io import assert_pipeline_lease, atomic_write_json


class BrokerCapture:
    def __init__(self, include_ibkr: bool) -> None:
        from ...ibkr import executions, positions

        self.reads: dict[str, dict[str, Any]] = {
            name: {"status": "PENDING" if include_ibkr else "NOT_READ", "reason": None if include_ibkr else "include_ibkr=false",
                   "snapshot": None, "error": None}
            for name in ("positions", "executions")
        }
        self.returned: dict[str, Any] = {}
        self.targets = {"positions": Path(positions._SNAPSHOT_PATH).absolute(),
                        "executions": Path(executions._CACHE_PATH).absolute()}
        self.modules = {"positions": positions, "executions": executions}

    def skipped(self, name: str, reason: str) -> None:
        self.reads[name].update(status="NOT_READ", reason=reason)

    def failed(self, name: str, error: Exception) -> None:
        self.reads[name].update(status="ERROR", error=str(error))

    def observed(self, name: str, snapshot: Any) -> None:
        if name in self.returned:
            raise ValueError("broker response was observed twice")
        self.reads[name].update(status="RETURNED", snapshot=json.loads(json.dumps(snapshot.to_dict())), reason=None)
        self.returned[name] = snapshot

    def tape(self, payload: dict[str, Any]) -> dict[str, Any]:
        if any(row["status"] == "PENDING" for row in self.reads.values()):
            raise ValueError("broker read branch was not captured")
        for name, snapshot in self.returned.items():
            if snapshot.to_dict() != self.reads[name]["snapshot"]:
                raise ValueError("broker response changed after consumption")
        return {"schema_version": "hermes-broker-input-tape-v1", "reads": self.reads,
                "cache_targets": {name: str(path) for name, path in self.targets.items()},
                "outcomes": {"positions": payload["ibkr"], "executions": payload["execution_sync"]}}

    def publish(self, transaction: ScoreRunTransaction, *, _lease: Any) -> dict[str, Any]:
        archive = transaction.archive_dir
        assert_pipeline_lease(_lease, path=archive / ".pipeline.lock")
        record = load_score_run_transaction(archive, transaction.run_id)
        if (record["schema_version"] != SCHEMA_V2 or record["status"] != "COMMITTED"
                or not transaction.capture_id or record.get("capture_id") != transaction.capture_id):
            raise ValueError("broker cache publication requires matching COMMITTED capture")
        rows = {}
        for name, row in self.reads.items():
            snapshot = row["snapshot"]
            if row["status"] != "RETURNED" or snapshot.get("source") != "tws":
                rows[name] = {"status": "NOT_PUBLISHED", "reason": row["reason"] or row["error"] or "not a live response"}
                continue
            try:
                module = self.modules[name]
                target = Path(module._SNAPSHOT_PATH if name == "positions" else module._CACHE_PATH).absolute()
                if target != self.targets[name] or target.resolve().is_relative_to(archive.resolve()):
                    raise ValueError("broker cache target changed or overlaps transaction archive")
                if name == "positions":
                    module.publish_positions_cache(module.PositionSnapshot.from_dict(snapshot))
                else:
                    module.publish_executions_cache(module.ExecutionSnapshot.from_dict(snapshot))
                rows[name] = {"status": "PUBLISHED", "target": str(target)}
            except Exception as exc:
                rows[name] = {"status": "FAILED", "error": str(exc)}
                logging.getLogger(__name__).warning("Committed broker cache publication failed (%s): %s", name, exc)
        receipt = {"schema_version": "hermes-broker-cache-publication-v1", "run_id": transaction.run_id,
                   "capture_id": transaction.capture_id, "business_status": "COMMITTED", "caches": rows}
        try:
            directory = archive / "broker_cache_publications"
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            atomic_write_json(directory / f"{transaction.run_id}.json", receipt)
        except Exception as exc:
            logging.getLogger(__name__).warning("Committed broker cache publication receipt unavailable: %s", exc)
        return receipt
