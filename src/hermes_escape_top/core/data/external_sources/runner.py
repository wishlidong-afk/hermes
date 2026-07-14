from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
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
    official_issue_as_of: str | None = None
    official_file_name: str | None = None
    official_file_sha256: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    input_hash: str | None = None
    output_hash: str | None = None
    canonical_sha256: str | None = None
    canonical_latest_as_of: str | None = None
    fetched_at: str | None = None
    pit_rule: str | None = None
    source_url: str | None = None

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
            pit_rule=spec.pit_rule,
            source_url=spec.source_url,
        )

    raw_text = json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str)
    raw_path.write_text(raw_text + "\n", encoding="utf-8")
    input_hash = _sha256(_stable_raw_text(raw))

    try:
        frame = adapter.parse(raw)
    except Exception as exc:
        official = _official_metadata(raw, None)
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
            official_file_name=official["official_file_name"],
            official_file_sha256=official["official_file_sha256"],
            fetched_at=started,
            pit_rule=spec.pit_rule,
            source_url=_source_url(raw) or spec.source_url,
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
    if validation_error is None:
        validation_error = _stale_target_error(spec, frame)
        validation_payload["status"] = "OK" if validation_error is None else "VALIDATION_ERROR"
        validation_payload["error"] = validation_error
    validation_path.write_text(json.dumps(validation_payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

    if validation_error:
        official = _official_metadata(raw, latest_frame_date(spec, frame))
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
            official_issue_as_of=official["official_issue_as_of"],
            official_file_name=official["official_file_name"],
            official_file_sha256=official["official_file_sha256"],
            fetched_at=started,
            pit_rule=spec.pit_rule,
            source_url=_source_url(raw) or spec.source_url,
        )

    previous = _canonical_snapshot(spec.target_path)
    atomic_write_csv(frame, spec.target_path, index=False)
    try:
        latest_as_of = latest_frame_date(spec, frame)
        canonical_sha256 = _sha256_file(spec.target_path)
        official = _official_metadata(raw, latest_as_of)
        return _record(
            archive_dir,
            spec,
            run_id,
            started,
            "OK",
            raw_path=raw_path,
            normalized_path=normalized_path,
            validation_path=validation_path,
            latest_promoted_as_of=latest_as_of,
            input_hash=input_hash,
            output_hash=output_hash,
            official_issue_as_of=official["official_issue_as_of"],
            official_file_name=official["official_file_name"],
            official_file_sha256=official["official_file_sha256"],
            canonical_sha256=canonical_sha256,
            canonical_latest_as_of=latest_as_of,
            fetched_at=started,
            pit_rule=spec.pit_rule,
            source_url=_source_url(raw) or spec.source_url,
        )
    except BaseException as exc:
        try:
            _restore_canonical(spec.target_path, previous)
        except BaseException as rollback_exc:
            raise RuntimeError(
                f"external source promotion failed ({exc!r}) and canonical rollback failed"
            ) from rollback_exc
        raise


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
    official_issue_as_of: str | None = None,
    official_file_name: str | None = None,
    official_file_sha256: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    input_hash: str | None = None,
    output_hash: str | None = None,
    canonical_sha256: str | None = None,
    canonical_latest_as_of: str | None = None,
    fetched_at: str | None = None,
    pit_rule: str | None = None,
    source_url: str | None = None,
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
        official_issue_as_of=official_issue_as_of,
        official_file_name=official_file_name,
        official_file_sha256=official_file_sha256,
        error_type=error_type,
        error_message=error_message,
        input_hash=input_hash,
        output_hash=output_hash,
        canonical_sha256=canonical_sha256,
        canonical_latest_as_of=canonical_latest_as_of,
        fetched_at=fetched_at,
        pit_rule=pit_rule,
        source_url=source_url,
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


def _stable_raw_text(raw: Any) -> str:
    volatile_keys = {"fetched_at", "retrieved_at"}

    def normalize(value: Any, path: tuple[str, ...] = ()) -> Any:
        if isinstance(value, dict):
            strip_volatile = not path or path[-1] == "metadata"
            return {
                key: normalize(item, path + (key,))
                for key, item in value.items()
                if not (strip_volatile and key in volatile_keys)
            }
        if isinstance(value, list):
            return [normalize(item, path + ("[]",)) for item in value]
        return value

    return json.dumps(normalize(raw), ensure_ascii=False, sort_keys=True, default=str)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical_snapshot(path: Path) -> tuple[bool, bytes, int | None]:
    target = Path(path)
    if not target.exists():
        return False, b"", None
    return True, target.read_bytes(), stat.S_IMODE(target.stat().st_mode)


def _restore_canonical(
    path: Path,
    snapshot: tuple[bool, bytes, int | None],
) -> None:
    target = Path(path)
    existed, content, mode = snapshot
    if not existed:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.rollback.", dir=target.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temp, mode)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def _source_url(raw: Any) -> str | None:
    if not isinstance(raw, dict):
        return None
    for key in ("artifact_url", "xlsx_url", "url", "source_url", "index_url"):
        value = raw.get(key)
        if value:
            return str(value)
    return None


def _official_metadata(raw: Any, latest_as_of: str | None) -> dict[str, str | None]:
    if not isinstance(raw, dict):
        return {
            "official_issue_as_of": None,
            "official_file_name": None,
            "official_file_sha256": None,
        }
    file_name = raw.get("file_name")
    if not file_name and raw.get("xlsx_url"):
        file_name = str(raw.get("xlsx_url")).rstrip("/").split("/")[-1] or None
    file_sha256 = raw.get("content_sha256") or raw.get("xlsx_sha256")
    has_file_evidence = bool(file_name or file_sha256)
    return {
        "official_issue_as_of": latest_as_of if has_file_evidence else None,
        "official_file_name": str(file_name) if file_name else None,
        "official_file_sha256": str(file_sha256) if file_sha256 else None,
    }


def _stale_target_error(spec: ExternalSourceSpec, frame: pd.DataFrame) -> str | None:
    target = Path(spec.target_path)
    if not target.exists():
        return None
    try:
        existing = pd.read_csv(target)
    except Exception:
        return None
    incoming_latest = latest_frame_date(spec, frame)
    existing_latest = latest_frame_date(spec, existing)
    if incoming_latest and existing_latest and incoming_latest < existing_latest:
        return f"source latest {incoming_latest} is older than existing target latest {existing_latest}"
    return None
