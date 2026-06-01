"""Correlation-regime threshold sensitivity for Phase II shadow output.

Reads PhaseII_Shadow_Compare.json and recomputes only the correlation-regime
penalty layer. This is diagnostic only; it does not rerun scores, change live
config, or mutate trading state.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


HERMES_ROOT = Path(__file__).resolve().parents[1]


def run_corr_sensitivity(
    *,
    shadow_path: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    thresholds: Optional[List[float]] = None,
    penalties: Optional[List[float]] = None,
) -> Dict[str, Any]:
    out_dir = out_dir or HERMES_ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    shadow_path = shadow_path or out_dir / "PhaseII_Shadow_Compare.json"
    thresholds = thresholds or [92, 100, 110, 120, 130, 140, 150]
    penalties = penalties or [0.70, 0.80, 0.90]

    shadow = json.loads(shadow_path.read_text(encoding="utf-8"))
    rows = shadow.get("comparisons", [])
    if not rows:
        raise RuntimeError(f"No comparison rows in {shadow_path}")

    scenarios = []
    for threshold in thresholds:
        for penalty in penalties:
            scenarios.append(_evaluate_scenario(rows, threshold, penalty))

    base = _evaluate_scenario(rows, 92, 0.70)
    recommendation = _pick_review_candidate(scenarios)
    artifact = {
        "schema_version": "phase2-corr-sensitivity-v1",
        "source_shadow": str(shadow_path),
        "rows_evaluated": len(rows),
        "base_threshold": 92,
        "base_penalty": 0.70,
        "base": base,
        "scenarios": scenarios,
        "review_candidate": recommendation,
        "live_effect": "none",
        "notes": [
            "Reprices only the correlation-regime penalty layer from the shadow artifact.",
            "Does not change production/live config.",
            "Candidate is a review target, not an automatic parameter change.",
        ],
    }

    json_path = out_dir / "PhaseII_Corr_Sensitivity.json"
    md_path = out_dir / "PhaseII_Corr_Sensitivity.md"
    json_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_report(artifact, md_path)
    print(f"Phase II corr sensitivity artifact: {json_path}")
    print(f"Phase II corr sensitivity report: {md_path}")
    return artifact


def _evaluate_scenario(rows: List[Dict[str, Any]], threshold: float, penalty: float) -> Dict[str, Any]:
    simulated = []
    gross_delta = []
    hit_count = 0
    for row in rows:
        meta = row.get("risk_meta", {})
        pre_gross = _as_float(meta.get("gross_before_corr_penalty"), row.get("shadow_gross_scaler"))
        old_gross = _as_float(row.get("old_gross_scaler"), 1.0)
        ratio = _as_float(meta.get("downside_corr_ratio_score"), 0.0)
        is_hit = ratio >= threshold
        if is_hit:
            hit_count += 1
        gross = pre_gross * penalty if is_hit else pre_gross
        gross = max(0.0, min(1.0, gross))
        simulated.append(gross)
        gross_delta.append(gross - old_gross)

    return {
        "threshold": threshold,
        "penalty": penalty,
        "hit_count": hit_count,
        "hit_share": round(hit_count / len(rows), 6),
        "avg_gross": round(_mean(simulated), 6),
        "min_gross": round(min(simulated), 6),
        "avg_gross_delta": round(_mean(gross_delta), 6),
        "p10_gross": round(_percentile(simulated, 10), 6),
        "p50_gross": round(_percentile(simulated, 50), 6),
        "p90_gross": round(_percentile(simulated, 90), 6),
    }


def _pick_review_candidate(scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pick a non-live review candidate with moderate hit-rate and usable gross."""
    feasible = [
        s for s in scenarios
        if 0.25 <= float(s["hit_share"]) <= 0.55 and 0.78 <= float(s["avg_gross"]) <= 0.90
    ]
    if not feasible:
        feasible = scenarios
    return sorted(
        feasible,
        key=lambda s: (
            abs(float(s["hit_share"]) - 0.40),
            abs(float(s["avg_gross"]) - 0.84),
            float(s["threshold"]),
            float(s["penalty"]),
        ),
    )[0]


def _write_report(artifact: Dict[str, Any], path: Path) -> None:
    candidate = artifact.get("review_candidate", {})
    lines = [
        "# Phase II Corr Sensitivity",
        "",
        f"Source: `{artifact['source_shadow']}`",
        f"Rows evaluated: {artifact['rows_evaluated']}",
        f"Live effect: `{artifact['live_effect']}`",
        "",
        "## Review Candidate",
        "",
        "| Field | Value |",
        "|---|---:|",
        f"| Threshold | {_fmt(candidate.get('threshold'))} |",
        f"| Penalty | {_fmt(candidate.get('penalty'))} |",
        f"| Hit share | {_fmt_pct(candidate.get('hit_share'))} |",
        f"| Avg gross | {_fmt(candidate.get('avg_gross'))} |",
        f"| Min gross | {_fmt(candidate.get('min_gross'))} |",
        "",
        "## Scenario Grid",
        "",
        "| Threshold | Penalty | Hit Share | Avg Gross | Min Gross | P10 Gross | P50 Gross | Avg Gross Delta |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in artifact.get("scenarios", []):
        lines.append(
            f"| {_fmt(row.get('threshold'))} | {_fmt(row.get('penalty'))} | "
            f"{_fmt_pct(row.get('hit_share'))} | {_fmt(row.get('avg_gross'))} | "
            f"{_fmt(row.get('min_gross'))} | {_fmt(row.get('p10_gross'))} | "
            f"{_fmt(row.get('p50_gross'))} | {_fmt(row.get('avg_gross_delta'))} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Current base 92/0.70 is intentionally defensive but hit-rate is high in the 252-day replay.",
            "- A higher threshold delays the EXTREME_CORR penalty until downside correlation is clearly above ordinary correlation.",
            "- A higher penalty keeps the signal but reduces forced gross shrinkage.",
            "- Do not promote any scenario to live until it passes full backtest, walk-forward, and Phase III migration gates.",
            "",
            "## Notes",
            "",
        ]
    )
    for note in artifact.get("notes", []):
        lines.append(f"- {note}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _as_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(round((len(ordered) - 1) * pct / 100.0))
    return ordered[max(0, min(len(ordered) - 1, idx))]


def _fmt(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "n/a"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--shadow", default=None)
    args = parser.parse_args()
    run_corr_sensitivity(
        shadow_path=Path(args.shadow) if args.shadow else None,
    )
