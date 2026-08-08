from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..config import load_config, resolve_path
from ..core.data.market_third_source import (
    retry_market_admission_third_source_shadow,
)
from ..core.safe_io import PipelineBusy, pipeline_lock


def run_retry(
    *,
    config: dict[str, Any] | None = None,
    retry_fn: Callable[[Path], dict[str, Any]] = retry_market_admission_third_source_shadow,
    lock_fn: Callable[..., Any] = pipeline_lock,
    lock_timeout: float = 600.0,
) -> dict[str, Any]:
    current = config if config is not None else load_config()
    archive_dir = Path(resolve_path(current, "archive_dir"))
    with lock_fn(
        blocking=True,
        timeout=max(float(lock_timeout), 0.0),
        path=archive_dir / ".pipeline.lock",
    ):
        return retry_fn(archive_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Retry delayed market-admission third-source evidence",
    )
    parser.add_argument(
        "--lock-timeout",
        type=float,
        default=600.0,
        help="Seconds to wait for the shared pipeline write lock",
    )
    args = parser.parse_args(argv)
    try:
        result = run_retry(lock_timeout=args.lock_timeout)
    except PipelineBusy as exc:
        print(json.dumps({"status": "BUSY", "error": str(exc)}, ensure_ascii=False))
        return 75
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if str(result.get("status") or "") in {
        "OK",
        "NOT_NEEDED",
        "NO_ADMISSION",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
