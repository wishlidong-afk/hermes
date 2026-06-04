"""Integration Configuration -- single source of truth for all engine parameters.

Per INTEGRATION_ARCHITECTURE §10, this config covers:
- confidence spine thresholds
- risk engine parameters (vol model, corr model, budgets)
- sizing optimizer (dd aversion, kelly, leverage map, solver)
- governance (disagreement, fragility, degraded behavior)
- validation (CPCV, PBO, bootstrap, adversarial)
- drift monitoring thresholds
- feature flags for Phase II-IV rollout

All parameters here are shadow-only defaults. Live activation requires human gate.
"""

from __future__ import annotations

from typing import Any, Dict


def default_integration_config() -> Dict[str, Any]:
    """Return the complete default integration config."""
    return {
        # ── Symbols and Sleeves ──
        "symbols": ["MSTR", "FNGU", "SOXL"],
        "sleeve_caps": {"MSTR": 0.15, "FNGU": 0.20, "SOXL": 0.30},

        # ── Verdict thresholds (from NEXT-3 v2 calibration) ──
        "thresholds": {
            "exit": 75,
            "defensive_exit": 65,
            "reduce": 50,
            "trim": 35,
            "watch": 20,
        },
        "sell_fractions": {
            "MSTR": {"TRIM": 0.25, "REDUCE": 0.50, "DEFENSIVE_EXIT": 0.75, "EXIT": 1.0},
            "FNGU": {"TRIM": 0.35, "REDUCE": 0.60, "DEFENSIVE_EXIT": 0.85, "EXIT": 1.0},
            "SOXL": {"TRIM": 0.35, "REDUCE": 0.60, "DEFENSIVE_EXIT": 0.85, "EXIT": 1.0},
        },

        # ── ConfidenceSpine (§2) ──
        "confidence": {
            "tau_stale": 3,
            "weakest_weight": 0.60,
            "normal_threshold": 0.80,
            "caution_threshold": 0.55,
            "drift_psi_threshold": 0.25,
        },

        # ── RiskEngine (§3) ──
        "risk_engine": {
            "vol_model": "har_rv",
            "corr_model": "ewma",
            "ewma_lambda": 0.94,
            "min_periods": 40,
            "har_min_obs": 66,
            "cvar_alpha": 0.95,
            "vol_budget_annual": 0.35,
            "cvar_budget": 0.08,
            # P10 approved calibration: threshold=110 / penalty=0.90.
            "extreme_corr_penalty": 0.90,
            "downside_q": 0.10,
            "corr_regime_extreme_ratio": 110,
            "corr_regime_elevated_ratio": 80,
            "concentration_cap": {"BTC": 0.50},
        },

        # ── SizingOptimizer (§7) ──
        "sizing": {
            "dd_aversion": 3.0,
            "kelly": {
                # Off until a calibrated p_act model is wired. Using decision
                # confidence as win probability is a category error.
                "enabled": False,
                "frac": 0.30,
                "payoff_ratio": 2.0,
                "ci_width": 0.0,
            },
            "leverage_L": {"FNGU": 3, "SOXL": 3, "MSTR": 1},
            "solver": "slsqp_or_grid",
            "exec_slices": 3,
            "liquidity": {
                "max_liquidation_days": 3,
                "participation_rate": 0.10,
            },
            "mu_mode": "proxy",
        },

        # ── Governance (§8) ──
        "governance": {
            "disagreement_threshold": 0.40,
            "fragility_eps": 0.02,
            "fragility_perturb": 20,
            "degraded_requires_human": True,
        },

        # ── ValidationHarness (§6) ──
        "validation": {
            "n_groups": 6,
            "n_test": 2,
            "embargo_pct": 0.02,
            "label_horizon": 20,
            "pbo_max": 0.50,
            "bootstrap_n": 2000,
            "adversarial_auc_max": 0.65,
        },

        # ── DriftMonitor (E9) ──
        "drift": {
            "psi_threshold": 0.25,
            "precision_drop_threshold": 0.10,
            "ic_decay_threshold": 0.50,
        },

        # ── Regime (E7) ──
        "regime": {
            "crisis_vol": 0.50,
            "high_vol": 0.30,
            "low_vol": 0.15,
            "transition_lookback": 20,
        },

        # ── Data Sanitization (E1) ──
        "sanitize": {
            "bad_tick_ret_threshold": 0.15,
            "split_gap_threshold": 0.40,
            "stale_days_threshold": 3,
            "outlier_sigma": 5.0,
            "cross_source_tolerance": 0.02,
        },

        # ── Leader Map (E17) ──
        "leader_map": {
            "MSTR": "BTC-USD",
            "SOXL": "SOXX",
            "FNGU": "QQQ",
        },

        # ── Feature Flags (Phase II-IV rollout, all OFF by default) ──
        "features": {
            "use_risk_engine": False,
            "use_sizing_optimizer": False,
            "use_confidence_spine": False,
            "use_factor_calibration": False,
            "use_market_context": False,
            "use_drift_monitor": False,
            "use_governance": False,
            "use_validation_harness": False,
            "use_meta_label": False,
        },

        # ── Calibration reference ──
        "calibration_ref": "building/reports/calibration_v2.json",
        "data_manifest_ref": None,
    }


def phase_ii_overrides() -> Dict[str, Any]:
    """Phase II: Risk & Signal integration overrides.

    Enables risk engine and market context in shadow mode.
    Does NOT enable sizing optimizer (that's Phase III).
    """
    return {
        "features": {
            "use_risk_engine": True,
            "use_confidence_spine": True,
            "use_market_context": True,
            "use_drift_monitor": True,
        },
    }


def phase_iii_overrides() -> Dict[str, Any]:
    """Phase III: Unified sizing overrides.

    Enables sizing optimizer, replacing old scaler chains.
    """
    return {
        "features": {
            "use_risk_engine": True,
            "use_sizing_optimizer": True,
            "use_confidence_spine": True,
            "use_market_context": True,
            "use_drift_monitor": True,
            "use_governance": True,
        },
    }


def phase_iv_overrides() -> Dict[str, Any]:
    """Phase IV: Validation & governance overrides.

    Full integration, all gates enabled for validation.
    """
    return {
        "features": {
            "use_risk_engine": True,
            "use_sizing_optimizer": True,
            "use_confidence_spine": True,
            "use_factor_calibration": True,
            "use_market_context": True,
            "use_drift_monitor": True,
            "use_governance": True,
            "use_validation_harness": True,
        },
    }
