#!/usr/bin/env python3
"""Generate the frozen Hermes baseline document from existing report artifacts."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO_ROOT / "docs" / "BASELINE_2026_06_11.md"
DEFAULT_CONTEXT = REPO_ROOT / "context.md"
CURRENT_ROUTING_BENCHMARK = {
    "defcon1": "BOXX50/DBMF30/GLD20",
    "defcon3_mstr": "MSTR->BTC-USD",
}


def _load_json(relpath: str) -> dict[str, Any]:
    return json.loads((REPO_ROOT / relpath).read_text(encoding="utf-8"))


def _pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.{digits}f}%"


def _num(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def _money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.2f}"


def _calmar(metrics: dict[str, Any]) -> float | None:
    cagr = metrics.get("cagr")
    maxdd = metrics.get("max_drawdown")
    if cagr is None or not maxdd:
        return None
    return float(cagr) / abs(float(maxdd))


def _metric_row(label: str, source: str, data: dict[str, Any], note: str = "") -> str:
    m = data["metrics"]
    return (
        f"| {label} | `{source}` | {_pct(m.get('cagr'))} | "
        f"{_pct(m.get('max_drawdown'))} | {_num(m.get('sharpe'))} | "
        f"{_num(m.get('sortino'))} | {_num(_calmar(m))} | {_money(m.get('final_value'))} | {note} |"
    )


def _weight(value: Any) -> str:
    pct = float(value) * 100
    if pct.is_integer():
        return f"{pct:.0f}"
    return f"{pct:.1f}".rstrip("0").rstrip(".")


def _current_routing() -> dict[str, str]:
    cfg = _load_json("src/hermes_escape_top/config/config.json")
    routing = cfg.get("routing", {})
    defcon1 = routing.get("defcon1", {})

    defcon1_parts: list[str] = []
    if "BOXX" in defcon1:
        defcon1_parts.append(f"BOXX{_weight(defcon1['BOXX'])}")
    if "TREND" in defcon1:
        trend_symbol = defcon1.get("trend_symbol", "TREND")
        defcon1_parts.append(f"{trend_symbol}{_weight(defcon1['TREND'])}")
    for symbol, weight in (defcon1.get("extra_legs", {}) or {}).items():
        defcon1_parts.append(f"{symbol}{_weight(weight)}")

    defcon3 = routing.get("defcon3", {})
    preferred_order = ["SOXL", "FNGU", "MSTR"]
    ordered_keys = [k for k in preferred_order if k in defcon3]
    ordered_keys += sorted(k for k in defcon3 if k not in ordered_keys)

    return {
        "defcon1": "/".join(defcon1_parts) or "n/a",
        "defcon3": ", ".join(f"{k}->{defcon3[k]}" for k in ordered_keys) or "n/a",
        "gate_note": routing.get("_defcon3_note", "n/a"),
    }


def _routing_gate_artifact_status() -> str:
    gate_dir = REPO_ROOT / "building" / "reports" / "routing_gate"
    if not gate_dir.exists():
        return "`building/reports/routing_gate/` absent in this worktree"
    required = ["baseline_equity.json", "combo_equity.json"]
    missing = [name for name in required if not (gate_dir / name).exists()]
    if missing:
        return f"`building/reports/routing_gate/` present, missing {', '.join(missing)}"
    return "`building/reports/routing_gate/` baseline + combo equity artifacts present"


def _routing_freshness(routing: dict[str, str]) -> str:
    expected_defcon1 = CURRENT_ROUTING_BENCHMARK["defcon1"]
    expected_mstr = CURRENT_ROUTING_BENCHMARK["defcon3_mstr"]
    note = routing.get("gate_note", "")
    note_mstr_ok = "MSTR→BTC-USD" in note or expected_mstr in note
    note_defcon1_ok = expected_defcon1 in note
    config_defcon1_ok = routing.get("defcon1") == expected_defcon1
    config_mstr_ok = expected_mstr in routing.get("defcon3", "")
    if config_defcon1_ok and config_mstr_ok and note_defcon1_ok and note_mstr_ok:
        return f"FRESH: config routing block matches `{expected_defcon1}` and `{expected_mstr}`"
    return (
        "STALE: headline source expects "
        f"`{expected_defcon1}` + `{expected_mstr}`, but current config/note reports "
        f"DEFCON1 `{routing.get('defcon1', 'n/a')}`; DEFCON3 `{routing.get('defcon3', 'n/a')}`"
    )


def _read_gate_rows(relpath: str) -> list[dict[str, str]]:
    text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("| ") or "---" in line or "variant" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 8:
            continue
        headers = ["variant", "full_cagr", "full_maxdd"]
        if len(cells) == 8:
            headers += ["median_oos_obj", "delta_vs_base", "pbo_oos", "dsr", "gate"]
        else:
            headers += ["sharpe", "calmar", "median_oos_obj", "delta_vs_base", "pbo_oos", "dsr", "gate"]
        rows.append(dict(zip(headers, cells)))
    return rows


def _gate_row(rows: list[dict[str, str]], variant: str) -> dict[str, str]:
    for row in rows:
        if row.get("variant") == variant:
            return row
    raise RuntimeError(f"Could not find gate row for variant {variant!r}")


def _git_branch() -> str:
    try:
        return subprocess.check_output(
            ["git", "branch", "--show-current"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _test_count() -> int:
    tests_dir = REPO_ROOT / "src" / "hermes_escape_top" / "tests"
    count = 0
    for path in tests_dir.glob("test_*.py"):
        text = path.read_text(encoding="utf-8")
        count += len(re.findall(r"^\s*def test_", text, flags=re.M))
    return count


def build_doc() -> str:
    deployed = _load_json("building/reports/capeff/baseline_deployed.json")
    pre_deploy = _load_json("building/reports/capeff/baseline.json")
    mstr_btc = _load_json("building/reports/capeff/mstr_btc.json")
    full_proxy = _load_json("building/reports/Backtest_FULL_2018_2026.json")
    calibration = _load_json("building/reports/Calibration_RiskFactors_2026_06_08.json")
    flag_base = _load_json("building/reports/flag_sweep/baseline.json")

    full_proxy_metrics = {
        "metrics": full_proxy["simulation"]["metrics"],
        "effective_start": full_proxy["effective_start"],
        "effective_end": full_proxy["effective_end"],
        "n_days": len(full_proxy.get("dates", [])),
    }
    chosen = calibration["chosen"]["selection"]
    thresholds = calibration["chosen"]["status_thresholds"]
    deployment_pbo = calibration.get("deployment_fixed_pbo")
    gate_rows = _read_gate_rows("building/reports/flag_sweep/GATE_REPORT.md")
    continuous_rows = _read_gate_rows("building/reports/flag_sweep/GATE_REPORT_continuous_sell_fraction.md")
    cot_rows = _read_gate_rows("building/reports/flag_sweep/GATE_REPORT_cot_nq.md")

    deployed_metrics = deployed["metrics"]
    routing = _current_routing()
    routing_artifacts = _routing_gate_artifact_status()
    routing_freshness = _routing_freshness(routing)
    cot_baseline = _gate_row(cot_rows, "baseline")
    lines = [
        "# Hermes Baseline 2026-06-11",
        "",
        "> Generated by `python3 -m hermes_escape_top.scripts.generate_baseline_doc --write`.",
        f"> Generated on: {date.today().isoformat()}",
        "",
        "## Scope",
        "",
        "This file freezes the performance and validation baseline used by `docs/OPTIMIZATION_ROADMAP.md` T4. "
        "The current deployed routing overlay is DEFCON1 BOXX/DBMF/GLD plus DEFCON3 MSTR routed to BTC-USD, "
        "with F3/F4/F5/F6 live, and H-M2 buffer still OFF. The forward optimization benchmark is the "
        "`cot_nq` gate baseline row because it reflects the current combo routing baseline; "
        "`baseline_deployed.json` is retained as a historical capeff reference.",
        "",
        "## Headline Deployment Baseline (current routing overlay)",
        "",
        "| Metric | Value | Source |",
        "|---|---|---|",
        f"| Current routing overlay | DEFCON1 `{routing['defcon1']}`; DEFCON3 `{routing['defcon3']}` | `src/hermes_escape_top/config/config.json` |",
        f"| Routing freshness | {routing_freshness} | config routing block + `_defcon3_note` consistency check |",
        f"| Routing-gate note | {routing['gate_note']} | config `_defcon3_note`; mirrored in `context.md` routing section |",
        f"| Routing-gate artifacts | {routing_artifacts} | local worktree check |",
        f"| Forward optimization benchmark | {cot_baseline['full_cagr']} CAGR / {cot_baseline['full_maxdd']} MaxDD / {cot_baseline.get('sharpe', 'n/a')} Sharpe / {cot_baseline.get('calmar', 'n/a')} Calmar | `building/reports/flag_sweep/GATE_REPORT_cot_nq.md` baseline row |",
        f"| Benchmark PBO / DSR | {cot_baseline.get('pbo_oos', 'n/a')} / {cot_baseline.get('dsr', 'n/a')} | same |",
        f"| Historical capeff reference | {_pct(deployed_metrics.get('cagr'))} CAGR / {_pct(deployed_metrics.get('max_drawdown'))} MaxDD / {_num(deployed_metrics.get('sharpe'))} Sharpe | `building/reports/capeff/baseline_deployed.json`; pre-GLD-combo comparison reference |",
        f"| Historical capeff window | `{deployed['effective_start']}` to `{deployed['effective_end']}` ({deployed['n_days']} trading days) | `building/reports/capeff/baseline_deployed.json` |",
        f"| Historical capeff final value | {_money(deployed_metrics.get('final_value'))} | same |",
        f"| Deployment fixed PBO | {_num(deployment_pbo, 6)} | `building/reports/Calibration_RiskFactors_2026_06_08.json` |",
        f"| Test inventory | {_test_count()} `def test_*` functions | static count under `src/hermes_escape_top/tests` |",
        f"| Branch | `{_git_branch()}` | git |",
        "",
        "## Source Matrix",
        "",
        "| Variant / report | Source | CAGR | MaxDD | Sharpe | Sortino | Calmar | Final value | Note |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
        _metric_row("Pre-deployment capital-efficiency baseline", "building/reports/capeff/baseline.json", pre_deploy, "Before MSTR→BTC and later live robustness bundle."),
        _metric_row("MSTR DEFCON3 BTC route", "building/reports/capeff/mstr_btc.json", mstr_btc, "Isolated MSTR route improvement."),
        _metric_row("Historical capeff reference", "building/reports/capeff/baseline_deployed.json", deployed, "Historical reference; superseded as future benchmark by COT NQ gate baseline with combo routing."),
        _metric_row("Full-proxy engineering backtest", "building/reports/Backtest_FULL_2018_2026.json", full_proxy_metrics, "Engineering reference; not the deployment gate baseline."),
        "",
        "## Validation Snapshot",
        "",
        "| Item | Value | Source |",
        "|---|---:|---|",
        f"| Chosen threshold combo | `{chosen['combo']}` | calibration JSON |",
        f"| Status thresholds | EXIT={thresholds['EXIT']}, DEFENSIVE_EXIT={thresholds['DEFENSIVE_EXIT']}, REDUCE={thresholds['REDUCE']}, TRIM={thresholds['TRIM']}, WATCH={thresholds['WATCH']} | calibration JSON |",
        f"| Deployment fixed PBO | {_num(calibration.get('deployment_fixed_pbo'), 6)} | calibration JSON |",
        f"| Train-greedy PBO diagnostic | {_num(calibration.get('train_greedy_pbo'), 6)} | calibration JSON |",
        f"| Calibration gates | `{json.dumps(calibration.get('gates', {}), sort_keys=True)}` | calibration JSON |",
        f"| Backtest data manifest | `{full_proxy.get('data_manifest_id')}` | full-proxy report |",
        f"| Flag-sweep baseline manifest | `{flag_base.get('manifest_id')}` | flag-sweep baseline |",
        "",
        "## Gate Evidence",
        "",
        "### Flag gate",
        "",
        "| Variant | Full CAGR | Full MaxDD | Median OOS obj | Δ vs base | PBO | DSR | Gate |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in gate_rows:
        lines.append(
            f"| {row['variant']} | {row['full_cagr']} | {row['full_maxdd']} | "
            f"{row.get('median_oos_obj', '')} | {row.get('delta_vs_base', '')} | "
            f"{row.get('pbo_oos', '')} | {row.get('dsr', '')} | {row.get('gate', '')} |"
        )

    lines += [
        "",
        "### Continuous sell fraction gate",
        "",
        "| Variant | Full CAGR | Full MaxDD | Median OOS obj | Δ vs base | PBO | DSR | Gate |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in continuous_rows:
        lines.append(
            f"| {row['variant']} | {row['full_cagr']} | {row['full_maxdd']} | "
            f"{row.get('median_oos_obj', '')} | {row.get('delta_vs_base', '')} | "
            f"{row.get('pbo_oos', '')} | {row.get('dsr', '')} | {row.get('gate', '')} |"
        )

    lines += [
        "",
        "### COT NQ gate",
        "",
        "| Variant | Full CAGR | Full MaxDD | Sharpe | Calmar | Median OOS obj | Δ vs base | PBO | DSR | Gate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in cot_rows:
        lines.append(
            f"| {row['variant']} | {row['full_cagr']} | {row['full_maxdd']} | "
            f"{row.get('sharpe', '')} | {row.get('calmar', '')} | {row.get('median_oos_obj', '')} | "
            f"{row.get('delta_vs_base', '')} | {row.get('pbo_oos', '')} | {row.get('dsr', '')} | {row.get('gate', '')} |"
        )

    lines += [
        "",
        "## Interpretation",
        "",
        f"- The current deployed routing state is **DEFCON1 {routing['defcon1']} plus DEFCON3 {routing['defcon3']}**.",
        f"- The forward optimization benchmark is **{cot_baseline['full_cagr']} CAGR / {cot_baseline['full_maxdd']} MaxDD / {cot_baseline.get('sharpe', 'n/a')} Sharpe / {cot_baseline.get('calmar', 'n/a')} Calmar** from the `cot_nq` gate baseline row.",
        "- The older **15.84% CAGR / -14.04% MaxDD / 1.140 Sharpe / 1.128 Calmar** `baseline_deployed.json` number is now only a historical capeff reference.",
        f"- Routing freshness check: **{routing_freshness}**.",
        f"- Routing-gate combo equity artifacts were not available for this run ({routing_artifacts}), so GLD combo evidence is referenced from the deployed config note rather than re-computed here.",
        "- The full-proxy engineering report remains useful for system verification, but its **18.13% CAGR / -27.60% MaxDD** is not the live deployment baseline.",
        "- `baseline_deployed.json` does not carry a DSR or manifest id; use the gate reports and calibration JSON above for validation provenance.",
        "- Failed variants remain valuable evidence. They should be archived in `docs/FLAG_REGISTRY.md` rather than re-tested casually.",
        "",
    ]
    return "\n".join(lines)


def update_context(context_path: Path, doc: str) -> None:
    deployed = _load_json("building/reports/capeff/baseline_deployed.json")
    calibration = _load_json("building/reports/Calibration_RiskFactors_2026_06_08.json")
    metrics = deployed["metrics"]
    routing = _current_routing()
    routing_artifacts = _routing_gate_artifact_status()
    routing_freshness = _routing_freshness(routing)
    cot_baseline = _gate_row(_read_gate_rows("building/reports/flag_sweep/GATE_REPORT_cot_nq.md"), "baseline")
    replacement = "\n".join([
        "## 13. 当前性能基线与路由部署态（2026-06-11）",
        "",
        "| 指标 | 值 | 来源 |",
        "|------|------|------|",
        f"| 当前路由部署态 | DEFCON1 `{routing['defcon1']}`；DEFCON3 `{routing['defcon3']}` | `src/hermes_escape_top/config/config.json` |",
        f"| 路由 freshness | {routing_freshness} | config routing block + `_defcon3_note` 校验 |",
        f"| 路由门控依据 | {routing['gate_note']} | config `_defcon3_note` |",
        f"| routing-gate 本地产物 | {routing_artifacts} | 本地文件检查 |",
        f"| 当前含 combo 对照基线 CAGR | {cot_baseline['full_cagr']} | `building/reports/flag_sweep/GATE_REPORT_cot_nq.md` baseline row |",
        f"| 当前含 combo 对照基线 Max Drawdown | {cot_baseline['full_maxdd']} | `building/reports/flag_sweep/GATE_REPORT_cot_nq.md` baseline row |",
        f"| 当前含 combo 对照基线 Sharpe | {cot_baseline.get('sharpe', 'n/a')} | `building/reports/flag_sweep/GATE_REPORT_cot_nq.md` baseline row |",
        f"| 当前含 combo 对照基线 Calmar | {cot_baseline.get('calmar', 'n/a')} | `building/reports/flag_sweep/GATE_REPORT_cot_nq.md` baseline row |",
        f"| 历史 capeff 参照 CAGR | {_pct(metrics.get('cagr'))} | `building/reports/capeff/baseline_deployed.json` |",
        f"| 部署 PBO | {_num(calibration.get('deployment_fixed_pbo'), 6)} | `building/reports/Calibration_RiskFactors_2026_06_08.json` |",
        f"| 测试数量 | {_test_count()} `def test_*` | 静态统计 |",
        f"| 分支 | `{_git_branch()}` | git |",
    ])
    text = context_path.read_text(encoding="utf-8")
    pattern = re.compile(r"## 13\. 当前性能基线(?:与路由部署态)?（2026-06-11）\n.*?\n---", re.S)
    new_text, count = pattern.subn(replacement + "\n\n---", text, count=1)
    if count != 1:
        raise RuntimeError("Could not locate context.md section 13")
    context_path.write_text(new_text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write docs/BASELINE_2026_06_11.md")
    parser.add_argument("--update-context", action="store_true", help="also update context.md section 13")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--context", type=Path, default=DEFAULT_CONTEXT)
    args = parser.parse_args()

    doc = build_doc()
    if args.write:
        args.out.write_text(doc + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
        if args.update_context:
            update_context(args.context, doc)
            print(f"updated {args.context}")
    else:
        print(doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
