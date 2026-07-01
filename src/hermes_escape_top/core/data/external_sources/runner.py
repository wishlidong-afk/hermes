from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ...safe_io import atomic_write_csv
from .ledger import append_source_run
from .registry import ExternalSourceSpec, latest_frame_date, validate_normalized_frame


@dataclass(frozen=True)
class ExternalSourceRun:
    run_id: str
    source_id: str
    status: str
    started_at: str
    finished_at: str
    target_path: str
    raw_path: str | None = None
    normalized_path: str | None = None
    validation_path: str | None = None
    latest_promoted_as_of: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    input_hash: str | None = None
    output_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_external_source_refresh(
    spec: ExternalSourceSpec,
    adapter: Any,
    archive_dir: Path,
    *,
    now: datetime | None = None,
) -> ExternalSourceRun:
    started = _iso(now)
    run_id = f"{spec.source_id}_{started.replace(':', '').replace('-', '').replace('.', '')}"
    staging_dir = Path(archive_dir) / "external_sources" / spec.source_id / run_id
    staging_dir.mkdir(parents=True, exist_ok=True)
    raw_path = staging_dir / "raw.json"
    normalized_path = staging_dir / "normalized.csv"
    validation_path = staging_dir / "validation.json"

    try:
        raw = adapter.fetch_raw()
    except Exception as exc:
        return _record(
            archive_dir,
            spec,
            run_id,
            started,
            "FETCH_ERROR",
            error_type=exc.__class__.__name__,
            error_message=str(exc),
        )

    raw_text = json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str)
    raw_path.write_text(raw_text + "\n", encoding="utf-8")
    input_hash = _sha256(raw_text)

    try:
        frame = adapter.parse(raw)
    except Exception as exc:
        return _record(
            archive_dir,
            spec,
            run_id,
            started,
            "PARSE_ERROR",
            raw_path=raw_path,
            error_type=exc.__class__.__name__,
            error_message=str(exc),
            input_hash=input_hash,
        )
    if not isinstance(frame, pd.DataFrame):
        frame = pd.DataFrame(frame)

    atomic_write_csv(frame, normalized_path, index=False)
    output_hash = _sha256(normalized_path.read_text(encoding="utf-8"))
    validation_error = validate_normalized_frame(spec, frame)
    validation_payload = {
        "source_id": spec.source_id,
        "status": "OK" if validation_error is None else "VALIDATION_ERROR",
        "error": validation_error,
        "rows": int(len(frame)),
        "latest_as_of": latest_frame_date(spec, frame),
    }
    validation_path.write_text(json.dumps(validation_payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

    if validation_error:
        return _record(
            archive_dir,
            spec,
            run_id,
            started,
            "VALIDATION_ERROR",
            raw_path=raw_path,
            normalized_path=normalized_path,
            validation_path=validation_path,
            error_type="ValidationError",
            error_message=validation_error,
            input_hash=input_hash,
            output_hash=output_hash,
        )

    atomic_write_csv(frame, spec.target_path, index=False)
    return _record(
        archive_dir,
        spec,
        run_id,
        started,
        "OK",
        raw_path=raw_path,
        normalized_path=normalized_path,
        validation_path=validation_path,
        latest_promoted_as_of=latest_frame_date(spec, frame),
        input_hash=input_hash,
        output_hash=output_hash,
    )


def _record(
    archive_dir: Path,
    spec: ExternalSourceSpec,
    run_id: str,
    started_at: str,
    status: str,
    *,
    raw_path: Path | None = None,
    normalized_path: Path | None = None,
    validation_path: Path | None = None,
    latest_promoted_as_of: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    input_hash: str | None = None,
    output_hash: str | None = None,
) -> ExternalSourceRun:
    run = ExternalSourceRun(
        run_id=run_id,
        source_id=spec.source_id,
        status=status,
        started_at=started_at,
        finished_at=_iso(),
        target_path=str(spec.target_path),
        raw_path=str(raw_path) if raw_path else None,
        normalized_path=str(normalized_path) if normalized_path else None,
        validation_path=str(validation_path) if validation_path else None,
        latest_promoted_as_of=latest_promoted_as_of,
        error_type=error_type,
        error_message=error_message,
        input_hash=input_hash,
        output_hash=output_hash,
    )
    append_source_run(archive_dir, run.to_dict())
    return run


def _iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
