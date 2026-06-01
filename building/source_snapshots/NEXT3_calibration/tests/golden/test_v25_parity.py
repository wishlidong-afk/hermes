from __future__ import annotations

import math
import re
import sys
import unittest

from .golden_utils import BASE_DIR, FIXTURE_DIR, GOLDEN_PATH, build_projection, load_escape_module, read_golden

REPLAY_GOLDEN_PATH = FIXTURE_DIR / "v25_replay_degraded_golden.json"

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.portfolio.invariants import assert_not_more_aggressive


_FLOAT_TEXT_RE = re.compile(r"(?<![A-Za-z0-9_])-?\d+\.\d+")


def _normalize_numeric_text(value: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return f"{float(match.group(0)):.6f}"

    return _FLOAT_TEXT_RE.sub(repl, value)


def _assert_json_near(testcase: unittest.TestCase, expected, current, path: str = "$") -> None:
    if isinstance(expected, dict):
        testcase.assertIsInstance(current, dict, path)
        testcase.assertEqual(set(expected.keys()), set(current.keys()), path)
        for key in expected:
            _assert_json_near(testcase, expected[key], current[key], f"{path}.{key}")
        return
    if isinstance(expected, list):
        testcase.assertIsInstance(current, list, path)
        testcase.assertEqual(len(expected), len(current), path)
        for idx, (expected_item, current_item) in enumerate(zip(expected, current)):
            _assert_json_near(testcase, expected_item, current_item, f"{path}[{idx}]")
        return
    if isinstance(expected, float) and isinstance(current, (int, float)) and not isinstance(current, bool):
        testcase.assertTrue(
            math.isclose(float(expected), float(current), rel_tol=1e-10, abs_tol=1e-6),
            f"{path}: expected {expected!r}, got {current!r}",
        )
        return
    if isinstance(expected, str) and isinstance(current, str) and expected != current:
        testcase.assertEqual(_normalize_numeric_text(expected), _normalize_numeric_text(current), path)
        return
    testcase.assertEqual(expected, current, path)


class V25GoldenParityTest(unittest.TestCase):
    maxDiff = None

    def test_v25_projection_matches_golden(self) -> None:
        if not GOLDEN_PATH.exists():
            self.fail(f"Missing golden fixture. Run: python3 {BASE_DIR / 'tests/golden/generate_v25_golden.py'}")
        ets = load_escape_module()
        current = build_projection(ets, FIXTURE_DIR)
        _assert_json_near(self, read_golden(), current)

    def test_hard_trigger_wrapper_accepts_injected_histories_without_io(self) -> None:
        ets = load_escape_module()
        install_snap = {
            "date": "2026-05-29",
            "close": 500.0,
            "ma200": 100.0,
            "ema10": 490.0,
            "ema20": 480.0,
            "return_1d": 0.01,
            "return_2d": 0.02,
            "drawdown_60d_high_pct": -0.01,
            "chandelier_exit_22_4_5x": 100.0,
        }

        def fail_load_history(symbol: str):  # pragma: no cover - should never run
            raise AssertionError(f"Unexpected hidden history load for {symbol}")

        ets.load_history = fail_load_history
        hard = ets.hard_triggers(
            "MSTR",
            install_snap,
            market={},
            radars={"BTC-USD": {"close": 100.0, "ma50": 200.0}},
            histories={},
        )
        self.assertFalse(hard["triggered"])

    def test_offline_replay_does_not_use_latest_enrichment_fallback(self) -> None:
        ets = load_escape_module()
        enriched, meta = ets.load_enrichment_for_as_of(
            {"runtime": {"offline_replay_mode": True}},
            "2024-01-03",
        )
        self.assertEqual(enriched, {})
        self.assertTrue(meta["offline_replay_mode"])
        self.assertIn("daily_archive/enrichment_cache_2024-01-03.json", meta["cache_path"])

    def test_r3_invariant_skeleton_currently_equal_to_v25(self) -> None:
        golden = read_golden()
        for date, rows in golden["results"].items():
            for symbol, result in rows.items():
                with self.subTest(date=date, symbol=symbol):
                    v25_target = 1.0 - float(result["sell_pct"]) / 100.0
                    assert_not_more_aggressive(v25_target, v25_target, v25_target)

    def test_replay_degraded_golden_expanded_to_20_dates(self) -> None:
        if not REPLAY_GOLDEN_PATH.exists():
            self.fail(f"Missing replay fixture. Run: python3 {BASE_DIR / 'tests/golden/generate_replay_degraded_golden.py'}")
        replay = __import__("json").loads(REPLAY_GOLDEN_PATH.read_text())
        self.assertGreaterEqual(len(replay["sample_dates"]), 20)
        self.assertGreaterEqual(replay["sample_count"], 60)
        self.assertEqual(replay["degraded_ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()
