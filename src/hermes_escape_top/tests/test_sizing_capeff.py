from __future__ import annotations

import numpy as np
import unittest

from hermes_escape_top.core.portfolio.sizing_optimizer import _cap_vol_factors


class CapVolFactorTest(unittest.TestCase):
    def test_off_when_fewer_than_two_vols(self) -> None:
        f = _cap_vol_factors(["MSTR"], {"MSTR": 0.6}, {})
        self.assertTrue(np.allclose(f, [1.0]))

    def test_calmest_keeps_full_others_shrink(self) -> None:
        syms = ["FNGU", "MSTR", "SOXL"]
        leg_vol = {"MSTR": 0.60, "FNGU": 0.90, "SOXL": 1.20}
        f = _cap_vol_factors(syms, leg_vol, {"cap_vol_floor": 0.3})
        # ref = min vol = 0.60 (MSTR) → MSTR factor 1.0; others = 0.60/vol.
        self.assertAlmostEqual(f[syms.index("MSTR")], 1.0, places=6)
        self.assertAlmostEqual(f[syms.index("FNGU")], 0.60 / 0.90, places=6)
        self.assertAlmostEqual(f[syms.index("SOXL")], 0.60 / 1.20, places=6)
        # never exceeds 1.0 (never more aggressive).
        self.assertTrue(np.all(f <= 1.0 + 1e-12))

    def test_floor_clips_extreme_ratio(self) -> None:
        syms = ["A", "B"]
        f = _cap_vol_factors(syms, {"A": 0.20, "B": 2.00}, {"cap_vol_floor": 0.5})
        # 0.20/2.00 = 0.10 but floored at 0.5.
        self.assertAlmostEqual(f[syms.index("B")], 0.5, places=6)

    def test_missing_vol_is_neutral(self) -> None:
        syms = ["A", "B", "C"]
        f = _cap_vol_factors(syms, {"A": 0.5, "B": 1.0}, {})  # C missing
        self.assertAlmostEqual(f[syms.index("C")], 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
