#!/usr/bin/env python3
"""run_daily.py — M4 live: runs the package engine as a module (single source of truth).

There is no loose run_daily_package.py copy any more. _discover_runtime_paths in
the package walks UP to locate hermes_escape_top, so `python -m` resolves the
engine — and every subprocess's PYTHONPATH — from escape-top/ no matter how deep
the file sits. Before 2026-06-17 this ran a shallower loose copy that silently
drifted from the package (the B incident: daily ran 4-day-stale orchestration).
Rollback: scripts/run_daily.py.bak_prepkg_<stamp> (+ restore the loose copy).

`--deploy-verify` traverses the same package entry as a manual preview without
committing state or stamping the scheduled-run receipt.
"""
import os
import subprocess
import sys
from pathlib import Path

ESCAPE_TOP = Path(__file__).resolve().parent.parent  # .../escape-top, holds hermes_escape_top/
RUNTIME_ROOT = Path(os.environ.get("HERMES_RUNTIME_ROOT", str(ESCAPE_TOP))).expanduser().resolve()
PYTHON = sys.executable


def build_command(args):
    deploy_verify = "--deploy-verify" in args
    forwarded = [arg for arg in args if arg != "--deploy-verify"]
    cmd = [PYTHON, "-m", "hermes_escape_top.scripts.run_daily_package", "--live"]
    if deploy_verify:
        if forwarded:
            raise SystemExit("--deploy-verify does not accept additional arguments")
        cmd.extend(["--run-type", "manual_rerun"])
    else:
        cmd.append("--commit-state")
        cmd.extend(forwarded)
    return cmd


if __name__ == "__main__":
    env = dict(os.environ)
    env["HERMES_RUNTIME_ROOT"] = str(RUNTIME_ROOT)
    env["PYTHONPATH"] = str(ESCAPE_TOP) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    cmd = build_command(sys.argv[1:])
    r = subprocess.run(cmd, cwd=str(RUNTIME_ROOT), env=env)
    sys.exit(r.returncode)
