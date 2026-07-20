"""#3 — pipeline mutex + atomic CSV writes."""
import os
import stat
import threading
import time
from unittest import mock

import pandas as pd
import pytest

from hermes_escape_top.core.safe_io import (
    PipelineBusy,
    assert_pipeline_lease,
    atomic_write_csv,
    atomic_write_text,
    pipeline_lock,
)


def test_nonblocking_lock_conflicts_even_same_process(tmp_path):
    # The load-bearing assumption: a second non-blocking acquire on a SEPARATE fd
    # of the same process still sees the lock as held. This is what serializes two
    # ThreadingHTTPServer handler threads (each opens its own fd).
    lock = tmp_path / ".pipeline.lock"
    with pipeline_lock(blocking=False, path=lock):
        with pytest.raises(PipelineBusy):
            with pipeline_lock(blocking=False, path=lock):
                pass


def test_lock_released_on_exit_and_reacquirable(tmp_path):
    lock = tmp_path / ".pipeline.lock"
    with pipeline_lock(blocking=False, path=lock):
        pass
    with pipeline_lock(blocking=False, path=lock):  # released → re-acquire works
        pass


def test_pipeline_lease_is_active_only_inside_owning_context(tmp_path):
    lock = tmp_path / ".pipeline.lock"
    with pipeline_lock(blocking=False, path=lock) as lease:
        assert_pipeline_lease(lease, path=lock)
    with pytest.raises(RuntimeError, match="inactive"):
        assert_pipeline_lease(lease, path=lock)


def test_pipeline_lease_cannot_cross_threads(tmp_path):
    lock = tmp_path / ".pipeline.lock"
    errors = []
    with pipeline_lock(blocking=False, path=lock) as lease:
        thread = threading.Thread(
            target=lambda: _capture_lease_error(errors, lease, lock),
        )
        thread.start()
        thread.join(timeout=5)
    assert len(errors) == 1
    assert "thread" in str(errors[0])


def test_lock_does_not_leak_on_exception(tmp_path):
    lock = tmp_path / ".pipeline.lock"
    with pytest.raises(ValueError):
        with pipeline_lock(blocking=False, path=lock):
            raise ValueError("boom")
    with pipeline_lock(blocking=False, path=lock):  # must be free after the error
        pass


def test_blocking_lock_times_out_when_held(tmp_path):
    lock = tmp_path / ".pipeline.lock"
    with pipeline_lock(blocking=False, path=lock):
        start = time.monotonic()
        with pytest.raises(PipelineBusy):
            with pipeline_lock(blocking=True, timeout=0.3, poll=0.05, path=lock):
                pass
        assert time.monotonic() - start >= 0.3


def test_atomic_write_csv_writes_and_leaves_no_temp(tmp_path):
    path = tmp_path / "soft" / "x.csv"  # nested dir is created
    df = pd.DataFrame({"date": ["2026-06-18"], "v": [1.0]})
    atomic_write_csv(df, path, index=False)
    assert path.exists()
    back = pd.read_csv(path)
    assert list(back["date"]) == ["2026-06-18"] and list(back["v"]) == [1.0]
    assert not list(path.parent.glob("*.tmp"))  # no residue


def test_atomic_write_csv_keeps_old_file_on_failure(tmp_path):
    path = tmp_path / "x.csv"
    atomic_write_csv(pd.DataFrame({"a": [1]}), path, index=False)
    original = path.read_text()

    class _Boom:
        def to_csv(self, *a, **k):
            raise RuntimeError("write failed mid-way")

    with pytest.raises(RuntimeError):
        atomic_write_csv(_Boom(), path, index=False)
    assert path.read_text() == original          # reader still sees the old file
    assert not list(path.parent.glob("*.tmp"))   # temp cleaned up


def test_atomic_write_csv_preserves_existing_mode(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("a\n1\n", encoding="utf-8")
    os.chmod(path, 0o644)

    atomic_write_csv(pd.DataFrame({"a": [2]}), path, index=False)

    assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_atomic_write_text_keeps_old_file_when_replace_fails(tmp_path):
    path = tmp_path / "report.json"
    path.write_text("old\n", encoding="utf-8")

    with mock.patch("hermes_escape_top.core.safe_io.os.replace", side_effect=OSError("replace failed")):
        with pytest.raises(OSError, match="replace failed"):
            atomic_write_text(path, "new\n")

    assert path.read_text(encoding="utf-8") == "old\n"
    assert not list(tmp_path.glob("*.tmp"))


def _capture_lease_error(errors, lease, path):
    try:
        assert_pipeline_lease(lease, path=path)
    except Exception as exc:
        errors.append(exc)
