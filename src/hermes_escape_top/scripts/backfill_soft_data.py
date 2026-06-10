#!/usr/bin/env python3
"""Validated live refresh of the slow soft-data CSVs.

Covers: FRED net-liquidity, FRED risk signals (real_rate/dollar/yield_curve/
hy_oas), NAAIM exposure index, AAII sentiment (best-effort).

Design rules (read-only-on-failure):
  - Fetch into memory first, validate, and only then write.
  - Network is flaky → per-series retries with backoff.
  - Never corrupt an existing CSV: back it up to ``*.csv.bak`` before replacing,
    and refuse to write a frame that fails sanity checks.
  - Failure of any single source is non-fatal: the others still run.
  - Honest reporting: every source returns an ``ok`` flag + reason so callers
    (CLI / WebUI button / run_daily) can show exactly what happened.

Usage:
    python3 -m hermes_escape_top.scripts.backfill_soft_data
    python3 -m hermes_escape_top.scripts.backfill_soft_data --only fred
    python3 -m hermes_escape_top.scripts.backfill_soft_data --only naaim
    python3 -m hermes_escape_top.scripts.backfill_soft_data --only fred_risk
    python3 -m hermes_escape_top.scripts.backfill_soft_data --only aaii
    python3 -m hermes_escape_top.scripts.backfill_soft_data --only cot
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
import warnings
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

warnings.filterwarnings("ignore")

from hermes_escape_top.config import load_config, resolve_path
from hermes_escape_top.core.data.macro import (
    FredNetLiquiditySource,
    fetch_fred_graph_csv,
    fred_net_liquidity_frame,
)
from hermes_escape_top.core.data.risk_signals import (
    FredPercentileSource,
    fetch_fred_series,
    _all_risk_sources,
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


# ── FRED risk signals (real_rate / dollar / yield_curve / hy_oas) ───────────

def refresh_fred_risk_signals(config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Refresh all enabled FRED-backed risk-signal CSVs (A9-A19 sources).

    Calls FredPercentileSource.backfill() for each active FRED source.
    ETF-ratio sources (defensive_rotation etc.) derive from local OHLCV and
    do not need network refresh here — they recompute at score time.
    Sources whose flag is OFF are skipped (no network call, no file write).
    """
    cfg = config or load_config()
    feats = cfg.get("features", {}) or {}
    results = []

    for src in _all_risk_sources():
        if not isinstance(src, FredPercentileSource):
            continue
        if not bool(feats.get(src.feature_flag, False)):
            results.append({"source": src.name, "ok": True, "wrote": False,
                            "skipped": True, "reason": f"flag {src.feature_flag} is OFF"})
            continue

        path = src.history_path(cfg)
        old = _read_existing(path)
        old_last, old_rows = _last_date(old), int(len(old))
        try:
            frame = _retry(lambda s=src: s.build_frame(config=cfg), tries=3, label=src.name)
        except Exception as exc:  # noqa: BLE001
            results.append({"source": src.name, "ok": False, "wrote": False,
                            "error": f"fetch/build failed: {exc}", "old_last": old_last})
            continue

        new_last, new_rows = _last_date(frame), int(len(frame))
        if new_rows < max(10, int(old_rows * 0.9)) or new_last is None:
            results.append({"source": src.name, "ok": False, "wrote": False,
                            "error": f"sanity fail rows={new_rows} last={new_last}", "old_last": old_last})
            continue
        if old_last is not None and new_last < old_last:
            results.append({"source": src.name, "ok": False, "wrote": False,
                            "error": f"refusing regression {new_last} < {old_last}", "old_last": old_last})
            continue

        advanced = old_last is None or new_last > old_last
        _commit(path, frame)
        results.append({"source": src.name, "ok": True, "wrote": True, "advanced": advanced,
                        "old_last": old_last, "new_last": new_last,
                        "old_rows": old_rows, "new_rows": new_rows, "path": str(path)})

    return results


# ── NAAIM Exposure Index ─────────────────────────────────────────────────────

