"""Standalone verification of the CODE_REVIEW_FOLLOWUP fixes.

The full pipeline needs 17 unmigrated modules, but the fixed math
(build_risk_state, compute_confidence, optimize_targets) is self-contained
and can be exercised directly against synthetic inputs. This asserts the
fixes behave as intended.
"""
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "src"))

import numpy as np
import pandas as pd

from hermes_escape_top.core.contracts import Verdict, ConfidenceState, RiskState
from hermes_escape_top.core.confidence.spine import compute_confidence
from hermes_escape_top.core.portfolio.risk_engine import (
    build_risk_state, ledoit_wolf_shrink, downside_vs_linear_ratio, _shrinkage_intensity,
)
from hermes_escape_top.core.portfolio.sizing_optimizer import (
    optimize_targets, kelly_fraction, _shrink_expected_returns, _solve_grid,
)

rng = np.random.default_rng(42)
fails = []
def check(name, cond):
    print(("  PASS" if cond else "  FAIL"), name)
    if not cond:
        fails.append(name)

# Build correlated 3-leg synthetic returns (high-beta leveraged ETF-ish).
n = 600
base = rng.normal(0.0008, 0.02, n)
legs = {
    "FNGU": pd.Series(base * 3 + rng.normal(0, 0.01, n)),
    "SOXL": pd.Series(base * 3 + rng.normal(0, 0.012, n)),
    "MSTR": pd.Series(base * 1.5 + rng.normal(0, 0.03, n)),
}
weights = {"FNGU": 0.2, "SOXL": 0.2, "MSTR": 0.2}

print("\n[S2] risk_engine — shrinkage honesty + EXTREME_CORR consistency")
# _shrinkage_intensity: bounded, more shrink with fewer obs
si_lo, si_hi = _shrinkage_intensity(3, 1000), _shrinkage_intensity(3, 10)
check("shrinkage intensity in [0,1]", 0 <= si_lo <= 1 and 0 <= si_hi <= 1)
check("fewer obs -> more shrinkage", si_hi > si_lo)
corr = np.array([[1, .8, .7], [.8, 1, .75], [.7, .75, 1]])
sh = ledoit_wolf_shrink(corr, 252)
check("shrunk matrix diagonal == 1", np.allclose(np.diag(sh), 1.0))
check("shrunk off-diag < raw off-diag", abs(sh[0, 1]) < abs(corr[0, 1]))
# regime ratio uses a single estimator -> both means from same Pearson sample
df = pd.DataFrame(legs)
pair = downside_vs_linear_ratio(df, 0.10)
check("downside_vs_linear_ratio returns a pair", pair is not None and len(pair) == 2)
tail_mean, lin_mean = pair
check("ratio components are finite", np.isfinite(tail_mean) and np.isfinite(lin_mean))

rs = build_risk_state(legs, weights, None, {"risk_engine": {"min_periods": 40}})
check("build_risk_state runs, regime set", rs.corr_regime in ("NORMAL", "ELEVATED", "EXTREME", "UNKNOWN"))
check("gross_scaler in [0,1]", 0 <= rs.gross_scaler <= 1)
check("RC keyed by symbol not leg_i", set(rs.risk_contributions).issubset(set(legs)) or rs.risk_contributions == {})

print("\n[S1] confidence spine — healthy inputs must NOT be permanently DEGRADED")
healthy = compute_confidence(
    data_conf=0.85, failover_state={"is_degraded": False}, staleness_days=0.0,
    drift_state={"psi": 0.0, "alert": False}, fragility=0.0, disagreement=0.0,
    cfg={},
)
print("   healthy confidence=%.3f mode=%s" % (healthy.decision_confidence, healthy.mode))
check("healthy data -> NORMAL (not DEGRADED)", healthy.mode == "NORMAL")
# The old bug: all-None inputs collapsed to 0.5/DEGRADED
buggy = compute_confidence(None, None, None, None, None, None, {})
check("all-None still DEGRADED (documents the trap we now avoid)", buggy.mode == "DEGRADED")
# missing data lowers confidence (red line)
poor = compute_confidence(0.2, {"is_degraded": False}, 0.0, {"psi": 0, "alert": False}, 0.0, 0.0, {})
check("low data_conf lowers confidence vs healthy", poor.decision_confidence < healthy.decision_confidence)

print("\n[S3/S4] sizing optimizer — Kelly off by default, mu shrinkage, no near-zero")
rule = {"FNGU": 0.2, "SOXL": 0.2, "MSTR": 0.2}
verdicts = {s: Verdict(symbol=s, status="HOLD", rule_target_weight=w, sell_fraction=0.0) for s, w in rule.items()}
conf = ConfidenceState(decision_confidence=healthy.decision_confidence, mode=healthy.mode,
                       components=healthy.components, weakest_link=healthy.weakest_link)
