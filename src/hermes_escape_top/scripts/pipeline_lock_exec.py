"""Run one command while holding the Hermes pipeline mutex."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from hermes_escape_top.config import load_config, resolve_path
from hermes_escape_top.core.safe_io import (
    PipelineBusy,
    pipeline_lease_fd,
    pipeline_lock,
)

LOCK_TIMEOUT_EXIT = 75
COMMAND_ERROR_EXIT = 126


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-dir", type=Path)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = list(args.command)
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        print("pipeline_lock_exec: missing command after --", file=sys.stderr)
        return COMMAND_ERROR_EXIT

    archive_dir = args.archive_dir or resolve_path(load_config(), "archive_dir")
    lock_path = Path(archive_dir) / ".pipeline.lock"
    try:
        with pipeline_lock(
            blocking=True,
            timeout=max(float(args.timeout), 0.0),
            path=lock_path,
        ) as lease:
            # Inheriting the same open file description keeps the lock alive if
            # this wrapper is interrupted while the guarded child is still up.
            lock_fd = pipeline_lease_fd(lease)
            child_env = dict(os.environ)
            child_env["HERMES_PIPELINE_LOCK_FD"] = str(lock_fd)
            result = subprocess.run(
                command,
                env=child_env,
                pass_fds=(lock_fd,),
            )
            return int(result.returncode)
    except PipelineBusy as exc:
        print(f"pipeline_lock_exec: {exc}", file=sys.stderr)
        return LOCK_TIMEOUT_EXIT
    except OSError as exc:
        print(f"pipeline_lock_exec: command failed to start: {exc}", file=sys.stderr)
        return COMMAND_ERROR_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
