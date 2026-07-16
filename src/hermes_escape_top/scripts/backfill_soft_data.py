#!/usr/bin/env python3
"""Compatibility router for the retired pre-ledger soft-data refresher.

Canonical external CSVs have one writer: ExternalSourceRunner.  This module
keeps the old command names available for runbook archaeology and local tools,
but it delegates every refresh to ``scripts.refresh_external``.
"""
from __future__ import annotations

import argparse
import json
from typing import Any, Dict, Optional

from hermes_escape_top.config import load_config
from hermes_escape_top.scripts import refresh_external


_VALID_ONLY = {"fred", "fred_risk", "naaim", "aaii", "cot"}


def _selected_source_ids(config: dict[str, Any], only: str) -> tuple[str, ...]:
    exact = bool((config.get("features") or {}).get("use_fred_vintage_pit", False))
    if only == "fred":
        return (
            ("fred_vintages", "fred_net_liquidity_vintage")
            if exact
            else ("fred_net_liquidity",)
        )
    if only == "fred_risk":
        return (
            ("fred_vintages", "dollar_vintage", "real_rate_vintage")
            if exact
            else ("dollar", "real_rate")
        )
    return {
        "naaim": ("naaim_exposure",),
        "aaii": ("aaii_sentiment",),
        "cot": ("cot_nq",),
    }[only]


def refresh_all(
    config: Optional[Dict[str, Any]] = None,
    only: Optional[str] = None,
) -> Dict[str, Any]:
    cfg = config or load_config()
    if only is not None and only not in _VALID_ONLY:
        raise ValueError(f"--only must be one of {sorted(_VALID_ONLY)}")
    if only is None:
        result = refresh_external.refresh_all_sources(cfg, auto_import=True)
    else:
        runs = refresh_external._refresh_sources_with_dependencies(
            list(_selected_source_ids(cfg, only)),
            cfg,
            auto_import=True,
        )
        ok_count = sum(1 for run in runs if str(run.get("status") or "") == "OK")
        result = {
            "ok": ok_count == len(runs),
            "ok_count": ok_count,
            "error_count": len(runs) - ok_count,
            "runs": runs,
            "mode": f"legacy_compat:{only}",
        }
    return {
        **result,
        "retired_entrypoint": "backfill_soft_data",
        "canonical_writer": "ExternalSourceRunner",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=sorted(_VALID_ONLY))
    args = parser.parse_args(argv)
    result = refresh_all(only=args.only)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