def refresh_naaim(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Refresh NAAIM Exposure Index from naaim.org.

    Delegates to the dedicated backfill_naaim module which handles the
    dynamic xlsx URL discovery. Returns a result dict in the same schema
    as the other refresh functions.
    """
    cfg = config or load_config()
    feats = cfg.get("features", {}) or {}
    if not bool(feats.get("data_naaim", False)):
        return {"source": "naaim_exposure", "ok": True, "wrote": False,
                "skipped": True, "reason": "flag data_naaim is OFF"}

    try:
        from hermes_escape_top.scripts import backfill_naaim as _naaim_mod
        raw = _naaim_mod.run(dry_run=False)
        ok = "error" not in raw and int(raw.get("rows", 0)) > 0
        return {
            "source": "naaim_exposure",
            "ok": ok,
            "wrote": ok,
            "advanced": ok,
            "rows": raw.get("rows", 0),
            "date_range": raw.get("date_range"),
            "url": raw.get("url"),
            "error": raw.get("error") if not ok else None,
            "note": "NAAIM is published weekly (Wednesday); occasional failures are normal",
        }
    except Exception as exc:  # noqa: BLE001
        return {"source": "naaim_exposure", "ok": False, "wrote": False,
                "error": f"NAAIM refresh failed: {exc}",
                "note": "NAAIM is published weekly (Wednesday); occasional failures are normal"}


# ── CFTC COT NQ futures (weekly, published Fridays with ~3-day lag) ────────────

def refresh_cot(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Incremental refresh of CFTC COT NQ futures positioning data.

    Fetches only the last 2 calendar years from CFTC (fast — 2 zip files),
    then merges with the existing CSV so full history is preserved.
    """
    from datetime import date as _date_cls
    from hermes_escape_top.scripts import backfill_cot

    cfg = config or load_config()
    out_csv = backfill_cot.OUT_CSV
    old_last = None
    try:
        existing = _read_existing(out_csv)
        existing["date"] = pd.to_datetime(existing["date"], errors="coerce")
        old_last = _last_date(existing)
        current_year = _date_cls.today().year
        raw = backfill_cot._fetch_all(start_year=current_year - 1)
        if raw.empty:
            return {"source": "cot_nq", "ok": False, "wrote": False,
                    "error": "no NQ rows from CFTC (site may be down)", "old_last": old_last}
        fresh = backfill_cot._compute(raw)
        if not existing.empty:
            combined = (pd.concat([existing, fresh])
                        .drop_duplicates(subset=["date"])
                        .sort_values("date")
                        .reset_index(drop=True))
        else:
            combined = fresh
        new_last = _last_date(combined)
        advanced = new_last != old_last
        _commit(out_csv, combined)
        return {"source": "cot_nq", "ok": True, "wrote": True, "advanced": advanced,
                "rows": len(combined), "old_last": old_last, "new_last": new_last,
                "note": "CFTC publishes every Friday; no change mid-week is normal"}
    except Exception as exc:  # noqa: BLE001
        return {"source": "cot_nq", "ok": False, "wrote": False,
                "error": str(exc), "old_last": old_last}


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


# ── Aggregate entry points ───────────────────────────────────────────────────

_VALID_ONLY = {"fred", "fred_risk", "naaim", "aaii", "cot"}


def refresh_all(config: Optional[Dict[str, Any]] = None,
                only: Optional[str] = None) -> Dict[str, Any]:
    """Run all (or selected) soft-data refreshes.

    ``only`` may be one of: "fred", "fred_risk", "naaim", "aaii", "cot".
    With only=None all sources run; failures are non-fatal.
    """
    cfg = config or load_config()
    results: List[Dict[str, Any]] = []

    if only in (None, "fred"):
        results.append(refresh_fred_net_liquidity(cfg))

    if only in (None, "fred_risk"):
        results.extend(refresh_fred_risk_signals(cfg))

    if only in (None, "naaim"):
        results.append(refresh_naaim(cfg))

    if only in (None, "aaii"):
        results.append(refresh_aaii_sentiment(cfg))

    if only in (None, "cot"):
        results.append(refresh_cot(cfg))

    any_ok = any(r.get("ok") for r in results)
    any_wrote = any(r.get("wrote") for r in results)
    errors = [r for r in results if not r.get("ok") and not r.get("skipped")]
    return {
        "ok": any_ok,
        "wrote": any_wrote,
        "errors": len(errors),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validated live refresh of soft-data CSVs")
    parser.add_argument("--only", choices=sorted(_VALID_ONLY), default=None,
                        help="Refresh only this source group (default: all)")
    args = parser.parse_args()
    out = refresh_all(only=args.only)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
