#!/usr/bin/env python3
"""run_daily.py — M4 live: runs the package engine as a module (single source of truth).

There is no loose run_daily_package.py copy any more. _discover_runtime_paths in
the package walks UP to locate hermes_escape_top, so `python -m` resolves the
engine — and every subprocess's PYTHONPATH — from escape-top/ no matter how deep
the file sits. Before 2026-06-17 this ran a shallower loose copy that silently
drifted from the package (the B incident: daily ran 4-day-stale orchestration).
Rollback: scripts/run_daily.py.bak_prepkg_<stamp> (+ restore the loose copy).
"""
import os
import subprocess
import sys
from pathlib import Path

ESCAPE_TOP = Path(__file__).resolve().parent.parent  # .../escape-top, holds hermes_escape_top/
PYTHON = sys.executable

if __name__ == "__main__":
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ESCAPE_TOP) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    cmd = [PYTHON, "-m", "hermes_escape_top.scripts.run_daily_package",
           "--live", "--commit-state"] + sys.argv[1:]
    r = subprocess.run(cmd, cwd=str(ESCAPE_TOP), env=env)
    sys.exit(r.returncode)
