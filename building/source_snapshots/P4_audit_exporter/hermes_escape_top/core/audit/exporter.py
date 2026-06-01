"""Audit Exporter -- structured export of PipelineResult for WebUI and observability.

Converts audit dicts to:
  - JSON (machine-readable, for API/WebUI)
  - Markdown summary (human-readable, for daily review)
  - Signal journal entry (for post-hoc P&L tracking)

Connects Pipeline (Phase 15) to WebUI (Phase 14).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional


def export_json(audit: Dict[str, Any], path: Optional[str] = None) -> str:
    """Export audit dict to formatted JSON string. Optionally write to file."""
    output = json.dumps(audit, indent=2, default=str, ensure_ascii=False)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(output)
    return output


def export_markdown(audit: Dict[str, Any]) -> str:
    """Export audit dict to human-readable Markdown summary."""
    lines = []
    as_of = audit.get("as_of", "unknown")
    lines.append(f"# Hermes Daily Audit — {as_of}")
    lines.append("")
    lines.append(f"Generated: {audit.get('timestamp', datetime.utcnow().isoformat())}")
    lines.append("")

    # Scores
    lines.append("## Scores")
    lines.append("")
    lines.append("| Symbol | Total |")
    lines.append("|---|---|")
    for sym, score in audit.get("scores_summary", {}).items():
        lines.append(f"| {sym} | {score} |")
    lines.append("")

    # Verdicts
    lines.append("## Verdicts")
    lines.append("")
    lines.append("| Symbol | Status | Rule Weight |")
    lines.append("|---|---|---|")
    for sym, v in audit.get("verdicts_summary", {}).items():
        lines.append(f"| {sym} | {v.get('status', '?')} | {v.get('rule_weight', '?'):.2%} |")
    lines.append("")

    # Risk
    risk = audit.get("risk_summary", {})
    lines.append("## Risk")
    lines.append("")
    lines.append(f"- Portfolio Vol: {risk.get('portfolio_vol', '?')}")
    lines.append(f"- Gross Scaler: {risk.get('gross_scaler', '?')}")
    lines.append(f"- Corr Regime: {risk.get('corr_regime', '?')}")
    lines.append(f"- Binding: {risk.get('binding', '?')}")
    lines.append("")

    # Confidence
    conf = audit.get("confidence", {})
    lines.append("## Confidence")
    lines.append("")
    mode = conf.get("mode", "?")
    dc = conf.get("decision_confidence", "?")
    wl = conf.get("weakest_link", "?")
    lines.append(f"- Mode: **{mode}** (confidence: {dc})")
    lines.append(f"- Weakest Link: {wl}")
    lines.append("")

    # Sizing
    sizing = audit.get("sizing_summary", {})
    lines.append("## Target Weights")
    lines.append("")
    lines.append("| Symbol | Weight | Binding |")
    lines.append("|---|---|---|")
    tw = sizing.get("target_weights", {})
    bc = sizing.get("binding_constraint", {})
    for sym in tw:
        lines.append(f"| {sym} | {tw[sym]:.2%} | {bc.get(sym, '-')} |")
    lines.append("")

    # Regime
    lines.append("## Regime")
    lines.append("")
    for sym, reg in audit.get("regime", {}).items():
        lines.append(f"- {sym}: {reg}")
    lines.append("")

    # Drift
    drift = audit.get("drift", {})
    psi = drift.get("psi", 0)
    alert = drift.get("alert", False)
    lines.append("## Drift")
    lines.append("")
    lines.append(f"- PSI: {psi}" + (" **ALERT**" if alert else ""))
    lines.append("")

    return "\n".join(lines)


def build_signal_entry(
    as_of: str,
    symbol: str,
    status: str,
    score: float,
    sell_fraction: float,
    hard_valve_hits: List[str],
    target_weight: float,
    confidence_mode: str,
) -> Dict[str, Any]:
    """Build a signal journal entry for post-hoc P&L tracking.

    Written to signal_journal.jsonl (one entry per line).
    """
    return {
        "as_of": as_of,
        "symbol": symbol,
        "status": status,
        "score": score,
        "sell_fraction": sell_fraction,
        "hard_valve_hits": hard_valve_hits,
        "target_weight": round(target_weight, 6),
        "confidence_mode": confidence_mode,
        "timestamp": datetime.utcnow().isoformat(),
    }


def export_signal_journal(entries: List[Dict[str, Any]], path: Optional[str] = None) -> str:
    """Export signal entries as JSONL (one JSON object per line)."""
    lines = [json.dumps(e, default=str, ensure_ascii=False) for e in entries]
    output = "\n".join(lines)
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(output + "\n")
    return output
