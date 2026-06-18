"""#3 — pipeline mutex + atomic CSV writes."""
import time

import pandas as pd
import pytest

from hermes_escape_top.core.safe_io import PipelineBusy, atomic_write_csv, pipeline_lock


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
