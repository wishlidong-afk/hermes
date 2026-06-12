#!/usr/bin/env python3
"""AAII member-session XLS fallback (deep history / public-probe outage).

Design (per 2026-06-12 plan): never store credentials. Reuse a persistent
browser profile that a human logged into once; this script only drives the
download and feeds the existing parse_aaii_sentiment_xls() path.

Until a Playwright/Chrome-profile runner is configured this is an explicit,
honest stub: it checks the prerequisites and reports AAII_LOGIN_REQUIRED
instead of pretending. The weekly public probe (refresh_aaii_public) is the
primary path and needs no login.

Usage: AAII_BROWSER_PROFILE=~/path/to/profile python3 -m hermes_escape_top.scripts.refresh_aaii_member
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

DOWNLOAD_URL = "https://www.aaii.com/files/surveys/sentiment.xls"


def main() -> int:
    profile = os.environ.get("AAII_BROWSER_PROFILE")
    if not profile or not Path(profile).expanduser().exists():
        print("AAII_LOGIN_REQUIRED: no browser profile configured "
              "(set AAII_BROWSER_PROFILE to a Chrome/Playwright profile dir "
              "after a one-time manual login; credentials are never stored)")
        return 1
    try:
        from playwright.sync_api import sync_playwright  # type: ignore # noqa: F401
    except ImportError:
        print("AAII_LOGIN_REQUIRED: playwright not installed "
              "(pip install playwright && playwright install chromium), "
              "or run the Claude-in-Chrome manual procedure from the runbook")
        return 1
    print("profile + playwright present — driver not yet implemented; "
          "use the manual runbook procedure for now")
    return 1


if __name__ == "__main__":
    sys.exit(main())
