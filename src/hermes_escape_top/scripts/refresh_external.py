from __future__ import annotations

import argparse
import json
from typing import Any

from hermes_escape_top.config import load_config, resolve_path
from hermes_escape_top.core.data.external_sources import (
    FredPercentileAdapter,
    fred_percentile_spec,
    run_external_source_refresh,
    source_status,
)


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


def source_specs(config: dict[str, Any]):
    spec, _ = dollar_source(config)
    return [spec]


def refresh_source(source_id: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    if source_id != "dollar":
        raise ValueError(f"unsupported external source: {source_id}")
    spec, adapter = dollar_source(cfg)
    run = run_external_source_refresh(spec, adapter, resolve_path(cfg, "archive_dir"))
    return run.to_dict()


def status(config: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    cfg = config or load_config()
    return source_status(resolve_path(cfg, "archive_dir"), source_specs(cfg))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh Hermes external data sources independently.")
    parser.add_argument("--source", choices=["dollar"], help="Refresh one source.")
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
