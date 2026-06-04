from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def write_json_report(payload: Dict[str, Any], output_path: Path) -> Path:
    import json

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n")
    return output_path


def write_full_backtest_markdown(payload: "Dict[str, Any] | Any", output_path: Path, *, label: str = "") -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(payload, "to_dict"):
        payload = payload.to_dict()
    sim = payload.get("simulation", {})
    metrics = sim.get("metrics", {})
    coverage = payload.get("coverage", {})
    title = f"# Hermes Full Backtest Report{' — ' + label if label else ''}"
    lines = [
        title,
        "",
        f"Data manifest: `{payload.get('data_manifest_id')}`",
        f"Requested window: `{payload.get('requested_start')}` to `{payload.get('requested_end')}`",
        f"Effective window: `{payload.get('effective_start')}` to `{payload.get('effective_end')}`",
        f"Trading dates: `{len(payload.get('dates', []))}`",
        "",
        "## Portfolio Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Final value | {_money(metrics.get('final_value'))} |",
        f"| CAGR | {_pct(metrics.get('cagr'))} |",
        f"| Max drawdown | {_pct(metrics.get('max_drawdown'))} |",
        f"| MaxDD start | `{metrics.get('max_drawdown_start')}` |",
        f"| MaxDD end | `{metrics.get('max_drawdown_end')}` |",
        f"| Sharpe | {_num(metrics.get('sharpe'))} |",
        f"| Sortino | {_num(metrics.get('sortino'))} |",
        f"| Turnover | `{sim.get('turnover')}` |",
        "",
        "## Benchmarks",
        "",
        "| Benchmark | Final | CAGR | MaxDD | Sharpe |",
        "|---|---:|---:|---:|---:|",
    ]
    for symbol in ["SPY", "QQQ"]:
        row = payload.get("benchmarks", {}).get(f"{symbol}_metrics", {})
        lines.append(f"| {symbol} | {_money(row.get('final_value'))} | {_pct(row.get('cagr'))} | {_pct(row.get('max_drawdown'))} | {_num(row.get('sharpe'))} |")
    lines.extend(
        [
            "",
            "## Signal Quality",
            "",
            "| Symbol | Signals | Label rows | Hit rate | Avg fwd DD | Avg fwd ret |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for symbol, row in sorted(payload.get("signal_quality", {}).items()):
        lines.append(
            f"| {symbol} | {row.get('signals')} | {row.get('label_rows')} | {_pct(row.get('hit_rate'))} | {_pct(row.get('avg_fwd_dd'))} | {_pct(row.get('avg_fwd_ret'))} |"
        )
    lines.extend(
        [
            "",
            "## Walk Forward",
            "",
            f"Deflated Sharpe: `{payload.get('walk_forward', {}).get('deflated_sharpe')}`",
            "",
            "| Fold | Train | Test | Train N | Test N |",
            "|---:|---|---|---:|---:|",
        ]
    )
    for idx, fold in enumerate(payload.get("walk_forward", {}).get("folds", []), start=1):
        lines.append(
            f"| {idx} | {fold.get('train_start')} to {fold.get('train_end')} | {fold.get('test_start')} to {fold.get('test_end')} | {fold.get('train_n')} | {fold.get('test_n')} |"
        )
    lines.extend(["", "## Coverage", ""])
    for note in coverage.get("notes", []):
        lines.append(f"- {note}")
    lines.extend(["", "| Symbol | Start | End | Rows | Blocks Requested Start |", "|---|---:|---:|---:|---:|"])
    for symbol, row in sorted(coverage.get("required_symbols", {}).items()):
        lines.append(f"| {symbol} | {row.get('start')} | {row.get('end')} | {row.get('rows')} | {row.get('blocks_requested_start')} |")
    lines.extend(["", "## Remaining Risk", ""])
    if label and "proxy" in label.lower():
        lines.append("- **Full-window report**: FNGU/SOXL pre-inception rows are synthetic (is_proxy=True); seam-adjusted P0 gate passed.")
        lines.append("- During proxy period: hard valves triggered on real market signals (2018 Q4/2020/2022 bear markets) → BOXX/DBMF routing.")
        lines.append("- CAGR/MaxDD reflect combined proxy+real behaviour; treat as indicative, not final calibration.")
    else:
        lines.append("- **Real-only report** (high-confidence window): no synthetic data in this range.")
        lines.append("- This is the primary reference for engineering acceptance and calibration discussions.")
    lines.append("- PCR/NAAIM/true BTC funding-basis-DVOL still pending; MSTR D-M3 uses BTC price proxy.")
    lines.append("- Results suitable for engineering verification, not production sizing.")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _money(value: Any) -> str:
    return "NA" if value is None else f"${float(value):,.2f}"


def _pct(value: Any) -> str:
    return "NA" if value is None else f"{float(value):.2%}"


def _num(value: Any) -> str:
    return "NA" if value is None else f"{float(value):.4f}"
