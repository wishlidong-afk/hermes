from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from hermes_escape_top.core.safe_io import pipeline_lock


def _run_helper(archive_dir: Path, *command: str, timeout: float = 2.0):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "hermes_escape_top.scripts.pipeline_lock_exec",
            "--archive-dir",
            str(archive_dir),
            "--timeout",
            str(timeout),
            "--",
            *command,
        ],
        env=env,
        capture_output=True,
        text=True,
    )


def test_helper_returns_guarded_command_exit_code(tmp_path):
    result = _run_helper(tmp_path, sys.executable, "-c", "raise SystemExit(7)")
    assert result.returncode == 7


def test_guarded_child_observes_same_lock_as_busy(tmp_path):
    child = """
import os
import sys
from pathlib import Path
from hermes_escape_top.core.safe_io import PipelineBusy, pipeline_lock
fd = int(os.environ["HERMES_PIPELINE_LOCK_FD"])
assert Path(f"/dev/fd/{fd}").exists()
try:
    with pipeline_lock(blocking=False, path=Path(sys.argv[1])):
        raise SystemExit(9)
except PipelineBusy:
    raise SystemExit(0)
"""
    result = _run_helper(
        tmp_path,
        sys.executable,
        "-c",
        child,
        str(tmp_path / ".pipeline.lock"),
    )
    assert result.returncode == 0, result.stderr


def test_helper_timeout_uses_distinct_exit_code(tmp_path):
    lock_path = tmp_path / ".pipeline.lock"
    with pipeline_lock(blocking=False, path=lock_path):
        result = _run_helper(
            tmp_path,
            sys.executable,
            "-c",
            "raise SystemExit(0)",
            timeout=0.0,
        )
    assert result.returncode == 75
    assert "pipeline lock held" in result.stderr
