from __future__ import annotations

import argparse
import json

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.market_witness import refresh_market_witness
from hermes_escape_top.core.safe_io import PipelineBusy, pipeline_lock


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare canonical OHLCV with Alpaca SIP shadow bars")
    parser.add_argument("--as-of", required=True, help="Trading date YYYY-MM-DD")
    parser.add_argument(
        "--lock-timeout",
        type=float,
        default=600.0,
        help="Seconds to wait for the shared pipeline write lock",
    )
    args = parser.parse_args(argv)
    try:
        with pipeline_lock(blocking=True, timeout=max(float(args.lock_timeout), 0.0)):
            payload = refresh_market_witness(args.as_of, load_config())
    except PipelineBusy as exc:
        print(json.dumps({"ok": False, "busy": True, "error": str(exc)}, ensure_ascii=False))
        return 75
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "as_of": payload.get("as_of"),
                "summary": payload.get("summary"),
                "cache_path": payload.get("cache_path"),
                "error": payload.get("error"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if payload.get("status") != "FETCH_ERROR" else 1


if __name__ == "__main__":
    raise SystemExit(main())
