#!/usr/bin/env python3
"""Generate factor max-score and module-cap inventory from scoring code."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from hermes_escape_top.config import CONFIG_PATH, load_config
from hermes_escape_top.core.scoring.capacity import factor_capacity_inventory


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "building/reports/factor_capacity"


def run(config_path: Path = CONFIG_PATH, output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    inventory = factor_capacity_inventory(load_config(config_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "FACTOR_CAPACITY_INVENTORY.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "FACTOR_CAPACITY_INVENTORY.md").write_text(
        render_inventory(inventory),
        encoding="utf-8",
    )
    return inventory


def render_inventory(inventory: Mapping[str, Any]) -> str:
    lines = [
        "# Factor Capacity Inventory",
        "",
        "Generated directly from `build_registry(symbol, config)`.",
        f"Config SHA-256: `{inventory.get('config_sha256')}`",
        "",
        "`defined_max` includes configured-off scoring definitions; `configured_reachable_max` excludes",
        "non-scoring placeholders and deliberate missing-only gates. The scorer applies `module_cap` last.",
        "",
        "## Module Summary",
        "",
        "| Symbol | Module | Defined max | Reachable max | Cap | Post-cap | Clipped reachable |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in inventory.get("module_summaries", []):
        lines.append(
            f"| {row.get('symbol')} | {row.get('module')} | {_num(row.get('defined_max'))} | "
            f"{_num(row.get('configured_reachable_max'))} | {_num(row.get('module_cap'))} | "
            f"{_num(row.get('post_cap_capacity'))} | {_num(row.get('reachable_points_clipped_by_cap'))} |"
        )
    lines.extend(
        [
            "",
            "## Factor Definitions",
            "",
            "| Symbol | Module | Factor | Max | Capacity state | Dependencies |",
            "|---|---|---|---:|---|---|",
        ]
    )
    for row in inventory.get("factors", []):
        dependencies = ", ".join(str(value) for value in row.get("dependencies", []))
        lines.append(
            f"| {row.get('symbol')} | {row.get('module')} | `{row.get('factor_id')}` | "
            f"{_num(row.get('max_score'))} | {row.get('capacity_state')} | `{dependencies}` |"
        )
    return "\n".join(lines) + "\n"


def _num(value: Any) -> str:
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "n/a"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    run(args.config, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
