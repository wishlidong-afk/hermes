#!/usr/bin/env python3
"""Root shim for read-only IBKR live verification."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" if (ROOT / "src" / "hermes_escape_top").exists() else ROOT
RUNNER = SRC / "hermes_escape_top" / "scripts" / "ibkr_live_check.py"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

runpy.run_path(str(RUNNER), run_name="__main__")
