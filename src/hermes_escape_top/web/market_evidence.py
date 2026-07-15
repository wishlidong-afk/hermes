"""Read-only selection of market-admission evidence for the dashboard."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..config import load_config, resolve_path
from ..core.data.market_admission import (
    read_market_admission_evidence,
    validate_market_admission_evidence,
)


def attach_market_admission_status(
    payload: dict[str, Any],
    *,
    config_loader: Callable[[], dict[str, Any]] = load_config,
    path_resolver: Callable[[dict[str, Any], str], Any] = resolve_path,
) -> dict[str, Any]:
    """Attach current gate evidence without trusting persisted score status."""
    try:
        config = config_loader()
        enabled = bool((config.get("features") or {}).get("use_market_admission_gate", False))
        if not enabled:
            payload.pop("market_admission_status", None)
            return payload
        archive_dir = path_resolver(config, "archive_dir")
        persisted = read_market_admission_evidence(archive_dir)
        current = payload.get("market_admission_status")
        current = current if isinstance(current, dict) else None
        if persisted is None and current is None:
            payload["market_admission_status"] = {
                "mode": "enforce_consensus",
                "status": "MISSING",
                "reason": "market admission is enabled but no evidence file exists",
            }
        else:
            receipt = payload.get("run_receipt") or {}
            history_dir = path_resolver(config, "history_dir")
            validated_current = (
                validate_market_admission_evidence(
                    current,
                    history_dir,
                    as_of=payload.get("as_of"),
                    run_started_at=receipt.get("started_at"),
                )
                if current is not None
                else None
            )
            validated_persisted = (
                validate_market_admission_evidence(
                    persisted,
                    history_dir,
                    as_of=payload.get("as_of"),
                    run_started_at=receipt.get("started_at"),
                )
                if persisted is not None
                else None
            )
            if validated_current is None:
                selected = validated_persisted
            elif validated_persisted is None:
                selected = validated_current
            elif current.get("operation_id") != persisted.get("operation_id"):
                selected = validated_current
                if selected.get("status") == "SUPERSEDED_BY_NEWER_DATA":
                    selected = {
                        **selected,
                        "latest_operation_id": validated_persisted.get("operation_id"),
                        "latest_evidence_status": validated_persisted.get("status"),
                    }
            else:
                severity = {
                    "OK": 0,
                    "SUPERSEDED_BY_NEWER_DATA": 1,
                    "BLOCKED": 2,
                    "MISSING": 3,
                    "STALE": 3,
                    "FETCH_ERROR": 4,
                    "ERROR": 5,
                    "EVIDENCE_DRIFT": 6,
                }
                selected = max(
                    (validated_current, validated_persisted),
                    key=lambda row: severity.get(str(row.get("status") or ""), 4),
                )
            payload["market_admission_status"] = selected
    except Exception as exc:
        payload["market_admission_status"] = {
            "mode": "enforce_consensus",
            "status": "ERROR",
            "run_error": f"{exc.__class__.__name__}: {exc}",
        }
    return payload
