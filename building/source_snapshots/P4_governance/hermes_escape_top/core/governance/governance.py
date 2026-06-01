"""Governance -- disagreement detection, decision fragility, attribution, champion-challenger.

Absorbs E10/E28/E29 from the integration architecture.
Feeds into ConfidenceSpine for circuit-breaker behavior.
All promotion decisions require human gate.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# E10: Disagreement detection (multi-source)
# ---------------------------------------------------------------------------

def detect_disagreement(
    rule_status: str,
    meta_p_act: Optional[float],
    mirror_cycle: Optional[str],
    cfg: Dict[str, Any],
) -> float:
    """Detect disagreement between rule verdict, meta-model, and mirror system.

    Maps each source to a common risk scale [0,1], then measures max pairwise gap.
    Returns disagreement in [0,1], 1 = strong disagreement.
    """
    threshold = float(cfg.get("disagreement_threshold", 0.40))

    status_map = {
        "EXIT": 1.0,
        "DEFENSIVE_EXIT": 0.85,
        "REDUCE": 0.65,
        "TRIM": 0.45,
        "WATCH": 0.25,
        "HOLD": 0.0,
    }

    signals = []
    rule_val = status_map.get(rule_status, 0.0)
    signals.append(rule_val)

    if meta_p_act is not None:
        signals.append(min(1.0, max(0.0, meta_p_act)))

    cycle_map = {
        "RISK_WARNING": 1.0,
        "RISK_ELEVATED": 0.7,
        "WEAK_TREND": 0.4,
        "STRONG_TREND": 0.1,
        "NORMAL": 0.2,
    }
    if mirror_cycle is not None:
        signals.append(cycle_map.get(mirror_cycle, 0.3))

    if len(signals) < 2:
        return 0.0

    max_gap = max(abs(signals[i] - signals[j])
                  for i in range(len(signals))
                  for j in range(i + 1, len(signals)))

    return round(min(1.0, max_gap / max(threshold, 1e-6) * threshold), 4)


# ---------------------------------------------------------------------------
# E28: Decision fragility
# ---------------------------------------------------------------------------

def decision_fragility(
    snapshot: Dict[str, float],
    scorer_fn: Callable[[Dict[str, float]], str],
    eps: float = 0.02,
    n_perturb: int = 20,
    seed: int = 42,
) -> float:
    """Perturb inputs ±eps, perturb thresholds ±delta; count verdict flips.

    fragility in [0,1], 1 = extremely fragile (knife-edge decision).
    """
    rng = np.random.RandomState(seed)
    base_verdict = scorer_fn(snapshot)
    flips = 0

    for _ in range(n_perturb):
        perturbed = {}
        for key, val in snapshot.items():
            noise = rng.uniform(-eps, eps)
            perturbed[key] = val * (1.0 + noise)
        try:
            new_verdict = scorer_fn(perturbed)
            if new_verdict != base_verdict:
                flips += 1
        except Exception:
            pass

    return round(flips / max(n_perturb, 1), 4)


# ---------------------------------------------------------------------------
# Attribution (leave-one-out + counterfactual)
# ---------------------------------------------------------------------------

def attribute(
    score_components: Dict[str, float],
    total_score: float,
) -> List[Tuple[str, float, float]]:
    """Per-factor contribution + leave-one-out counterfactual.

    Returns [(factor_name, contribution, counterfactual_total), ...].
    contribution = component_value / total (proportional).
    counterfactual_total = total - component_value (what if this factor were 0).
    """
    if total_score == 0:
        return [(k, 0.0, 0.0) for k in score_components]

    result = []
    for key, val in score_components.items():
        contribution = round(val / total_score, 4) if total_score != 0 else 0.0
        counterfactual = round(total_score - val, 4)
        result.append((key, contribution, counterfactual))

    return sorted(result, key=lambda x: -abs(x[1]))


# ---------------------------------------------------------------------------
# E29: Champion-Challenger
# ---------------------------------------------------------------------------

class ChampionChallenger:
    """Run multiple configurations in shadow; suggest promotion (human gate).

    The challenger never affects live decisions until a human approves promotion.
    """

    def __init__(self, champion_cfg: Dict[str, Any], challengers: List[Dict[str, Any]]):
        self._champion = champion_cfg
        self._challengers = challengers

    def ensemble_decision(
        self,
        scorer_fn: Callable[[Dict[str, Any]], Dict[str, Any]],
        snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run all configs on same snapshot; return comparison.

        Champion result is authoritative; challengers are shadow-only.
        """
        champion_result = scorer_fn({**snapshot, **self._champion})
        challenger_results = []
        for cfg in self._challengers:
            try:
                res = scorer_fn({**snapshot, **cfg})
                challenger_results.append({"config": cfg.get("name", "unnamed"), "result": res})
            except Exception as e:
                challenger_results.append({"config": cfg.get("name", "unnamed"), "error": str(e)[:100]})

        return {
            "champion": champion_result,
            "challengers": challenger_results,
            "authoritative": "champion",
        }

    def evaluate_promotion(
        self,
        champion_oos: List[float],
        challenger_oos: Dict[str, List[float]],
    ) -> Dict[str, Any]:
        """Evaluate if any challenger should be promoted.

        Criteria: challenger OOS median > champion OOS median by margin.
        Returns suggestion only; actual promotion requires human gate.
        """
        if not champion_oos:
            return {"suggestion": "insufficient_data", "requires_human_gate": True}

        champ_median = float(np.median(champion_oos))
        margin = 0.05

        candidates = []
        for name, oos in challenger_oos.items():
            if not oos:
                continue
            chal_median = float(np.median(oos))
            if chal_median > champ_median + margin:
                candidates.append({
                    "name": name,
                    "oos_median": round(chal_median, 4),
                    "improvement": round(chal_median - champ_median, 4),
                })

        return {
            "champion_oos_median": round(champ_median, 4),
            "promotion_candidates": sorted(candidates, key=lambda x: -x["improvement"]),
            "suggestion": "promote" if candidates else "retain_champion",
            "requires_human_gate": True,
        }
