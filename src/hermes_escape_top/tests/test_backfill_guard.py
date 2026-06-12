"""Download sanity guard (2026-06-12 cross-wired yfinance incident)."""
from __future__ import annotations

import pandas as pd

from hermes_escape_top.scripts.backfill_history import _sanity_check_download


def _frame(closes, start="2026-06-01"):
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({"Close": closes}, index=idx)


def test_cross_wired_append_rejected():
    existing = _frame([700, 705, 710])
    wrong_ticker = _frame([218, 217, 220], start="2026-06-04")
    ok, why = _sanity_check_download("QQQ", existing, wrong_ticker)
    assert not ok and "boundary jump" in why


def test_normal_append_accepted():
    existing = _frame([700, 705, 710])
    ok, _ = _sanity_check_download("QQQ", existing, _frame([715, 720], start="2026-06-04"))
    assert ok


def test_vol_index_gets_wider_band_but_still_catches_cross_wiring():
    existing = _frame([15.4])
    ok, _ = _sanity_check_download("^VIX", existing, _frame([38.0], start="2026-06-02"))
    assert ok  # VIX 2.5x in a day is a real regime, not corruption
    ok, why = _sanity_check_download("^VIX", existing, _frame([12906.0], start="2026-06-02"))
    assert not ok  # ^SOX values under a ^VIX name


def test_overlap_anchor_mismatch_rejected():
    existing = _frame([700, 705, 710, 715, 720])
    garbage_repair = _frame([210, 212, 215, 214], start="2026-06-02")
    ok, why = _sanity_check_download("QQQ", existing, garbage_repair)
    assert not ok and "anchor" in why


def test_overlap_anchor_match_accepts_repair():
    existing = _frame([700, 705, 31.4, 715, 720])      # one corrupt mid row
    repair = _frame([705, 708, 712, 718], start="2026-06-02")  # anchors on clean 705
    ok, _ = _sanity_check_download("FNGS", existing, repair)
    assert ok
