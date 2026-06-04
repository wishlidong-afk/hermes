#!/usr/bin/env python3
"""Root shim for the package run-daily wrapper."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
RUNNER = SRC / "hermes_escape_top" / "scripts" / "run_daily_package.py"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

runpy.run_path(str(RUNNER), run_name="__main__")
