from __future__ import annotations

import argparse
import json
from typing import Any

from hermes_escape_top.config import load_config, resolve_path
from hermes_escape_top.core.data.external_sources import (
    FredNetLiquidityAdapter,
    FredPercentileAdapter,
    NaaimExposureAdapter,
    fred_net_liquidity_spec,
    fred_percentile_spec,
    naaim_exposure_spec,
    run_external_source_refresh,
    source_status,
)

SOURCE_IDS = ("dollar", "real_rate", "fred_net_liquidity", "naaim_exposure")


def dollar_source(config: dict[str, Any]):
    target = resolve_path(config, "soft_history_dir") / "dollar.csv"
    spec = fred_percentile_spec(
        source_id="dollar",
        target_path=target,
        field="dollar_broad",
    )
    adapter = FredPercentileAdapter(
        series_id="DTWEXBGS",
        field="dollar_broad",
    )
    return spec, adapter


def real_rate_source(config: dict[str, Any]):
    target = resolve_path(config, "soft_history_dir") / "real_rate.csv"
    spec = fred_percentile_spec(
        source_id="real_rate",
        target_path=target,
        field="real_rate_10y",
    )
    adapter = FredPercentileAdapter(
        series_id="DFII10",
        field="real_rate_10y",
    )
    return spec, adapter


def fred_net_liquidity_source(config: dict[str, Any]):
    target = resolve_path(config, "soft_history_dir") / "fred_net_liquidity.csv"
    return fred_net_liquidity_spec(target_path=target), FredNetLiquidityAdapter()


def naaim_exposure_source(config: dict[str, Any]):
    target = resolve_path(config, "soft_history_dir") / "naaim_exposure.csv"
    return naaim_exposure_spec(target_path=target), NaaimExposureAdapter()


def source_factories():
    return {
        "dollar": dollar_source,
        "real_rate": real_rate_source,
        "fred_net_liquidity": fred_net_liquidity_source,
        "naaim_exposure": naaim_exposure_source,
    }


def source_specs(config: dict[str, Any]):
    specs = []
    for source_id in SOURCE_IDS:
        spec, _ = source_factories()[source_id](config)
        specs.append(spec)
    return specs


def refresh_source(source_id: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    factories = source_factories()
    if source_id not in factories:
        raise ValueError(f"unsupported external source: {source_id}")
    spec, adapter = factories[source_id](cfg)
    run = run_external_source_refresh(spec, adapter, resolve_path(cfg, "archive_dir"))
    return run.to_dict()


def status(config: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    cfg = config or load_config()
    return source_status(resolve_path(cfg, "archive_dir"), source_specs(cfg))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh Hermes external data sources independently.")
    parser.add_argument("--source", choices=list(SOURCE_IDS), help="Refresh one source.")
    parser.add_argument("--status", action="store_true", help="Print latest source-run status.")
    args = parser.parse_args(argv)

    if args.status:
        print(json.dumps(status(), ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 0
    if args.source:
        print(json.dumps(refresh_source(args.source), ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
