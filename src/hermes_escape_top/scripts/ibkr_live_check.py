#!/usr/bin/env python3
"""Read-only IBKR live verification CLI."""
from __future__ import annotations

import argparse
import json
from datetime import date

from hermes_escape_top.ibkr.live_check import run_live_check


def main() -> None:
    parser = argparse.ArgumentParser(description="Run read-only IBKR live verification")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--no-report", action="store_true", help="Do not write archive reports")
    args = parser.parse_args()
    payload = run_live_check(args.as_of, write_report=not args.no_report)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    raise SystemExit(0 if payload.get("ok") else 2)


if __name__ == "__main__":
    main()
