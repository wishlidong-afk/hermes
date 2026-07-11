#!/usr/bin/env python3
"""Plan or apply bounded retention for Hermes runtime artifacts.

Dry-run is the default. ``--apply`` takes the pipeline lock and removes only
strictly named, direct children of the configured roots. Current/previous release
targets and an active score transaction are always protected.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional


SCHEMA_VERSION = "hermes-runtime-retention-v1"
RELEASE_RE = re.compile(r"^[0-9a-f]{7,40}_[0-9]{8}_[0-9]{6}$")
BACKUP_RE = re.compile(r"^hermes_escape_top\.predeploy_backup_[0-9]{8}_[0-9]{6}$")
AUDIT_RE = re.compile(r"^audit_log\.archived_[0-9]{8}T[0-9]{6}\.jsonl\.gz$")
TERMINAL_TRANSACTION_STATUSES = {"COMMITTED", "ROLLED_BACK", "RECOVERED_ROLLBACK"}


def build_prune_plan(
    *,
    live_root: Path,
    backup_root: Path,
    archive_dir: Path,
    keep_releases: int = 12,
    keep_backups: int = 10,
    keep_audit_archives: int = 12,
    keep_transactions: int = 50,
    max_release_bytes: Optional[int] = 2 * 1024**3,
    max_backup_bytes: Optional[int] = 4 * 1024**3,
    max_audit_bytes: Optional[int] = 2 * 1024**3,
    max_transaction_bytes: Optional[int] = 64 * 1024**2,
) -> dict[str, Any]:
    live_root = Path(live_root).resolve()
    backup_root = Path(backup_root).resolve()
    archive_dir = Path(archive_dir).resolve()
    releases_root = live_root / "releases"
    transaction_root = archive_dir / ".score_run_transactions" / "runs"
    protected_releases = _current_release_targets(live_root)
    active_transaction = _active_transaction_id(archive_dir)

    groups = [
        (
            "release",
            _named_entries(releases_root, RELEASE_RE, directories=True),
            max(0, int(keep_releases)),
            protected_releases,
            max_release_bytes,
        ),
        (
            "backup",
            _named_entries(backup_root, BACKUP_RE, directories=True),
            max(0, int(keep_backups)),
            set(),
            max_backup_bytes,
        ),
        (
            "audit_archive",
            _named_entries(archive_dir, AUDIT_RE, directories=False),
            max(0, int(keep_audit_archives)),
            set(),
            max_audit_bytes,
        ),
        (
            "score_transaction",
            _transaction_entries(transaction_root),
            max(0, int(keep_transactions)),
            {transaction_root / active_transaction} if active_transaction else set(),
            max_transaction_bytes,
        ),
    ]

    delete = []
    summaries = {}
    for kind, entries, keep_count, protected, max_bytes in groups:
        selected = _select(entries, keep_count=keep_count, protected=protected, max_bytes=max_bytes)
        for row in selected:
            delete.append({"kind": kind, **row})
        summaries[kind] = {
            "found": len(entries),
            "delete": len(selected),
            "delete_bytes": sum(int(row["bytes"]) for row in selected),
            "protected": sorted(str(path) for path in protected if Path(path).exists()),
            "keep_count": keep_count,
            "max_bytes": max_bytes,
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "DRY_RUN",
        "roots": {
            "live": str(live_root),
            "release": str(releases_root),
            "backup": str(backup_root),
            "audit_archive": str(archive_dir),
            "score_transaction": str(transaction_root),
        },
        "delete": sorted(delete, key=lambda row: (row["kind"], row["mtime"], row["path"])),
        "summary": summaries,
    }


def apply_prune_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported retention plan schema")
    deleted = []
    skipped = []
    for row in plan.get("delete") or []:
        path = Path(str(row.get("path") or ""))
        kind = str(row.get("kind") or "")
        try:
            _validate_delete(kind, path, plan)
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            deleted.append(str(path))
        except FileNotFoundError:
            skipped.append({"path": str(path), "reason": "already_missing"})
        except Exception as exc:
            skipped.append({"path": str(path), "reason": str(exc)})
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "APPLIED",
        "deleted_count": len(deleted),
        "deleted": deleted,
        "skipped": skipped,
    }


def _select(
    entries: list[dict[str, Any]],
    *,
    keep_count: int,
    protected: set[Path],
    max_bytes: Optional[int],
) -> list[dict[str, Any]]:
    protected_resolved = {Path(path).resolve() for path in protected}
    newest = sorted(entries, key=lambda row: (row["mtime"], row["path"]), reverse=True)
    retained = {
        row["path"]
        for row in newest[:keep_count]
    } | {row["path"] for row in newest if Path(row["path"]).resolve() in protected_resolved}
    selected: dict[str, dict[str, Any]] = {
        row["path"]: {**row, "reason": "count"}
        for row in newest
        if row["path"] not in retained and Path(row["path"]).resolve() not in protected_resolved
    }
    remaining_bytes = sum(row["bytes"] for row in newest if row["path"] not in selected)
    if max_bytes is not None and remaining_bytes > max(0, int(max_bytes)):
        for row in sorted(newest, key=lambda item: (item["mtime"], item["path"])):
            if remaining_bytes <= max(0, int(max_bytes)):
                break
            if row["path"] in selected or Path(row["path"]).resolve() in protected_resolved:
                continue
            selected[row["path"]] = {**row, "reason": "capacity"}
            remaining_bytes -= row["bytes"]
    return sorted(selected.values(), key=lambda row: (row["mtime"], row["path"]))


def _named_entries(root: Path, pattern: re.Pattern[str], *, directories: bool) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    rows = []
    for path in root.iterdir():
        if path.is_symlink() or not pattern.fullmatch(path.name):
            continue
        if directories != path.is_dir():
            continue
        rows.append(_entry(path))
    return rows


def _transaction_entries(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    rows = []
    for path in root.iterdir():
        if path.is_symlink() or not path.is_dir():
            continue
        manifest = path / "manifest.json"
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(payload.get("run_id") or "") != path.name:
            continue
        if str(payload.get("status") or "") not in TERMINAL_TRANSACTION_STATUSES:
            continue
        rows.append(_entry(path))
    return rows


def _entry(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": _path_size(path),
        "mtime": path.stat().st_mtime,
    }


def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file() and not child.is_symlink():
            total += child.stat().st_size
    return total


def _current_release_targets(live_root: Path) -> set[Path]:
    targets = set()
    for name in ("current", "previous"):
        link = live_root / name
        if link.is_symlink():
            targets.add(link.resolve())
    return targets


def _active_transaction_id(archive_dir: Path) -> Optional[str]:
    path = archive_dir / ".score_run_transactions" / "active.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    value = str(payload.get("run_id") or "")
    return value or None


def _validate_delete(kind: str, path: Path, plan: dict[str, Any]) -> None:
    roots = plan.get("roots") or {}
    if kind not in {"release", "backup", "audit_archive", "score_transaction"}:
        raise ValueError(f"unknown artifact kind: {kind}")
    root = Path(str(roots.get(kind) or "")).resolve()
    resolved = path.resolve()
    if resolved.parent != root:
        raise ValueError("candidate is not a direct child of its retention root")
    if path.is_symlink():
        raise ValueError("refusing to prune symlink")
    if kind == "release":
        if not RELEASE_RE.fullmatch(path.name) or not path.is_dir():
            raise ValueError("invalid release candidate")
        live_root = Path(str(roots.get("live") or "")).resolve()
        if resolved in _current_release_targets(live_root):
            raise ValueError("release is current/previous")
    elif kind == "backup":
        if not BACKUP_RE.fullmatch(path.name) or not path.is_dir():
            raise ValueError("invalid backup candidate")
    elif kind == "audit_archive":
        if not AUDIT_RE.fullmatch(path.name) or not path.is_file():
            raise ValueError("invalid audit archive candidate")
    else:
        archive_dir = Path(str(roots.get("audit_archive") or "")).resolve()
        if path.name == _active_transaction_id(archive_dir):
            raise ValueError("score transaction is active")
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        if str(manifest.get("run_id") or "") != path.name:
            raise ValueError("transaction run_id mismatch")
        if str(manifest.get("status") or "") not in TERMINAL_TRANSACTION_STATUSES:
            raise ValueError("transaction is not terminal")


@contextmanager
def _pipeline_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except BlockingIOError as exc:
        raise RuntimeError(f"pipeline busy: {path}") from exc
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _parser() -> argparse.ArgumentParser:
    default_live = Path.home() / ".hermes" / "skills" / "investment" / "escape-top"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-root", type=Path, default=default_live)
    parser.add_argument("--backup-root", type=Path, default=Path.home() / ".hermes-deploy-backups" / "escape-top")
    parser.add_argument("--archive-dir", type=Path)
    parser.add_argument("--keep-releases", type=int, default=12)
    parser.add_argument("--keep-backups", type=int, default=10)
    parser.add_argument("--keep-audit-archives", type=int, default=12)
    parser.add_argument("--keep-transactions", type=int, default=50)
    parser.add_argument("--max-release-mb", type=int, default=2048)
    parser.add_argument("--max-backup-mb", type=int, default=4096)
    parser.add_argument("--max-audit-mb", type=int, default=2048)
    parser.add_argument("--max-transaction-mb", type=int, default=64)
    parser.add_argument("--apply", action="store_true", help="delete planned entries; default is dry-run")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _parser().parse_args(argv)
    archive = args.archive_dir or args.live_root / "shared" / "hermes_escape_top" / "data" / "archive"
    plan = build_prune_plan(
        live_root=args.live_root,
        backup_root=args.backup_root,
        archive_dir=archive,
        keep_releases=args.keep_releases,
        keep_backups=args.keep_backups,
        keep_audit_archives=args.keep_audit_archives,
        keep_transactions=args.keep_transactions,
        max_release_bytes=args.max_release_mb * 1024**2,
        max_backup_bytes=args.max_backup_mb * 1024**2,
        max_audit_bytes=args.max_audit_mb * 1024**2,
        max_transaction_bytes=args.max_transaction_mb * 1024**2,
    )
    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    try:
        with _pipeline_lock(Path(archive) / ".pipeline.lock"):
            result = apply_prune_plan(plan)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not result["skipped"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
