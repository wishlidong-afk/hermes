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

Acquire the lock ONLY at the two top entry points (``run_daily_package.main`` and
the web ``do_POST`` handler), never inside a shared helper: a locked function
that called another locked function would self-deadlock, because ``flock`` on a
second fd of the same process conflicts with the first.
"""
from __future__ import annotations

import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

try:
    import fcntl  # POSIX (macOS/Linux); this system only ever runs on darwin
except ImportError:  # pragma: no cover - Windows has no flock
    fcntl = None  # type: ignore


class PipelineBusy(RuntimeError):
    """Raised when the pipeline lock is held and the caller asked not to wait."""


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
) -> Iterator[None]:
    """Hold an exclusive pipeline lock for the duration of the context.

    blocking=True  → wait up to ``timeout`` s for the lock, then raise
                     :class:`PipelineBusy` (the daily run must mutate, but must
                     never hang forever on a stuck holder).
    blocking=False → raise :class:`PipelineBusy` immediately if held (the WebUI
                     prefers a clean "busy, retry" over racing the writer).
    """
    lock_path = Path(path) if path is not None else pipeline_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None:  # pragma: no cover - no flock available off POSIX
        yield
        return
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if blocking:
            deadline = time.monotonic() + max(timeout, 0.0)
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except (BlockingIOError, OSError):
                    if time.monotonic() >= deadline:
                        raise PipelineBusy(f"pipeline lock held > {timeout:.0f}s ({lock_path})")
                    time.sleep(poll)
        else:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError):
                raise PipelineBusy(f"pipeline busy ({lock_path})")
        yield
    finally:
        try:
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
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    try:
        frame.to_csv(tmp, **to_csv_kwargs)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
