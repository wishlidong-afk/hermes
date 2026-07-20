from __future__ import annotations

import hashlib
import json
from typing import Any

from .registry import FactorDefinition
from .scorer import build_registry


SCORING_SYMBOLS = ("MSTR", "FNGU", "SOXL")
MODULES = ("A", "B", "C", "D")


def factor_capacity_inventory(config: dict[str, Any]) -> dict[str, Any]:
    caps = {str(module): float(value) for module, value in (config.get("module_caps") or {}).items()}
    factor_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for symbol in SCORING_SYMBOLS:
        factors = build_registry(symbol, config).factors
        for factor in factors:
            factor_rows.append(_factor_row(symbol, factor))
        for module in MODULES:
            local = [row for row in factor_rows if row["symbol"] == symbol and row["module"] == module]
            defined_max = round(sum(float(row["max_score"]) for row in local), 4)
            reachable_max = round(
                sum(
                    float(row["max_score"])
                    for row in local
                    if row["capacity_state"] == "ACTIVE_SCORING"
                ),
                4,
            )
            cap = float(caps.get(module, defined_max))
            summaries.append(
                {
                    "symbol": symbol,
                    "module": module,
                    "module_cap": cap,
                    "defined_max": defined_max,
                    "configured_reachable_max": reachable_max,
                    "post_cap_capacity": round(min(cap, reachable_max), 4),
                    "defined_points_clipped_by_cap": round(max(0.0, defined_max - cap), 4),
                    "reachable_points_clipped_by_cap": round(max(0.0, reachable_max - cap), 4),
                    "active_factor_count": sum(
                        1 for row in local if row["capacity_state"] == "ACTIVE_SCORING"
                    ),
                    "placeholder_factor_count": sum(
                        1 for row in local if row["capacity_state"] == "NON_SCORING_PLACEHOLDER"
                    ),
                    "configured_disabled_factor_count": sum(
                        1 for row in local if row["capacity_state"] == "CONFIG_DISABLED"
                    ),
                }
            )
    factor_rows.sort(key=lambda row: (row["symbol"], row["module"], row["factor_id"]))
    return {
        "schema_version": "factor-capacity-inventory-v1",
        "config_sha256": hashlib.sha256(
            json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "symbols": list(SCORING_SYMBOLS),
        "module_caps": {module: caps.get(module) for module in MODULES},
        "module_summaries": summaries,
        "factors": factor_rows,
    }


def _factor_row(symbol: str, factor: FactorDefinition) -> dict[str, Any]:
    if float(factor.max_score) <= 0:
        state = "NON_SCORING_PLACEHOLDER"
    elif factor.missing_name and factor.dependencies == [factor.missing_name]:
        state = "CONFIG_DISABLED"
    else:
        state = "ACTIVE_SCORING"
    return {
        "symbol": symbol,
        "module": factor.module,
        "factor_id": factor.factor_id,
        "max_score": float(factor.max_score),
        "capacity_state": state,
        "dependencies": list(factor.dependencies),
        "missing_name": factor.missing_name,
        "partial_ok": bool(factor.partial_ok),
    }
