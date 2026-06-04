#!/usr/bin/env python3
"""Hermes live daily entrypoint.

The implementation lives in src/hermes_escape_top/scripts/run_daily_package.py.
This root shim keeps deployment/runbook paths stable.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_RUNNER = ROOT / "scripts" / "run_daily_package.py"


if __name__ == "__main__":
    cmd = [sys.executable, str(PACKAGE_RUNNER), "--live", "--commit-state", *sys.argv[1:]]
    raise SystemExit(subprocess.run(cmd, cwd=str(ROOT)).returncode)
