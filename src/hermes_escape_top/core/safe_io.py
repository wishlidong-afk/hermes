"""Cross-process pipeline mutex + atomic file writes (#3).

Two separate write paths mutate the same data dir with no serialization: the
07:10 launchd run (``run_daily_package``) and the WebUI refresh endpoints
(``ThreadingHTTPServer`` → concurrent handler threads). Without a lock they can
interleave (two writers), and a reader (the dashboard) can observe a half-written
CSV. This module closes both seams:

  * :func:`pipeline_lock` — one ``flock`` on ``<archive_dir>/.pipeline.lock``.
    The daily run takes it *blocking* (it must run, so it waits its turn); the
    WebUI takes it *non-blocking* (returns "busy" instead of racing the writer).
    ``flock`` locks are bound to the open file description, so a fresh ``open``
    per acquirer serializes BOTH cross-process (cron vs server) AND intra-process
    (two server threads each open their own fd).

  * :func:`atomic_write_csv` — temp file in the same dir + ``os.replace``, the
    same discipline ``commit_state`` and the audit-log rotation already use, so a
    reader sees either the old or the new file (never a torn one) and a crash
    mid-write leaves the prior file intact.

Acquire the lock at a public transaction boundary. A workflow that already owns
the mutex passes its active private lease to an approved locked helper; it never
opens a second lock fd, which would self-deadlock in the same process.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

try:
    import fcntl  # POSIX (macOS/Linux); this system only ever runs on darwin
except ImportError:  # pragma: no cover - Windows has no flock
    fcntl = None  # type: ignore


class PipelineBusy(RuntimeError):
    """Raised when the pipeline lock is held and the caller asked not to wait."""


_PIPELINE_LEASE_CAPABILITY = object()


class _PipelineLease:
    """Runtime proof that the current process/thread owns a pipeline lock."""

    __slots__ = ("_capability", "_active", "_fd", "_path", "_pid", "_thread_id")

    def __init__(self, fd: int, path: Path) -> None:
        self._capability = _PIPELINE_LEASE_CAPABILITY
        self._active = True
        self._fd = fd
        self._path = Path(path).resolve()
        self._pid = os.getpid()
        self._thread_id = threading.get_ident()

    def _deactivate(self) -> None:
        self._active = False


def assert_pipeline_lease(lease: Any, *, path: Optional[Path] = None) -> None:
    """Reject calls that are not inside the owning pipeline-lock context."""
    if not isinstance(lease, _PipelineLease) or lease._capability is not _PIPELINE_LEASE_CAPABILITY:
        raise RuntimeError("invalid pipeline lease")
    if not lease._active:
        raise RuntimeError("inactive pipeline lease")
    if lease._pid != os.getpid():
        raise RuntimeError("pipeline lease belongs to another process")
    if lease._thread_id != threading.get_ident():
        raise RuntimeError("pipeline lease belongs to another thread")
    if path is not None and lease._path != Path(path).resolve():
        raise RuntimeError(f"pipeline lease path mismatch: {lease._path} != {Path(path).resolve()}")


def pipeline_lease_fd(lease: Any) -> int:
    """Return the active lock fd for inheritance by a guarded subprocess."""
    assert_pipeline_lease(lease)
    return int(lease._fd)


def pipeline_lock_path() -> Path:
    """Resolve the per-data-dir lock file. Both the cron and the server resolve
    the same live ``archive_dir`` (and isolated test dirs resolve their own), so
    they share exactly one lock."""
    from hermes_escape_top.config import load_config, resolve_path

    return resolve_path(load_config(), "archive_dir") / ".pipeline.lock"


@contextmanager
def pipeline_lock(
    blocking: bool = True,
    timeout: float = 600.0,
    poll: float = 0.5,
    path: Optional[Path] = None,
) -> Iterator[_PipelineLease]:
    """Hold an exclusive pipeline lock for the duration of the context.

    blocking=True  → wait up to ``timeout`` s for the lock, then raise
                     :class:`PipelineBusy` (the daily run must mutate, but must
                     never hang forever on a stuck holder).
    blocking=False → raise :class:`PipelineBusy` immediately if held (the WebUI
                     prefers a clean "busy, retry" over racing the writer).
    """
    lock_path = Path(path) if path is not None else pipeline_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    lease: Optional[_PipelineLease] = None
    try:
        if fcntl is None:  # pragma: no cover - no flock available off POSIX
            pass
        elif blocking:
            deadline = time.monotonic() + max(timeout, 0.0)
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise PipelineBusy(f"pipeline lock held > {timeout:.0f}s ({lock_path})")
                    time.sleep(poll)
                except InterruptedError:
                    continue
        else:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise PipelineBusy(f"pipeline busy ({lock_path})")
        lease = _PipelineLease(fd, lock_path)
        yield lease
    finally:
        if lease is not None:
            lease._deactivate()
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def atomic_write_csv(frame: Any, path: Any, **to_csv_kwargs: Any) -> None:
    """Write a DataFrame to CSV atomically: temp file in the same dir + replace.

    A concurrent reader sees either the old complete file or the new one, never a
    half-written file; a crash mid-write leaves the prior file intact. Same
    discipline as ``commit_state`` and ``rotate_audit_log``. The temp file is
    created in the destination dir so ``os.replace`` is a same-filesystem
    (atomic) rename, and is removed if the write fails.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    try:
        frame.to_csv(tmp, **to_csv_kwargs)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: Any, content: str) -> None:
    """Atomically replace a UTF-8 text file while preserving its mode."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o644
    fd, temp_name = tempfile.mkstemp(
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, target)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        temp.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Any, payload: Mapping[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
