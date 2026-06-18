from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import pandas as pd


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    sha256: str
    bytes: int
    rows: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    proxy_rows: int = 0
    proxy_start_date: Optional[str] = None
    proxy_end_date: Optional[str] = None
    proxy_sources: Optional[list[str]] = None


@dataclass(frozen=True)
class Manifest:
    schema_version: str
    manifest_id: str
    frozen_at: str
    root: str
    entries: Dict[str, ManifestEntry]

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["entries"] = {key: asdict(value) for key, value in self.entries.items()}
        return payload


def freeze_manifest(store_dir: str | Path) -> Manifest:
    root = Path(store_dir).resolve()
    entries: Dict[str, ManifestEntry] = {}
    if root.exists():
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            rel = path.relative_to(root).as_posix()
            entries[rel] = _entry(root, path)
    frozen_at = datetime.now(timezone.utc).isoformat()
    manifest_id = _manifest_id(entries)
    return Manifest(
        schema_version="escape-top-data-manifest-v1",
        manifest_id=manifest_id,
        frozen_at=frozen_at,
        root=str(root),
        entries=entries,
    )


def write_manifest(store_dir: str | Path, output_path: str | Path) -> Path:
    manifest = freeze_manifest(store_dir)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write (temp in same dir + replace) so a concurrent reader
    # (manifest_status / verify_manifest) never sees a half-written manifest (#3).
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(out)
    return out


def load_manifest(path: str | Path) -> Manifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = {key: ManifestEntry(**value) for key, value in payload.get("entries", {}).items()}
    return Manifest(
        schema_version=payload["schema_version"],
        manifest_id=payload["manifest_id"],
        frozen_at=payload["frozen_at"],
        root=payload["root"],
        entries=entries,
    )


def verify_manifest(store_dir: str | Path, manifest_path: str | Path) -> bool:
    expected = load_manifest(manifest_path)
    current = freeze_manifest(store_dir)
    manifest = Path(manifest_path).resolve()
    root = Path(store_dir).resolve()
    try:
        manifest_rel = manifest.relative_to(root).as_posix()
    except ValueError:
        manifest_rel = None
    if manifest_rel is not None:
        current.entries.pop(manifest_rel, None)
    if set(current.entries) != set(expected.entries):
        return False
    return all(current.entries[key].sha256 == expected.entries[key].sha256 for key in expected.entries)


def _entry(root: Path, path: Path) -> ManifestEntry:
    rel = path.relative_to(root).as_posix()
    rows: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    proxy_rows = 0
    proxy_start_date: Optional[str] = None
    proxy_end_date: Optional[str] = None
    proxy_sources: Optional[list[str]] = None
    if path.suffix.lower() == ".csv":
        try:
            frame = pd.read_csv(path)
            rows = int(len(frame))
            date_col = "Date" if "Date" in frame.columns else "date" if "date" in frame.columns else None
            if date_col is not None and rows:
                dates = pd.to_datetime(frame[date_col], errors="coerce").dropna()
                if not dates.empty:
                    start_date = dates.min().date().isoformat()
                    end_date = dates.max().date().isoformat()
                proxy_col = "is_proxy" if "is_proxy" in frame.columns else None
                if proxy_col is not None:
                    proxy_mask = frame[proxy_col].astype(str).str.lower().isin({"true", "1", "yes"})
                    proxy_rows = int(proxy_mask.sum())
                    if proxy_rows and date_col is not None:
                        proxy_dates = pd.to_datetime(frame.loc[proxy_mask, date_col], errors="coerce").dropna()
                        if not proxy_dates.empty:
                            proxy_start_date = proxy_dates.min().date().isoformat()
                            proxy_end_date = proxy_dates.max().date().isoformat()
                    if proxy_rows and "source" in frame.columns:
                        proxy_sources = sorted(str(item) for item in frame.loc[proxy_mask, "source"].dropna().unique())
        except Exception:
            rows = None
    return ManifestEntry(
        path=rel,
        sha256=_sha256(path),
        bytes=path.stat().st_size,
        rows=rows,
        start_date=start_date,
        end_date=end_date,
        proxy_rows=proxy_rows,
        proxy_start_date=proxy_start_date,
        proxy_end_date=proxy_end_date,
        proxy_sources=proxy_sources,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_id(entries: Dict[str, ManifestEntry]) -> str:
    payload = {key: asdict(value) for key, value in sorted(entries.items())}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
