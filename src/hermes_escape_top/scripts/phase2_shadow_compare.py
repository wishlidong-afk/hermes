"""Phase II shadow comparison for the integration pipeline.

This is intentionally read-only: it replays historical scoring rows from
Backtest_FULL.json through the new pipeline and compares shadow sizing/risk
outputs with the existing routed backtest sizing. It does not change config,
state, signal journal, or live decisions.
"""
from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from hermes_escape_top.config import CONFIG_PATH, load_config
from hermes_escape_top.core.contracts import Verdict
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.core.pipeline import score_pipeline
from hermes_escape_top.integration_config import default_integration_config, phase_ii_overrides


HERMES_ROOT = Path(__file__).resolve().parents[1]


def run_phase2_shadow(
    *,
    backtest_path: Optional[Path] = None,
    days: int = 20,
    out_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    out_dir = out_dir or HERMES_ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    backtest_path = backtest_path or out_dir / "Backtest_FULL.json"

    rows = _load_rows(backtest_path)
    selected = rows[-max(1, int(days)) :]
    base_cfg = load_config(CONFIG_PATH)
    pipeline_cfg = _pipeline_config()
    store = _load_store(base_cfg, pipeline_cfg)

    comparisons: List[Dict[str, Any]] = []
    mode_counts: Counter = Counter()
    binding_counts: Counter = Counter()
    corr_regime_counts: Counter = Counter()
    max_abs_weight_delta = 0.0
    r3_violations = 0
    errors: List[Dict[str, str]] = []

    for row in selected:
        as_of = str(row["date"])
        daily_store = _slice_store(store, as_of)
        try:
            result = score_pipeline(
                as_of,
                daily_store,
                pipeline_cfg,
                scorer_fn=_scorer_from_row(row),
                verdict_fn=_verdict_from_row(row, pipeline_cfg),
            )
        except Exception as exc:
            errors.append({"date": as_of, "error": str(exc)})
            continue

        mode_counts[result.confidence.mode] += 1
        binding_counts[result.risk_state.binding] += 1
        corr_regime_counts[result.risk_state.corr_regime] += 1
        old_sizing = row.get("sizing", {})
        symbol_rows: Dict[str, Any] = {}
        for sym in pipeline_cfg["symbols"]:
            old_target = float(old_sizing.get(sym, {}).get("target_weight", 0.0) or 0.0)
            shadow_target = float(result.sizing.target_weights.get(sym, 0.0) or 0.0)
            rule_weight = float(result.verdicts[sym].rule_target_weight)
            delta = shadow_target - old_target
            max_abs_weight_delta = max(max_abs_weight_delta, abs(delta))
            if shadow_target > rule_weight + 1e-6:
                r3_violations += 1
            symbol_rows[sym] = {
                "status": result.verdicts[sym].status,
                "old_target_weight": round(old_target, 6),
                "shadow_target_weight": round(shadow_target, 6),
                "delta": round(delta, 6),
                "rule_weight": round(rule_weight, 6),
                "binding": result.sizing.binding_constraint.get(sym),
            }

        old_gross_values = [
            float(item.get("gross_scaler", 1.0) or 1.0)
            for item in old_sizing.values()
            if isinstance(item, dict)
        ]
        old_gross = max(old_gross_values) if old_gross_values else 1.0
        risk_meta = result.risk_state.estimator_meta
        comparisons.append(
            {
                "date": as_of,
                "confidence_mode": result.confidence.mode,
                "decision_confidence": result.confidence.decision_confidence,
                "weakest_link": result.confidence.weakest_link,
                "old_gross_scaler": round(old_gross, 6),
                "shadow_gross_scaler": round(float(result.risk_state.gross_scaler), 6),
                "gross_delta": round(float(result.risk_state.gross_scaler) - old_gross, 6),
                "risk_binding": result.risk_state.binding,
                "corr_regime": result.risk_state.corr_regime,
                "portfolio_vol": result.risk_state.portfolio_vol,
                "cvar": result.risk_state.cvar,
                "vol_scaler": result.risk_state.vol_scaler,
                "cvar_scaler": result.risk_state.cvar_scaler,
                "risk_meta": {
                    "n_obs": risk_meta.get("n_obs"),
                    "corr_mean": risk_meta.get("corr_mean"),
                    "downside_corr_mean": risk_meta.get("downside_corr_mean"),
                    "downside_corr_ratio_score": risk_meta.get("downside_corr_ratio_score"),
                    "corr_elevated_threshold": risk_meta.get("corr_elevated_threshold"),
                    "corr_extreme_threshold": risk_meta.get("corr_extreme_threshold"),
                    "gross_before_corr_penalty": risk_meta.get("gross_before_corr_penalty"),
                    "extreme_corr_penalty": risk_meta.get("extreme_corr_penalty"),
                },
                "risk_explain": list(result.risk_state.explain),
                "symbols": symbol_rows,
            }
        )

    artifact = {
        "schema_version": "phase2-shadow-v1",
        "source_backtest": str(backtest_path),
        "rows_requested": int(days),
        "rows_evaluated": len(comparisons),
        "errors": errors,
        "mode_counts": dict(mode_counts),
        "binding_counts": dict(binding_counts),
        "corr_regime_counts": dict(corr_regime_counts),
        "max_abs_weight_delta": round(max_abs_weight_delta, 6),
        "r3_violations": r3_violations,
        "diagnostics": _summarize_diagnostics(comparisons),
        "phase": "Phase II shadow",
        "live_effect": "none",
        "comparisons": comparisons,
        "notes": [
            "Uses historical Backtest_FULL scoring rows as scorer input.",
            "Runs new pipeline in shadow mode only; no production state or live config is changed.",
            "Sizing differences are diagnostic, not recommendations.",
        ],
    }
    json_path = out_dir / "PhaseII_Shadow_Compare.json"
    md_path = out_dir / "PhaseII_Shadow_Compare.md"
    json_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_report(artifact, md_path)
    print(f"Phase II shadow artifact: {json_path}")
    print(f"Phase II shadow report: {md_path}")
    return artifact


def _load_rows(path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text())
    rows = payload.get("rows", [])
    if not rows:
        raise RuntimeError(f"No rows in {path}")
    return rows


def _pipeline_config() -> Dict[str, Any]:
    cfg = default_integration_config()
    _deep_update(cfg, phase_ii_overrides())
    return cfg


def _load_store(base_cfg: Dict[str, Any], pipeline_cfg: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
    local = LocalStore(base_cfg)
    symbols = set(pipeline_cfg.get("symbols", []))
    symbols.update(["QQQ", "SPY", "^VIX", "SOXX", "BTC-USD"])
    result: Dict[str, pd.DataFrame] = {}
    for sym in sorted(symbols):
        df = local.load_history(sym)
        if df is None or df.empty:
            continue
        result[sym] = _lower_ohlcv(df)
    return result


def _lower_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    rename = {col: col.lower().replace(" ", "_") for col in df.columns}
    out = df.rename(columns=rename).copy()
    if "adj_close" in out.columns and "close" not in out.columns:
        out["close"] = out["adj_close"]
    return out


def _slice_store(store: Dict[str, pd.DataFrame], as_of: str) -> Dict[str, pd.DataFrame]:
    day = pd.Timestamp(as_of)
    return {sym: df.loc[df.index <= day].copy() for sym, df in store.items()}


def _scorer_from_row(row: Dict[str, Any]):
    row_scores = row.get("scores", {})

    def scorer(sym: str, store: Dict[str, pd.DataFrame], ctx: Any, cfg: Dict[str, Any]) -> Dict[str, Any]:
        payload = row_scores.get(sym, {})
        modules = payload.get("module_scores", {})
        return {
            "A": float(modules.get("A", 0.0) or 0.0),
            "B": float(modules.get("B", 0.0) or 0.0),
            "C": float(modules.get("C", 0.0) or 0.0),
            "D": float(modules.get("D", 0.0) or 0.0),
            "total": float(payload.get("final_score", payload.get("raw_total", 0.0)) or 0.0),
            "missing_weight": float(payload.get("missing_weight", 0.0) or 0.0),
        }

    return scorer


def _verdict_from_row(row: Dict[str, Any], cfg: Dict[str, Any]):
    row_scores = row.get("scores", {})
    sleeve_caps = cfg.get("sleeve_caps", {})

    def verdict(sym: str, score: Dict[str, Any], store: Dict[str, pd.DataFrame], cfg_inner: Dict[str, Any]) -> Verdict:
        payload = row_scores.get(sym, {})
        sell_fraction = float(payload.get("sell_fraction", 0.0) or 0.0)
        cap = float(sleeve_caps.get(sym, 0.0) or 0.0)
        return Verdict(
            symbol=sym,
            status=str(payload.get("status", "HOLD")),
            rule_target_weight=max(0.0, cap * (1.0 - sell_fraction)),
            sell_fraction=sell_fraction,
            hard_valve_hits=list(payload.get("hard_valve_hits", [])),
        )

    return verdict


def _deep_update(base: Dict[str, Any], override: Dict[str, Any]) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = copy.deepcopy(value)


def _write_report(artifact: Dict[str, Any], path: Path) -> None:
    diagnostics = artifact.get("diagnostics", {})
    lines = [
        "# Phase II Shadow Compare",
        "",
        f"Source: `{artifact['source_backtest']}`",
        f"Rows evaluated: {artifact['rows_evaluated']} / requested {artifact['rows_requested']}",
        f"Live effect: `{artifact['live_effect']}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Max abs weight delta | {artifact['max_abs_weight_delta']:.4f} |",
        f"| R3 violations | {artifact['r3_violations']} |",
        f"| Errors | {len(artifact['errors'])} |",
        f"| Avg shadow gross | {_fmt(diagnostics.get('avg_shadow_gross'))} |",
        f"| Min shadow gross | {_fmt(diagnostics.get('min_shadow_gross'))} |",
        f"| Avg gross delta | {_fmt(diagnostics.get('avg_gross_delta'))} |",
        f"| Extreme corr share | {_fmt_pct(diagnostics.get('extreme_corr_share'))} |",
        "",
        "## Confidence Modes",
        "",
        "| Mode | Count |",
        "|---|---:|",
    ]
    for mode, count in sorted(artifact["mode_counts"].items()):
        lines.append(f"| {mode} | {count} |")
    lines.extend(
        [
            "",
            "## Risk Bindings",
            "",
            "| Binding | Count |",
            "|---|---:|",
        ]
    )
    for binding, count in sorted(artifact.get("binding_counts", {}).items()):
        lines.append(f"| {binding} | {count} |")
    lines.extend(
        [
            "",
            "## Correlation Regimes",
            "",
            "| Regime | Count |",
            "|---|---:|",
        ]
    )
    for regime, count in sorted(artifact.get("corr_regime_counts", {}).items()):
        lines.append(f"| {regime} | {count} |")
    lines.extend(
        [
            "",
            "## Corr Diagnostics",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Avg ordinary corr mean | {_fmt(diagnostics.get('avg_corr_mean'))} |",
            f"| Avg downside corr mean | {_fmt(diagnostics.get('avg_downside_corr_mean'))} |",
            f"| Avg downside/ordinary ratio score | {_fmt(diagnostics.get('avg_downside_corr_ratio_score'))} |",
            f"| Extreme threshold | {_fmt(diagnostics.get('corr_extreme_threshold'))} |",
            f"| Avg pre-penalty gross | {_fmt(diagnostics.get('avg_gross_before_corr_penalty'))} |",
        ]
    )
    lines.extend(
        [
            "",
            "## Daily Shadow Rows",
            "",
            "| Date | Confidence | Weakest | Old Gross | Shadow Gross | Pre-Corr Gross | Risk Binding | Corr Regime | Ratio Score | Max Symbol Delta |",
            "|---|---:|---|---:|---:|---:|---|---|---:|---:|",
        ]
    )
    for row in artifact["comparisons"]:
        max_delta = max(abs(float(item["delta"])) for item in row["symbols"].values()) if row["symbols"] else 0.0
        meta = row.get("risk_meta", {})
        lines.append(
            f"| {row['date']} | {row['confidence_mode']} {row['decision_confidence']:.4f} | {row['weakest_link']} | "
            f"{row['old_gross_scaler']:.4f} | {row['shadow_gross_scaler']:.4f} | "
            f"{_fmt(meta.get('gross_before_corr_penalty'))} | {row['risk_binding']} | {row['corr_regime']} | "
            f"{_fmt(meta.get('downside_corr_ratio_score'))} | {max_delta:.4f} |"
        )
    top_rows = diagnostics.get("most_defensive_rows", [])
    if top_rows:
        lines.extend(
            [
                "",
                "## Most Defensive Rows",
                "",
                "| Date | Shadow Gross | Binding | Corr Regime | Ordinary Corr | Downside Corr | Ratio Score |",
                "|---|---:|---|---|---:|---:|---:|",
            ]
        )
        for row in top_rows:
            lines.append(
                f"| {row['date']} | {_fmt(row.get('shadow_gross_scaler'))} | {row.get('risk_binding')} | "
                f"{row.get('corr_regime')} | {_fmt(row.get('corr_mean'))} | "
                f"{_fmt(row.get('downside_corr_mean'))} | {_fmt(row.get('downside_corr_ratio_score'))} |"
            )
    if diagnostics.get("interpretation"):
        lines.extend(["", "## Interpretation", ""])
        for item in diagnostics["interpretation"]:
            lines.append(f"- {item}")
    lines.extend(["", "## Notes", ""])
    for note in artifact.get("notes", []):
        lines.append(f"- {note}")
    if artifact.get("errors"):
        lines.extend(["", "## Errors", ""])
        for err in artifact["errors"]:
            lines.append(f"- {err['date']}: {err['error']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _summarize_diagnostics(comparisons: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not comparisons:
        return {}

    shadow_gross = [_as_float(row.get("shadow_gross_scaler")) for row in comparisons]
    gross_delta = [_as_float(row.get("gross_delta")) for row in comparisons]
    corr_means = [_as_float(row.get("risk_meta", {}).get("corr_mean")) for row in comparisons]
    downside_means = [_as_float(row.get("risk_meta", {}).get("downside_corr_mean")) for row in comparisons]
    ratio_scores = [_as_float(row.get("risk_meta", {}).get("downside_corr_ratio_score")) for row in comparisons]
    pre_penalty = [_as_float(row.get("risk_meta", {}).get("gross_before_corr_penalty")) for row in comparisons]

    extreme_count = sum(1 for row in comparisons if row.get("corr_regime") == "EXTREME")
    threshold_values = [
        _as_float(row.get("risk_meta", {}).get("corr_extreme_threshold"))
        for row in comparisons
        if row.get("risk_meta", {}).get("corr_extreme_threshold") is not None
    ]
    most_defensive = sorted(comparisons, key=lambda r: _as_float(r.get("shadow_gross_scaler")))[:10]
    most_defensive_rows = []
    for row in most_defensive:
        meta = row.get("risk_meta", {})
        most_defensive_rows.append(
            {
                "date": row.get("date"),
                "shadow_gross_scaler": row.get("shadow_gross_scaler"),
                "risk_binding": row.get("risk_binding"),
                "corr_regime": row.get("corr_regime"),
                "corr_mean": meta.get("corr_mean"),
                "downside_corr_mean": meta.get("downside_corr_mean"),
                "downside_corr_ratio_score": meta.get("downside_corr_ratio_score"),
            }
        )

    avg_ratio = _safe_mean(ratio_scores)
    avg_corr = _safe_mean(corr_means)
    avg_downside = _safe_mean(downside_means)
    extreme_share = extreme_count / len(comparisons)
    interpretation = [
        "EXTREME_CORR compares left-tail correlation against ordinary correlation, not absolute correlation alone.",
        "If ratio score is above the extreme threshold, the engine applies extreme_corr_penalty after VOL/CVAR scaling.",
    ]
    if extreme_share >= 0.50:
        interpretation.append(
            "More than half of the replay window is EXTREME_CORR; Phase III should not replace the old scaler until this risk budget is calibrated over a longer window."
        )
    if avg_downside > avg_corr:
        interpretation.append(
            "Average downside correlation is higher than ordinary correlation, so the new risk layer is detecting crash-correlation clustering rather than random noise."
        )
    if _safe_mean(pre_penalty) and _safe_mean(shadow_gross) < _safe_mean(pre_penalty):
        interpretation.append(
            "Shadow gross is lower than pre-penalty gross because the correlation-regime penalty is binding on EXTREME days."
        )

    return {
        "avg_shadow_gross": round(_safe_mean(shadow_gross), 6),
        "min_shadow_gross": round(min(shadow_gross), 6),
        "max_shadow_gross": round(max(shadow_gross), 6),
        "avg_gross_delta": round(_safe_mean(gross_delta), 6),
        "extreme_corr_share": round(extreme_share, 6),
        "avg_corr_mean": round(avg_corr, 6),
        "avg_downside_corr_mean": round(avg_downside, 6),
        "avg_downside_corr_ratio_score": round(avg_ratio, 6),
        "corr_extreme_threshold": round(_safe_mean(threshold_values), 6) if threshold_values else None,
        "avg_gross_before_corr_penalty": round(_safe_mean(pre_penalty), 6),
        "most_defensive_rows": most_defensive_rows,
        "interpretation": interpretation,
    }


def _as_float(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return out if pd.notna(out) else 0.0


def _safe_mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "n/a"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backtest", default=None)
    parser.add_argument("--days", type=int, default=20)
    args = parser.parse_args()
    run_phase2_shadow(
        backtest_path=Path(args.backtest) if args.backtest else None,
        days=args.days,
    )
