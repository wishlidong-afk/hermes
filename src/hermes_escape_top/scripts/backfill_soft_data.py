#!/usr/bin/env python3
"""Validated live refresh of the slow soft-data CSVs (FRED net-liquidity, AAII).

Design rules (read-only-on-failure):
  - Fetch into memory first, validate, and only then write.
  - Network is flaky → per-series retries with backoff.
  - Never corrupt an existing CSV: back it up to ``*.csv.bak`` before replacing,
    and refuse to write a frame that fails sanity checks.
  - Honest reporting: every source returns an ``ok`` flag + reason so callers
    (CLI / WebUI button) can show exactly what happened.

Usage:
    python3 -m hermes_escape_top.scripts.backfill_soft_data            # both
    python3 -m hermes_escape_top.scripts.backfill_soft_data --only fred
    python3 -m hermes_escape_top.scripts.backfill_soft_data --only aaii
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
import warnings
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pandas as pd

warnings.filterwarnings("ignore")

from hermes_escape_top.config import load_config, resolve_path
from hermes_escape_top.core.data.macro import (
    FredNetLiquiditySource,
    fetch_fred_graph_csv,
    fred_net_liquidity_frame,
)


def _retry(fn: Callable[[], Any], tries: int = 4, backoff: float = 3.0, label: str = "") -> Any:
    last = None
    for attempt in range(tries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — network failures are expected
            last = exc
            if attempt < tries - 1:
                time.sleep(backoff * (attempt + 1))
    raise last if last else RuntimeError(f"{label} failed")


def _last_date(frame: pd.DataFrame, col: str = "date") -> Optional[str]:
    if frame is None or frame.empty or col not in frame.columns:
        return None
    dates = pd.to_datetime(frame[col], errors="coerce").dropna()
    return dates.max().date().isoformat() if not dates.empty else None


def _read_existing(path: Path) -> pd.DataFrame:
    if path.exists():
        try:
            return pd.read_csv(path)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def _commit(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copyfile(path, path.with_suffix(path.suffix + ".bak"))
    frame.to_csv(path, index=False)


# ── FRED net-liquidity ──────────────────────────────────────────────────────

def refresh_fred_net_liquidity(config: Optional[Dict[str, Any]] = None, start: str = "2015-01-01") -> Dict[str, Any]:
    cfg = config or load_config()
    src = FredNetLiquiditySource()
    path = src.history_path(cfg)
    old = _read_existing(path)
    old_last, old_rows = _last_date(old), int(len(old))

    try:
        series = {
            name: _retry(lambda sid=sid: fetch_fred_graph_csv(sid, start=start), label=sid)
            for name, sid in src.fred_ids.items()
        }
        frame = fred_net_liquidity_frame(series["walcl"], series["wtregen"], series["rrp"])
    except Exception as exc:  # noqa: BLE001
        return {"source": "fred_net_liquidity", "ok": False, "wrote": False,
                "error": f"fetch failed: {exc}", "old_last": old_last}

    new_last, new_rows = _last_date(frame), int(len(frame))
    # sanity: enough rows, advancing (or equal) coverage, net_liq present + in range
    if new_rows < max(100, int(old_rows * 0.9)) or new_last is None:
        return {"source": "fred_net_liquidity", "ok": False, "wrote": False,
                "error": f"sanity fail rows={new_rows} last={new_last}", "old_last": old_last}
    if frame["net_liq"].dropna().empty:
        return {"source": "fred_net_liquidity", "ok": False, "wrote": False,
                "error": "net_liq all-NaN", "old_last": old_last}
    last_nl = float(frame["net_liq"].dropna().iloc[-1])
    if not (1e5 < last_nl < 2e7):
        return {"source": "fred_net_liquidity", "ok": False, "wrote": False,
                "error": f"net_liq out of range: {last_nl}", "old_last": old_last}
    if old_last is not None and new_last < old_last:
        return {"source": "fred_net_liquidity", "ok": False, "wrote": False,
                "error": f"refusing regression new_last {new_last} < old {old_last}", "old_last": old_last}

    advanced = old_last is None or new_last > old_last
    _commit(path, frame)
    return {"source": "fred_net_liquidity", "ok": True, "wrote": True, "advanced": advanced,
            "old_last": old_last, "new_last": new_last, "old_rows": old_rows, "new_rows": new_rows,
            "path": str(path)}


# ── AAII sentiment (best-effort; endpoint historically blocked) ──────────────

_AAII_URLS = [
    "https://www.aaii.com/files/surveys/sentiment.xls",
    "https://www.aaii.com/sentimentsurvey/sent_results",
]


def refresh_aaii_sentiment(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = config or load_config()
    base = resolve_path(cfg, "soft_history_dir")
    path = base / "aaii_sentiment.csv"
    old = _read_existing(path)
    old_last, old_rows = _last_date(old), int(len(old))

    import requests

    raw = None
    used_url = None
    for url in _AAII_URLS:
        try:
            resp = _retry(lambda u=url: requests.get(
                u, timeout=30, headers={"User-Agent": "Mozilla/5.0 (hermes-backfill)"}
            ), tries=3, label=url)
            if resp.status_code == 200 and resp.content:
                raw, used_url = resp, url
                break
        except Exception:
            continue
    if raw is None:
        return {"source": "aaii_sentiment", "ok": False, "wrote": False,
                "error": "all AAII endpoints unreachable/blocked", "old_last": old_last,
                "note": "leave CSV untouched; aaii latency stays high until manual download"}

    # Parse: AAII publishes an .xls (HTML table or BIFF). Try the lenient paths.
    new = None
    try:
        if used_url.endswith(".xls"):
            try:
                new = pd.read_excel(StringIO(raw.text) if False else raw.content)  # type: ignore[arg-type]
            except Exception:
                tables = pd.read_html(raw.text)
                new = tables[0] if tables else None
        else:
            tables = pd.read_html(raw.text)
            new = tables[0] if tables else None
    except Exception as exc:  # noqa: BLE001
        return {"source": "aaii_sentiment", "ok": False, "wrote": False,
                "error": f"fetched but parse failed: {exc}", "old_last": old_last, "url": used_url}

    if new is None or new.empty:
        return {"source": "aaii_sentiment", "ok": False, "wrote": False,
                "error": "fetched but no parseable table", "old_last": old_last, "url": used_url}

    # The raw AAII layout differs from our normalized schema; rather than risk a
    # bad transform that pollutes scoring, we hand the parsed frame to a sidecar
    # file for human review instead of overwriting the canonical CSV.
    sidecar = base / "aaii_sentiment_fetched_raw.csv"
    try:
        new.to_csv(sidecar, index=False)
    except Exception as exc:  # noqa: BLE001
        return {"source": "aaii_sentiment", "ok": False, "wrote": False,
                "error": f"could not write sidecar: {exc}", "old_last": old_last}
    return {"source": "aaii_sentiment", "ok": False, "wrote": False,
            "fetched": True, "url": used_url, "old_last": old_last,
            "sidecar": str(sidecar),
            "note": "raw AAII fetched to sidecar for review; canonical CSV left intact "
                    "(schema mapping is manual to avoid polluting scores)"}


def refresh_all(config: Optional[Dict[str, Any]] = None, only: Optional[str] = None) -> Dict[str, Any]:
    cfg = config or load_config()
    results = []
    if only in (None, "fred"):
        results.append(refresh_fred_net_liquidity(cfg))
    if only in (None, "aaii"):
        results.append(refresh_aaii_sentiment(cfg))
    return {"ok": any(r.get("ok") for r in results), "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validated live refresh of slow soft-data CSVs")
    parser.add_argument("--only", choices=["fred", "aaii"], default=None)
    args = parser.parse_args()
    out = refresh_all(only=args.only)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
