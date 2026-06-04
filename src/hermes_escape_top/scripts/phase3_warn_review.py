"""Phase III WARN review pack for the dry-run comparator.

This script is a read-only human-gate helper.  It consumes
PhaseIII_Dry_Run_Comparator.json, classifies WARN rows, and measures how the
candidate route would have performed versus the old route over short forward
holding windows.  It never changes live config, feature flags, account state,
or signal journal files.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

from hermes_escape_top.config import CONFIG_PATH, load_config
from hermes_escape_top.core.backtest.run_full import _load_histories, _price_panel
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.scripts.phase2_full_backtest_sensitivity import HERMES_ROOT, _fmt, _fmt_pct, _safe_suffix


DEFAULT_LOOKAHEADS = [1, 5, 10]


def run_phase3_warn_review(
    *,
    comparator_path: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    lookaheads: Optional[List[int]] = None,
    suffix: str = "",
) -> Dict[str, Any]:
    out_dir = out_dir or HERMES_ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    comparator_path = comparator_path or out_dir / "PhaseIII_Dry_Run_Comparator.json"
    lookaheads = sorted({int(x) for x in (lookaheads or DEFAULT_LOOKAHEADS) if int(x) > 0})

    comparator = json.loads(comparator_path.read_text(encoding="utf-8"))
    rows = comparator.get("daily_rows", [])
    if not rows:
        raise RuntimeError(f"No daily_rows in {comparator_path}")
    price_frame = _build_price_frame(rows)

    enriched = []
    reason_counts: Counter = Counter()
    month_counts: Counter = Counter()
    gate_counts: Counter = Counter()
    for row in rows:
        gate_status = str(row.get("gate", {}).get("status", "UNKNOWN"))
        gate_counts[gate_status] += 1
        categories = _categorize_reasons(row.get("gate", {}).get("reasons", []))
        if gate_status == "WARN":
            reason_counts.update(categories)
            month_counts[_month_key(row.get("date"))] += 1
        forward = {}
        for horizon in lookaheads:
            old_ret = _forward_weighted_return(row.get("old_route_leg_weights", {}), price_frame, str(row["date"]), horizon)
            new_ret = _forward_weighted_return(row.get("new_route_leg_weights", {}), price_frame, str(row["date"]), horizon)
            forward[str(horizon)] = {
                "old": _round_optional(old_ret),
                "candidate": _round_optional(new_ret),
                "delta": _round_optional(None if old_ret is None or new_ret is None else new_ret - old_ret),
            }
        enriched.append(
            {
                "date": row.get("date"),
                "gate": row.get("gate", {}),
                "categories": categories,
                "risk": row.get("risk", {}),
                "turnover": row.get("turnover", {}),
                "max_symbol_delta": round(_max_abs(row.get("target_deltas", {}).values()), 6),
                "max_route_leg_delta": round(_max_abs(row.get("route_leg_deltas", {}).values()), 6),
                "target_deltas": row.get("target_deltas", {}),
                "route_leg_deltas": row.get("route_leg_deltas", {}),
                "forward_returns": forward,
            }
        )

    warn_rows = [row for row in enriched if row.get("gate", {}).get("status") == "WARN"]
    pass_rows = [row for row in enriched if row.get("gate", {}).get("status") == "PASS"]
    category_stats = _category_stats(warn_rows, lookaheads)
    artifact = {
        "schema_version": "phase3-warn-review-v1",
        "source_comparator": str(comparator_path),
        "candidate": comparator.get("candidate", {}),
        "rows_evaluated": len(rows),
        "lookaheads": lookaheads,
        "gate_counts": dict(gate_counts),
        "reason_category_counts": dict(reason_counts),
        "warn_month_counts": dict(sorted(month_counts.items())),
        "warn_forward_stats": _forward_stats(warn_rows, lookaheads),
        "pass_forward_stats": _forward_stats(pass_rows, lookaheads),
        "category_forward_stats": category_stats,
        "top_warn_rows": {
            "largest_symbol_delta": _top_rows(warn_rows, "max_symbol_delta", 20),
            "largest_route_delta": _top_rows(warn_rows, "max_route_leg_delta", 20),
            "largest_abs_turnover_delta": _top_turnover_rows(warn_rows, 20),
            "largest_candidate_drag_1d": _top_forward_delta_rows(warn_rows, 1, 20, reverse=False),
            "largest_candidate_benefit_1d": _top_forward_delta_rows(warn_rows, 1, 20, reverse=True),
        },
        "readiness": _readiness(comparator, warn_rows, lookaheads),
        "live_effect": "none",
        "notes": [
            "Read-only human-gate helper; no live config, feature flag, account state, signal journal, or order routing is changed.",
            "Forward returns use same-day route weights held over the next N trading days on the local price panel.",
            "This report does not approve scaler migration.  It only organizes WARN evidence for human review.",
        ],
    }
    safe_suffix = _safe_suffix(suffix)
    json_path = out_dir / f"PhaseIII_WARN_Review{safe_suffix}.json"
    md_path = out_dir / f"PhaseIII_WARN_Review{safe_suffix}.md"
    json_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_report(artifact, md_path)
    print(f"Phase III WARN review artifact: {json_path}")
    print(f"Phase III WARN review report: {md_path}")
    return artifact


def _build_price_frame(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    legs = sorted(
        {
            str(leg)
            for row in rows
            for weights in (row.get("old_route_leg_weights", {}), row.get("new_route_leg_weights", {}))
            for leg in weights
        }
    )
    dates = [str(row["date"]) for row in rows]
    cfg = load_config(CONFIG_PATH)
    histories = _load_histories(LocalStore(cfg), cfg)
    panel = _price_panel(legs, dates, histories)
    frame = pd.DataFrame({leg: pd.to_numeric(series, errors="coerce") for leg, series in panel.items()})
    return frame.sort_index().ffill().bfill()


def _categorize_reasons(reasons: Iterable[str]) -> List[str]:
    categories: List[str] = []
    for reason in reasons:
        text = str(reason)
        if "R3" in text:
            categories.append("R3")
        if "route gross" in text:
            categories.append("ROUTE_GROSS")
        if "max symbol delta" in text:
            categories.append("SYMBOL_DELTA")
        if "max route leg delta" in text:
            categories.append("ROUTE_LEG_DELTA")
        if "turnover delta" in text:
            categories.append("TURNOVER_DELTA")
        if "EXTREME_CORR" in text:
            categories.append("EXTREME_CORR")
        if "corr regime=EXTREME" in text:
            categories.append("EXTREME_REGIME")
        if "scenario gross" in text:
            categories.append("LOW_GROSS")
    return sorted(set(categories)) or ["TOLERANCE"]


def _forward_weighted_return(weights: Dict[str, Any], price_frame: pd.DataFrame, date: str, horizon: int) -> Optional[float]:
    if price_frame.empty:
        return None
    day = pd.Timestamp(date)
    if day not in price_frame.index:
        return None
    pos = int(price_frame.index.get_loc(day))
    future_pos = pos + int(horizon)
    if future_pos >= len(price_frame.index):
        return None
    start = price_frame.iloc[pos]
    end = price_frame.iloc[future_pos]
    total = 0.0
    used = False
    for leg, raw_weight in weights.items():
        if leg not in price_frame.columns:
            continue
        weight = float(raw_weight or 0.0)
        start_price = float(start[leg])
        end_price = float(end[leg])
        if start_price <= 0 or pd.isna(start_price) or pd.isna(end_price):
            continue
        total += weight * (end_price / start_price - 1.0)
        used = True
    return float(total) if used else None


def _forward_stats(rows: List[Dict[str, Any]], lookaheads: List[int]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for horizon in lookaheads:
        values = [
            row.get("forward_returns", {}).get(str(horizon), {}).get("delta")
            for row in rows
            if row.get("forward_returns", {}).get(str(horizon), {}).get("delta") is not None
        ]
        out[str(horizon)] = _series_stats(values)
    return out


def _category_stats(warn_rows: List[Dict[str, Any]], lookaheads: List[int]) -> Dict[str, Any]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in warn_rows:
        for category in row.get("categories", []):
            grouped[category].append(row)
    return {
        category: {
            "count": len(rows),
            "avg_abs_turnover_delta": round(_mean([abs(float(row.get("turnover", {}).get("delta", 0.0) or 0.0)) for row in rows]), 6),
            "forward_delta": _forward_stats(rows, lookaheads),
        }
        for category, rows in sorted(grouped.items())
    }


def _readiness(comparator: Dict[str, Any], warn_rows: List[Dict[str, Any]], lookaheads: List[int]) -> Dict[str, Any]:
    summary = comparator.get("summary", {})
    blockers = []
    if int(summary.get("r3_violations", 0) or 0) > 0:
        blockers.append("R3 violations present")
    if int(summary.get("gate_counts", {}).get("BLOCK", 0) or 0) > 0:
        blockers.append("BLOCK rows present")
    max_turnover = float(summary.get("max_abs_turnover_delta", 0.0) or 0.0)
    if max_turnover >= 0.30:
        blockers.append("max turnover delta requires human review")
    warn_share = len(warn_rows) / max(1, int(comparator.get("rows_evaluated", len(warn_rows)) or len(warn_rows)))
    status = "BLOCKED" if any("R3" in item or "BLOCK" in item for item in blockers) else "REVIEW_REQUIRED"
    return {
        "status": status,
        "warn_share": round(float(warn_share), 6),
        "blockers_or_review_items": blockers or ["No invariant blockers; WARN rows still require human review"],
        "next_step": "Human-review WARN clusters and turnover outliers before scaler migration design.",
        "live_promotion": "BLOCKED",
    }


def _top_rows(rows: List[Dict[str, Any]], key: str, limit: int) -> List[Dict[str, Any]]:
    ranked = sorted(rows, key=lambda row: float(row.get(key, 0.0) or 0.0), reverse=True)
    return [_public_row(row, horizon=1) for row in ranked[:limit]]


def _top_turnover_rows(rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    ranked = sorted(rows, key=lambda row: abs(float(row.get("turnover", {}).get("delta", 0.0) or 0.0)), reverse=True)
    return [_public_row(row, horizon=1) for row in ranked[:limit]]


def _top_forward_delta_rows(rows: List[Dict[str, Any]], horizon: int, limit: int, *, reverse: bool) -> List[Dict[str, Any]]:
    eligible = [
        row for row in rows
        if row.get("forward_returns", {}).get(str(horizon), {}).get("delta") is not None
    ]
    ranked = sorted(
        eligible,
        key=lambda row: float(row["forward_returns"][str(horizon)]["delta"]),
        reverse=reverse,
    )
    return [_public_row(row, horizon=horizon) for row in ranked[:limit]]


def _public_row(row: Dict[str, Any], *, horizon: Optional[int] = None) -> Dict[str, Any]:
    out = {
        "date": row.get("date"),
        "categories": row.get("categories", []),
        "reasons": row.get("gate", {}).get("reasons", []),
        "scenario_gross": row.get("risk", {}).get("scenario_gross"),
        "risk_binding": row.get("risk", {}).get("risk_binding"),
        "max_symbol_delta": row.get("max_symbol_delta"),
        "max_route_leg_delta": row.get("max_route_leg_delta"),
        "turnover_delta": row.get("turnover", {}).get("delta"),
        "top_target_deltas": _top_delta_dict(row.get("target_deltas", {}), 3),
        "top_route_deltas": _top_delta_dict(row.get("route_leg_deltas", {}), 3),
    }
    if horizon is not None:
        out[f"forward_{horizon}d"] = row.get("forward_returns", {}).get(str(horizon), {})
    return out


def _top_delta_dict(deltas: Dict[str, Any], limit: int) -> Dict[str, float]:
    ranked = sorted(deltas.items(), key=lambda item: abs(float(item[1])), reverse=True)
    return {str(key): round(float(value), 6) for key, value in ranked[:limit] if abs(float(value)) > 1e-9}


def _write_report(artifact: Dict[str, Any], path: Path) -> None:
    readiness = artifact.get("readiness", {})
    warn_stats = artifact.get("warn_forward_stats", {})
    pass_stats = artifact.get("pass_forward_stats", {})
    lines = [
        "# Phase III WARN Review",
        "",
        f"Source: `{artifact['source_comparator']}`",
        f"Rows evaluated: {artifact['rows_evaluated']}",
        f"Candidate: `{artifact.get('candidate')}`",
        f"Live effect: `{artifact.get('live_effect')}`",
        "",
        "## Readiness",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Status | `{readiness.get('status')}` |",
        f"| WARN share | {_fmt_pct(readiness.get('warn_share'))} |",
        f"| Live promotion | `{readiness.get('live_promotion')}` |",
        f"| Next step | {readiness.get('next_step')} |",
        f"| Review items | {'; '.join(readiness.get('blockers_or_review_items', []))} |",
        "",
        "## Gate And Reason Counts",
        "",
        "| Field | Counts |",
        "|---|---|",
        f"| Gates | `{artifact.get('gate_counts', {})}` |",
        f"| Reason categories | `{artifact.get('reason_category_counts', {})}` |",
        f"| WARN months | `{artifact.get('warn_month_counts', {})}` |",
        "",
        "## Forward Delta Stats",
        "",
        "Candidate minus old route, using same-day route weights held over the next N trading days.",
        "",
        "| Horizon | WARN avg | WARN median | WARN positive share | PASS avg | PASS median | PASS positive share |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for horizon in artifact.get("lookaheads", []):
        w = warn_stats.get(str(horizon), {})
        p = pass_stats.get(str(horizon), {})
        lines.append(
            f"| {horizon}d | {_fmt_pct(w.get('mean'))} | {_fmt_pct(w.get('median'))} | {_fmt_pct(w.get('positive_share'))} | "
            f"{_fmt_pct(p.get('mean'))} | {_fmt_pct(p.get('median'))} | {_fmt_pct(p.get('positive_share'))} |"
        )

    lines.extend(
        [
            "",
            "## Category Forward Stats",
            "",
            "| Category | Count | Avg Abs Turnover Δ | 1d Avg Δ | 5d Avg Δ | 10d Avg Δ |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for category, stats in artifact.get("category_forward_stats", {}).items():
        fwd = stats.get("forward_delta", {})
        lines.append(
            f"| {category} | {stats.get('count')} | {_fmt(stats.get('avg_abs_turnover_delta'))} | "
            f"{_fmt_pct(fwd.get('1', {}).get('mean'))} | {_fmt_pct(fwd.get('5', {}).get('mean'))} | "
            f"{_fmt_pct(fwd.get('10', {}).get('mean'))} |"
        )

    _append_top_table(lines, "Largest Symbol Delta WARN Rows", artifact.get("top_warn_rows", {}).get("largest_symbol_delta", []), horizon=1)
    _append_top_table(lines, "Largest Abs Turnover Delta WARN Rows", artifact.get("top_warn_rows", {}).get("largest_abs_turnover_delta", []), horizon=1)
    _append_top_table(lines, "Largest 1d Candidate Drag WARN Rows", artifact.get("top_warn_rows", {}).get("largest_candidate_drag_1d", []), horizon=1)
    _append_top_table(lines, "Largest 1d Candidate Benefit WARN Rows", artifact.get("top_warn_rows", {}).get("largest_candidate_benefit_1d", []), horizon=1)

    lines.extend(["", "## Notes", ""])
    for note in artifact.get("notes", []):
        lines.append(f"- {note}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_top_table(lines: List[str], title: str, rows: List[Dict[str, Any]], *, horizon: Optional[int] = None) -> None:
    lines.extend(
        [
            "",
            f"## {title}",
            "",
            "| Date | Categories | Gross | Binding | Max Symbol Δ | Turnover Δ | Forward Δ | Reasons |",
            "|---|---|---:|---|---:|---:|---:|---|",
        ]
    )
    for row in rows[:20]:
        fwd = ""
        if horizon is not None:
            fwd = _fmt_pct(row.get(f"forward_{horizon}d", {}).get("delta"))
        lines.append(
            f"| {row.get('date')} | {','.join(row.get('categories', []))} | {_fmt(row.get('scenario_gross'))} | "
            f"{row.get('risk_binding')} | {_fmt(row.get('max_symbol_delta'))} | {_fmt(row.get('turnover_delta'))} | "
            f"{fwd} | {'; '.join(row.get('reasons', []))} |"
        )


def _series_stats(values: Iterable[Any]) -> Dict[str, Any]:
    nums = [float(value) for value in values if value is not None and pd.notna(value)]
    if not nums:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None, "positive_share": None}
    series = pd.Series(nums, dtype=float)
    return {
        "count": int(len(series)),
        "mean": round(float(series.mean()), 6),
        "median": round(float(series.median()), 6),
        "min": round(float(series.min()), 6),
        "max": round(float(series.max()), 6),
        "positive_share": round(float((series > 0).mean()), 6),
    }


def _month_key(date: Any) -> str:
    return pd.Timestamp(str(date)).strftime("%Y-%m")


def _max_abs(values: Iterable[Any]) -> float:
    return max((abs(float(value)) for value in values), default=0.0)


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _round_optional(value: Optional[float]) -> Optional[float]:
    return None if value is None or pd.isna(value) else round(float(value), 6)


def _parse_int_list(raw: str) -> List[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--comparator", default=None)
    parser.add_argument("--lookaheads", default="1,5,10")
    parser.add_argument("--suffix", default="")
    args = parser.parse_args()
    run_phase3_warn_review(
        comparator_path=Path(args.comparator) if args.comparator else None,
        lookaheads=_parse_int_list(args.lookaheads),
        suffix=args.suffix,
    )
