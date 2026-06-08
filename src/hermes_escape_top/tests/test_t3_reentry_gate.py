from __future__ import annotations

import unittest
from datetime import date, timedelta

import pandas as pd

from hermes_escape_top.core.reentry.plan import _t3_market_gate
from hermes_escape_top.core.data.base import Field, SymbolSnapshot


def _frame(closes: list[float], end: date) -> pd.DataFrame:
    idx = pd.bdate_range(end=pd.Timestamp(end), periods=len(closes))
    return pd.DataFrame({"Close": closes}, index=idx)


def _scenario(today_close: float, ma200: float):
    """300 bars: deep dip to 60 then recovering; `today_close` is the latest bar."""
    end = date(2026, 1, 2)
    base = [100.0] * 100 + [60.0] * 60 + [70.0] * 139 + [today_close]
    frame = _frame(base, end)
    snap = SymbolSnapshot(
        "QQQ", end, {"close": Field("close", today_close, "u", end), "ma200": Field("ma200", ma200, "u", end)}
    )
    return {"QQQ": snap}, {"QQQ": frame}


class T3GateTest(unittest.TestCase):
    def test_default_requires_full_252d_high(self) -> None:
        # today=75 is below the 100-region 252D high → default gate stays locked.
        snaps, hist = _scenario(today_close=75.0, ma200=72.0)
        self.assertFalse(_t3_market_gate(snaps, hist, {}))
        # only a true new high (>=100) clears the default.
        snaps2, hist2 = _scenario(today_close=101.0, ma200=72.0)
        self.assertTrue(_t3_market_gate(snaps2, hist2, {"t3_gate_mode": "market_252d_high"}))

    def test_ma200_reclaim_clears_earlier(self) -> None:
        # 75 vs 60D low 70 = +7.1%; above MA200 72. Default OFF, ma200 mode ON at 5% floor.
        snaps, hist = _scenario(today_close=75.0, ma200=72.0)
        cfg = {"t3_gate_mode": "ma200_reclaim", "t3_off_low_pct": 0.05}
        self.assertTrue(_t3_market_gate(snaps, hist, cfg))
        # raise the rebound floor above 7.1% → not yet.
        cfg_strict = {"t3_gate_mode": "ma200_reclaim", "t3_off_low_pct": 0.15}
        self.assertFalse(_t3_market_gate(snaps, hist, cfg_strict))
        # below MA200 never clears regardless of rebound.
        snaps_below, hist_below = _scenario(today_close=75.0, ma200=80.0)
        self.assertFalse(_t3_market_gate(snaps_below, hist_below, cfg))

    def test_shorter_high_clears_on_quarter_high(self) -> None:
        # today 71 exceeds the trailing 63-bar high (the 70 plateau) → clears.
        snaps, hist = _scenario(today_close=71.0, ma200=72.0)
        cfg = {"t3_gate_mode": "shorter_high", "t3_high_lookback": 63}
        self.assertTrue(_t3_market_gate(snaps, hist, cfg))


if __name__ == "__main__":
    unittest.main()
