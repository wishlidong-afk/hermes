from __future__ import annotations

import argparse
import json

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.market_witness import refresh_market_witness


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare canonical OHLCV with Alpaca SIP shadow bars")
    parser.add_argument("--as-of", required=True, help="Trading date YYYY-MM-DD")
    args = parser.parse_args()
    payload = refresh_market_witness(args.as_of, load_config())
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
