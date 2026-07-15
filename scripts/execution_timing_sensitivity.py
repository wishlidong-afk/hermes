#!/usr/bin/env python3
"""Compare legacy-close, next-open, delayed-close, and stress execution.

This is a research-only repricing tool. It consumes a full-backtest artifact's
already-computed daily route weights and never calls the scoring pipeline.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

from hermes_escape_top.config import load_config
from hermes_escape_top.core.backtest.execution import execution_timing_sensitivity
from hermes_escape_top.core.backtest.run_full import _load_histories
from hermes_escape_top.core.backtest.simulator import DayDecision
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.core.routing.leg_proxy import leg_price_frame


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKTEST = REPO_ROOT / "building" / "reports" / "Backtest_FULL_2018_2026.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "building" / "reports" / "execution_timing"
PROVENANCE_FIELDS = (
    "git_commit",
    "code_sha256",
    "config_sha256",
    "manifest_id",
    "soft_history_sha256",
    "start",
    "end",
    "worktree_clean",
    "equity_timing",
)
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from backtest_flag_sweep import build_config, cache_evidence  # noqa: E402


def build_execution_config(config_path: Path | None = None) -> dict[str, Any]:
    cfg = load_config(config_path) if config_path is not None else build_config("baseline")
    cfg.setdefault("features", {})["use_indicator_cache"] = True
    return cfg


def headline_open_quality_ok(quality: Mapping[str, Any]) -> bool:
    missing = quality.get("required_missing_rows")
    if missing is None:
        missing = quality.get("missing_rows", 0)
    return int(missing or 0) == 0


def classify_source_provenance(source: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, object]:
    provenance = source.get("provenance")
    if not isinstance(provenance, Mapping):
        return {"status": "UNVERIFIED_LEGACY_SOURCE", "mismatches": list(PROVENANCE_FIELDS), "headline_eligible": False}
    missing = [field for field in PROVENANCE_FIELDS if field not in provenance]
    mismatches = missing + [
        field
        for field in PROVENANCE_FIELDS
        if field in provenance and provenance.get(field) != current.get(field)
    ]
    if provenance.get("worktree_clean") is not True or current.get("worktree_clean") is not True:
        mismatches.append("worktree_clean")
    mismatches = list(dict.fromkeys(mismatches))
    return {
        "status": "CURRENT_SOURCE" if not mismatches else "STALE_SOURCE",
        "mismatches": mismatches,
        "headline_eligible": not mismatches,
    }


def extract_decisions(source: Mapping[str, Any]) -> list[DayDecision]:
    rows = source.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("backtest artifact has no rows")
    decisions: list[DayDecision] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping) or not row.get("date"):
            raise ValueError("each backtest row must have a date")
        day = str(row["date"])
        weights = row.get("route_leg_weights")
        if not isinstance(weights, Mapping):
            raise ValueError(f"backtest row {day} has no route_leg_weights")
        if day in seen:
            raise ValueError(f"duplicate backtest row date: {day}")
        seen.add(day)
        decisions.append(DayDecision(day, {str(leg): float(weight) for leg, weight in weights.items()}))
    return sorted(decisions, key=lambda item: item.date)


def source_window(source: Mapping[str, Any]) -> tuple[str, str]:
    provenance = source.get("provenance")
    if isinstance(provenance, Mapping) and provenance.get("start") and provenance.get("end"):
        return str(provenance["start"]), str(provenance["end"])
    start = source.get("requested_start")
    end = source.get("requested_end")
    if not start or not end:
        raise ValueError("backtest source has no requested/provenance window")
    return str(start), str(end)


def compare_legacy_source(source: Mapping[str, Any], artifact: Mapping[str, Any]) -> dict[str, object]:
    source_simulation = source.get("simulation")
    legacy = next((row for row in artifact.get("scenarios", []) if row.get("scenario_id") == "legacy_close"), None)
    if not isinstance(source_simulation, Mapping) or not isinstance(legacy, Mapping):
        return {"status": "UNAVAILABLE", "mismatches": []}
    source_metrics = source_simulation.get("metrics", {})
    legacy_metrics = legacy.get("metrics", {})
    fields = ["final_value", "cagr", "max_drawdown", "sharpe", "sortino"]
    mismatches = [field for field in fields if not _same_number(source_metrics.get(field), legacy_metrics.get(field))]
    if not _same_number(source_simulation.get("turnover"), legacy.get("turnover")):
        mismatches.append("turnover")
    return {"status": "MATCH" if not mismatches else "MISMATCH", "mismatches": mismatches}


def build_gate_baseline_artifacts(
    source: Mapping[str, Any],
    artifact: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, float], dict[str, float]]:
    if artifact.get("evidence_status") != "CURRENT_EXECUTION_EVIDENCE":
        raise ValueError("only CURRENT_EXECUTION_EVIDENCE may be exported as a gate baseline")
    provenance = source.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError("current baseline source has no provenance")
    scenarios = {
        str(row.get("scenario_id")): row
        for row in artifact.get("scenarios", [])
        if isinstance(row, Mapping)
    }
    next_open = scenarios.get("next_open")
    legacy = scenarios.get("legacy_close")
    if not next_open or not legacy:
        raise ValueError("execution timing artifact is missing next_open or legacy_close")
    next_equity = {str(day): float(value) for day, value in next_open.get("equity_curve", {}).items()}
    legacy_equity = {str(day): float(value) for day, value in legacy.get("equity_curve", {}).items()}
    if not next_equity or not legacy_equity:
        raise ValueError("execution timing artifact has an empty gate equity curve")
    metrics = {
        **dict(provenance),
        "variant": "baseline",
        "equity_timing": "next_open",
        "effective_start": source.get("effective_start"),
        "effective_end": source.get("effective_end"),
        "n_days": len(source.get("dates", [])),
        "metrics": dict(next_open.get("metrics", {})),
        "turnover": next_open.get("turnover"),
        "legacy_close_metrics": dict(legacy.get("metrics", {})),
        "execution_open_quality": dict(artifact.get("open_quality", {})),
    }
    return metrics, next_equity, legacy_equity


def render_report(artifact: Mapping[str, Any]) -> str:
    provenance = artifact.get("source_provenance", {})
    quality = artifact.get("open_quality", {})
    lines = [
        "# Execution Timing Sensitivity",
        "",
        f"Evidence status: **{artifact.get('evidence_status', 'UNKNOWN')}**",
        f"Source provenance: `{provenance.get('status', 'UNKNOWN')}`",
        f"Headline scenario: `{artifact.get('headline_scenario', 'next_open')}`",
        f"Legacy parity: `{artifact.get('legacy_source_parity', {}).get('status', 'UNKNOWN')}`",
        "Live effect: `none`",
        "",
    ]
    if artifact.get("evidence_status") != "CURRENT_EXECUTION_EVIDENCE":
        lines.extend(
            [
                "> **METHODOLOGY_ONLY**：源产物没有通过当前 commit/code/config/data provenance 校验，",
                "> 本报告只验证成交时点方法，不得作为当前基线头条，也不授权任何配置翻闸。",
                "",
            ]
        )
    lines.extend(
        [
            "## Open-Price Coverage",
            "",
            f"- Total rows: `{quality.get('total_rows', 0)}`",
            f"- Observed: `{quality.get('observed_rows', 0)}` ({_pct(quality.get('observed_share'))})",
            f"- Modeled synthetic/proxy: `{quality.get('modeled_rows', 0)}`",
            f"- Missing: `{quality.get('missing_rows', 0)}`",
            f"- Execution-required rows: `{quality.get('required_total_rows', 'n/a')}`",
            f"- Execution-required missing: `{quality.get('required_missing_rows', 'n/a')}`",
            "",
            "| Leg | Observed | Modeled | Missing |",
            "|---|---:|---:|---:|",
        ]
    )
    for leg, counts in quality.get("by_leg", {}).items():
        observed = int(counts.get("OBSERVED", 0))
        modeled = sum(int(count) for label, count in counts.items() if str(label).startswith("MODELED_"))
        missing = int(counts.get("MISSING", 0))
        lines.append(f"| {leg} | {observed} | {modeled} | {missing} |")
    lines.extend(
        [
            "",
            "## Scenarios",
            "",
            "| Scenario | Role | Timing | Extra slip | Final | CAGR | MaxDD | Sharpe | Turnover | Base cost | Extra slip cost |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in artifact.get("scenarios", []):
        metrics = row.get("metrics", {})
        lines.append(
            f"| {row.get('scenario_id')} | {row.get('role')} | {row.get('timing')} | "
            f"{_num(row.get('extra_slippage_bps'))} bps | {_money(metrics.get('final_value'))} | "
            f"{_pct(metrics.get('cagr'))} | {_pct(metrics.get('max_drawdown'))} | "
            f"{_num(metrics.get('sharpe'))} | {_num(row.get('turnover'))} | "
            f"{_money(row.get('base_cost'))} | {_money(row.get('extra_slippage_cost'))} |"
        )
    lines.extend(["", "## Provenance", ""])
    mismatches = provenance.get("mismatches", [])
    lines.append(f"- Mismatches: `{', '.join(mismatches) if mismatches else 'none'}`")
    source = artifact.get("source", {})
    lines.append(f"- Source artifact: `{source.get('path', 'unknown')}`")
    lines.append(f"- Source SHA256: `{source.get('sha256', 'unknown')}`")
    lines.extend(["", "## Notes", ""])
    for note in artifact.get("notes", []):
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def research_worktree_clean(repo_root: Path = REPO_ROOT) -> bool:
    paths = [
        ":(glob)src/hermes_escape_top/**/*.py",
        "src/hermes_escape_top/config/config.json",
        "src/pyproject.toml",
        "scripts/backtest_flag_sweep.py",
        "scripts/execution_timing_sensitivity.py",
    ]
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", *paths],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0 and not result.stdout.strip()


def run(
    backtest_path: Path = DEFAULT_BACKTEST,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    stress_slippage_bps: float = 25.0,
    gate_artifacts_dir: Path | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    source_path = backtest_path.resolve()
    source = json.loads(source_path.read_text(encoding="utf-8"))
    decisions = extract_decisions(source)
    dates = [item.date for item in decisions]
    legs = sorted({leg for item in decisions for leg in item.target_weights})

    cfg = build_execution_config(config_path)
    store = LocalStore(cfg)
    histories = _load_histories(store, cfg)
    for leg in legs:
        if leg not in histories:
            histories[leg] = store.load_history(leg)
    frames = {leg: leg_price_frame(leg, dates, histories) for leg in legs}

    source_start, source_end = source_window(source)
    current = cache_evidence("baseline", cfg, start=source_start, end=source_end, enable=["costs"])
    current["worktree_clean"] = research_worktree_clean()
    source_status = classify_source_provenance(source, current)
    artifact = execution_timing_sensitivity(
        decisions,
        frames,
        cfg,
        stress_slippage_bps=stress_slippage_bps,
    )
    legacy_parity = compare_legacy_source(source, artifact)
    open_quality = artifact.get("open_quality", {})
    headline_eligible = bool(
        source_status["headline_eligible"]
        and headline_open_quality_ok(open_quality)
        and legacy_parity["status"] == "MATCH"
    )
    artifact.update(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "evidence_status": "CURRENT_EXECUTION_EVIDENCE" if headline_eligible else "METHODOLOGY_ONLY",
            "headline_eligible": headline_eligible,
            "authorization": "NO_CONFIG_FLIP",
            "legacy_source_parity": legacy_parity,
            "source_provenance": source_status,
            "current_provenance": {field: current.get(field) for field in PROVENANCE_FIELDS},
            "source": {
                "path": str(source_path),
                "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                "schema_version": source.get("schema_version"),
                "data_manifest_id": source.get("data_manifest_id"),
                "rows": len(decisions),
                "start": dates[0],
                "end": dates[-1],
            },
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "EXECUTION_TIMING_SENSITIVITY.json"
    md_path = output_dir / "EXECUTION_TIMING_SENSITIVITY.md"
    json_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_report(artifact), encoding="utf-8")
    if gate_artifacts_dir is not None:
        metrics, next_equity, legacy_equity = build_gate_baseline_artifacts(source, artifact)
        gate_artifacts_dir.mkdir(parents=True, exist_ok=True)
        (gate_artifacts_dir / "baseline.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (gate_artifacts_dir / "baseline_equity.json").write_text(
            json.dumps(next_equity, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (gate_artifacts_dir / "baseline_legacy_close_equity.json").write_text(
            json.dumps(legacy_equity, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(f"Execution timing artifact: {json_path}")
    print(f"Execution timing report: {md_path}")
    print(f"Evidence status: {artifact['evidence_status']}")
    return artifact


def _num(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "n/a"


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "n/a"


def _money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _same_number(left: Any, right: Any, tolerance: float = 1e-9) -> bool:
    if left is None or right is None:
        return left is right
    try:
        return abs(float(left) - float(right)) <= tolerance
    except (TypeError, ValueError):
        return left == right


def main() -> int:
    parser = argparse.ArgumentParser(description="Reprice a full-backtest artifact under executable timing assumptions")
    parser.add_argument("--backtest", type=Path, default=DEFAULT_BACKTEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--stress-slippage-bps", type=float, default=25.0)
    parser.add_argument("--gate-artifacts-dir", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()
    run(
        args.backtest,
        args.output_dir,
        stress_slippage_bps=args.stress_slippage_bps,
        gate_artifacts_dir=args.gate_artifacts_dir,
        config_path=args.config,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
