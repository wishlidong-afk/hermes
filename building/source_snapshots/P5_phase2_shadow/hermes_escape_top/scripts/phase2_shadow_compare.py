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
        "max_abs_weight_delta": round(max_abs_weight_delta, 6),
        "r3_violations": r3_violations,
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
            "## Daily Shadow Rows",
            "",
            "| Date | Confidence | Weakest | Old Gross | Shadow Gross | Risk Binding | Corr Regime | Max Symbol Delta |",
            "|---|---:|---|---:|---:|---|---|---:|",
        ]
    )
    for row in artifact["comparisons"]:
        max_delta = max(abs(float(item["delta"])) for item in row["symbols"].values()) if row["symbols"] else 0.0
        lines.append(
            f"| {row['date']} | {row['confidence_mode']} {row['decision_confidence']:.4f} | {row['weakest_link']} | "
            f"{row['old_gross_scaler']:.4f} | {row['shadow_gross_scaler']:.4f} | "
            f"{row['risk_binding']} | {row['corr_regime']} | {max_delta:.4f} |"
        )
    lines.extend(["", "## Notes", ""])
    for note in artifact.get("notes", []):
        lines.append(f"- {note}")
    if artifact.get("errors"):
        lines.extend(["", "## Errors", ""])
        for err in artifact["errors"]:
            lines.append(f"- {err['date']}: {err['error']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backtest", default=None)
    parser.add_argument("--days", type=int, default=20)
    args = parser.parse_args()
    run_phase2_shadow(
        backtest_path=Path(args.backtest) if args.backtest else None,
        days=args.days,
    )