cfg = {"sizing": {"dd_aversion": 3.0, "leverage_L": {"FNGU": 3, "SOXL": 3, "MSTR": 1}}}
dec = optimize_targets(verdicts, rs, conf, cfg, leg_returns=legs)
tot = sum(dec.target_weights.values())
print("   proxy-mode target_weights=%s sum=%.4f" % ({k: round(v, 4) for k, v in dec.target_weights.items()}, tot))
check("default proxy mode -> weights not crushed to ~0 (posture preserved)", tot > 0.05 * sum(rule.values()))
check("R3 respected (w_i <= rule_i)", all(dec.target_weights[s] <= rule[s] + 1e-9 for s in rule))

# historical_tilt mode (opt-in): when the optimizer's OWN vol budget binds, the
# higher-trailing-return leg should receive MORE than the others. Build a
# RiskState where gross=1 and the budget binds at the upper bounds (corr=0.8).
c = 0.8 * 0.04
cov3 = np.array([[0.04, c, c], [c, 0.04, c], [c, c, 0.04]])
rs_bind = RiskState(
    cov=cov3, corr=np.full((3, 3), 0.8), downside_corr=np.full((3, 3), 0.8),
    leg_vol={"FNGU": 0.2, "MSTR": 0.2, "SOXL": 0.2}, legs_used=["FNGU", "MSTR", "SOXL"],
    legs_reported=["FNGU", "MSTR", "SOXL"], portfolio_vol=0.3, cvar=-0.05,
    vol_budget=0.30, cvar_budget=0.08, vol_scaler=1.0, cvar_scaler=1.0, gross_scaler=1.0,
    risk_contributions={}, factor_betas={}, book_factor_exposure={},
    corr_regime="NORMAL", binding="NONE", explain=[],
)
rule_b = {"FNGU": 0.8, "MSTR": 0.8, "SOXL": 0.8}
verd_b = {s: Verdict(symbol=s, status="HOLD", rule_target_weight=w, sell_fraction=0.0) for s, w in rule_b.items()}
conf_full = ConfidenceState(decision_confidence=1.0, mode="NORMAL", components={}, weakest_link="data")
legs_tilt = dict(legs)
legs_tilt["FNGU"] = pd.Series(base * 3 + 0.004 + rng.normal(0, 0.01, n))  # clearly higher mean
cfg_tilt = {"sizing": {"dd_aversion": 3.0, "mu_mode": "historical_tilt"}}
dec_tilt = optimize_targets(verd_b, rs_bind, conf_full, cfg_tilt, leg_returns=legs_tilt)
print("   tilt-mode  target_weights=%s" % {k: round(v, 4) for k, v in dec_tilt.target_weights.items()})
check("historical_tilt runs and respects R3",
      all(dec_tilt.target_weights[s] <= rule_b[s] + 1e-9 for s in rule_b))
check("historical_tilt favours higher-return leg (FNGU >= others) under binding budget",
      dec_tilt.target_weights["FNGU"] >= dec_tilt.target_weights["SOXL"] - 1e-9
      and dec_tilt.target_weights["FNGU"] >= dec_tilt.target_weights["MSTR"] - 1e-9)
check("historical_tilt actually differentiates (FNGU strictly largest)",
      dec_tilt.target_weights["FNGU"] > max(dec_tilt.target_weights["SOXL"], dec_tilt.target_weights["MSTR"]) + 1e-6)

# Kelly enabled without p_act must raise (category-error guard)
raised = False
try:
    optimize_targets(verdicts, rs, conf, {"sizing": {"kelly": {"enabled": True}}}, leg_returns=legs)
except ValueError:
    raised = True
check("kelly.enabled without p_act raises ValueError", raised)

# mu shrinkage pulls toward cross-sectional mean
shrunk = _shrink_expected_returns({"a": 1.0, "b": 0.0}, 0.5)
check("mu shrink toward grand mean", abs(shrunk["a"] - 0.75) < 1e-9 and abs(shrunk["b"] - 0.25) < 1e-9)
check("mu shrink=0 is identity", _shrink_expected_returns({"a": 1.0, "b": 0.0}, 0.0) == {"a": 1.0, "b": 0.0})

# grid generalizes to n>3 without the old upper*0.3 cliff (feasible, R3-respecting)
up = np.array([0.1, 0.1, 0.1, 0.1])
cov4 = np.eye(4) * 0.04
mu4 = np.array([0.3, 0.2, 0.1, 0.05])
w4 = _solve_grid(mu4, cov4, up, vol_budget=0.35, dd_aversion=3.0, n=4)
check("grid n=4 returns feasible vector within bounds", np.all(w4 >= -1e-9) and np.all(w4 <= up + 1e-9))

print("\n[S3] CVaR no longer a (redundant) solver constraint")
import inspect
from hermes_escape_top.core.portfolio import sizing_optimizer as so
check("_cvar_normal_factor removed", not hasattr(so, "_cvar_normal_factor"))
check("_solve_slsqp signature has no cvar params",
      "cvar" not in str(inspect.signature(so._solve_slsqp)))

print("\n=== RESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}", "===")
sys.exit(1 if fails else 0)
