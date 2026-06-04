from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from hermes_escape_top.core.features.indicators import indicator_frame
from hermes_escape_top.core.features.normalize import RollingNormalizer, to_score
from hermes_escape_top.core.features.regime import Regime, RegimeHysteresis, RegimeInput, classify_regime
from hermes_escape_top.core.features.volatility import (
    ewma_volatility,
    realized_volatility,
    relative_vol_scaler,
    volatility_snapshot,
)


class Phase2FeatureTest(unittest.TestCase):
    def test_indicator_frame_includes_platform_and_money_flow_fields(self) -> None:
        dates = pd.bdate_range("2026-01-01", periods=90)
        close = pd.Series(100 + np.linspace(0, 8, len(dates)) + np.sin(np.arange(len(dates))) * 1.5, index=dates)
        df = pd.DataFrame(
            {
                "Open": close.shift(1).fillna(close.iloc[0]),
                "High": close + 1.0,
                "Low": close - 1.0,
                "Close": close,
                "Volume": 1_000_000 + (np.arange(len(dates)) % 7) * 10_000,
            },
            index=dates,
        )
        out = indicator_frame(df)
        last = out.iloc[-1]
        for field in [
            "vwap20",
            "avwap_60d",
            "support_60d_low",
            "support_distance_60d_pct",
            "cmf20",
            "mfi14",
            "ad_line",
            "ad_slope20",
        ]:
            self.assertIn(field, out.columns)
            self.assertFalse(pd.isna(last[field]), field)

    def test_rolling_normalizer_is_causal(self) -> None:
        dates = pd.bdate_range("2025-01-01", periods=120)
        base = pd.Series(np.linspace(1.0, 120.0, len(dates)), index=dates)
        normalizer = RollingNormalizer(window=60, min_periods=20)
        anchor = dates[79]
        before_pct = normalizer.percentile(base).loc[anchor]
        before_z = normalizer.zscore(base).loc[anchor]

        mutated = base.copy()
        mutated.loc[dates[80]:] = 1000000.0
        after_pct = normalizer.percentile(mutated).loc[anchor]
        after_z = normalizer.zscore(mutated).loc[anchor]

        self.assertAlmostEqual(float(before_pct), float(after_pct))
        self.assertAlmostEqual(float(before_z), float(after_z))

    def test_percentile_to_score_preserves_missing(self) -> None:
        ladder = {95: 5, 90: 3, 80: 2, 70: 1}
        self.assertEqual(to_score(96, ladder), 5)
        self.assertEqual(to_score(91, ladder), 3)
        self.assertEqual(to_score(50, ladder), 0)
        self.assertIsNone(to_score(None, ladder))

    def test_volatility_forecast_and_scaler(self) -> None:
        low = pd.Series([0.004, -0.003, 0.002, -0.002] * 70)
        high = pd.Series([0.045, -0.040, 0.035, -0.030] * 15)
        returns = pd.concat([low, high], ignore_index=True)
        snap = volatility_snapshot(returns, baseline_window=120, floor=0.25)
        self.assertIsNotNone(snap.forecast_vol)
        self.assertIsNotNone(snap.baseline_vol)
        self.assertLess(snap.relative_scaler, 1.0)
        self.assertGreaterEqual(snap.relative_scaler, 0.25)

        forecast = float(ewma_volatility(returns).dropna().iloc[-1])
        baseline = float(realized_volatility(returns, window=20).rolling(120, min_periods=30).median().dropna().iloc[-1])
        self.assertEqual(relative_vol_scaler(None, baseline), 1.0)
        self.assertLess(relative_vol_scaler(forecast, baseline), 1.0)

    def test_regime_classifier(self) -> None:
        bull = classify_regime(
            RegimeInput(close=120, ema20=115, ema50=110, ma200=100, vix_percentile=40, vix_term_ratio=0.85)
        )
        self.assertEqual(bull, Regime.LOW_VOL_TREND)

        crisis = classify_regime(
            RegimeInput(close=90, ema20=95, ema50=100, ma200=110, vix_percentile=92, vix_term_ratio=1.05)
        )
        self.assertEqual(crisis, Regime.CRISIS)

        high_vol = classify_regime(
            RegimeInput(close=105, ema20=108, ema50=110, ma200=100, vix_percentile=72, vix_term_ratio=0.97)
        )
        self.assertEqual(high_vol, Regime.HIGH_VOL)

    def test_regime_hysteresis_enters_risk_fast_and_exits_slowly(self) -> None:
        hysteresis = RegimeHysteresis(current=Regime.LOW_VOL_TREND, min_dwell_days_on_exit=3)
        self.assertEqual(hysteresis.update(Regime.CRISIS), Regime.CRISIS)
        self.assertEqual(hysteresis.update(Regime.LOW_VOL_TREND), Regime.CRISIS)
        self.assertEqual(hysteresis.update(Regime.LOW_VOL_TREND), Regime.CRISIS)
        self.assertEqual(hysteresis.update(Regime.LOW_VOL_TREND), Regime.LOW_VOL_TREND)


if __name__ == "__main__":
    unittest.main()
