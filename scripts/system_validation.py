#!/usr/bin/env python3
"""Hermes system validation regression — data trust / determinism / stability.

Operator's priorities, in order: trustworthy data, no front-back contradiction,
no crash. NOT profitability. Re-runnable: each case asserts in-process and
writes a single JSON report (never relies on stdout, which interleaves badly
on this host — the 2026-06-13 false "gate only scans first file" scare came
from trusting interleaved `cat -A`/print output; lesson: verdict via file).

Usage:
  HERMES_DATA_DIR=<clean root> PYTHONPATH=src python3 scripts/system_validation.py
  -> writes building/reports/system_validation_report.json
Cases that need a clean data root read it from HERMES_DATA_DIR; pure-function
cases construct in-memory data. Returns nonzero if any SYSTEM case fails
(scaffold-only skips are reported separately).
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pandas as pd

RESULTS = []


def rec(cid, cat, desc, passed, detail=""):
    RESULTS.append({"id": cid, "cat": cat, "desc": desc, "pass": bool(passed), "detail": str(detail)[:200]})


def _frame(closes, start="2026-06-01", ticker=None):
    idx = pd.bdate_range(start, periods=len(closes))
    if ticker:
        return pd.DataFrame({(c, ticker): closes for c in ("Open", "High", "Low", "Close", "Adj Close", "Volume")}, index=idx)
    return pd.DataFrame({"Close": closes}, index=idx)


def _scan_history(files: dict) -> list:
    """Run the real integrity scan over a throwaway history dir (isolated env)."""
    from hermes_escape_top.scripts.run_daily_package import _history_integrity_scan
    from hermes_escape_top.config import load_config
    d = Path(tempfile.mkdtemp())
    hist = d / "data" / "history"
    hist.mkdir(parents=True)
    for name, rows in files.items():
        (hist / name).write_text("date,open,high,low,close,adj_close,volume\n" + rows)
    prev = os.environ.get("HERMES_DATA_DIR")
    os.environ["HERMES_DATA_DIR"] = str(d)
    try:
        return _history_integrity_scan(load_config())
    finally:
        if prev is not None:
            os.environ["HERMES_DATA_DIR"] = prev
        shutil.rmtree(d, ignore_errors=True)


# ---- A. DATA TRUST ----
from hermes_escape_top.scripts.backfill_history import _normalize_download, _sanity_check_download

try:
    try:
        _normalize_download(_frame([700, 705], ticker="TSLA"), expected_symbol="QQQ")
        rec("A1", "trust", "cross-wired ticker QQQ<-TSLA rejected", False, "no raise")
    except ValueError as e:
        rec("A1", "trust", "cross-wired ticker QQQ<-TSLA rejected", "ticker mismatch" in str(e))
except Exception as e:
    rec("A1", "trust", "cross-wired ticker rejected", False, repr(e))

try:
    rec("A2", "trust", "correct ticker accepted", not _normalize_download(_frame([700, 705], ticker="QQQ"), expected_symbol="QQQ").empty)
except Exception as e:
    rec("A2", "trust", "correct ticker accepted", False, repr(e))

for cid, sym, ex, new, start, want, note in [
    ("A3", "QQQ", [700, 705, 710], [217, 216], "2026-06-04", False, "magnitude 710->217 rejected"),
    ("A4", "QQQ", [700, 705, 710], [715, 720], "2026-06-04", True, "normal 710->715 accepted"),
    ("A5", "^VIX", [15.0], [38.0], "2026-06-02", True, "real VIX +150% accepted"),
    ("A6", "^VIX", [15.0], [12906.0], "2026-06-02", False, "VIX cross-wire rejected"),
    ("A7", "FNGS", [31.4, 705, 710, 715, 720], [702, 706, 711, 716], "2026-06-01", True, "corrupt anchor outvoted (majority)"),
]:
    try:
        ok, why = _sanity_check_download(sym, _frame(ex), _frame(new, start=start))
        rec(cid, "trust", note, ok == want, why)
    except Exception as e:
        rec(cid, "trust", note, False, repr(e))

# A8-A10: integrity scan must traverse ALL files (the 2026-06-13 scare)
try:
    off = _scan_history({"AAPL.csv": "2026-06-05,1,1,1,100,100,1\n2026-06-08,1,1,1,101,101,1\n",
                         "QQQ.csv": "2026-06-05,1,1,1,705,705,1\n2026-06-08,1,1,1,217,217,1\n"})
    rec("A8", "trust", "integrity scan catches QQQ behind clean AAPL (traverses all files)", any("QQQ" in o for o in off), off)
except Exception as e:
    rec("A8", "trust", "integrity scan traverses all files", False, repr(e))
try:
    off = _scan_history({"_VIX.csv": "2026-06-04,1,1,1,15.4,15.4,0\n2026-06-05,1,1,1,21.5,21.5,0\n"})
    rec("A9", "trust", "integrity scan tolerates real VIX move", not any("_VIX" in o for o in off), off)
except Exception as e:
    rec("A9", "trust", "integrity scan tolerates VIX", False, repr(e))
try:
    off = _scan_history({"KLAC.csv": "2026-06-05,1,1,1,1929,1929,1\n2026-06-08,1,1,1,210,210,1\n"})
    rec("A10", "trust", "component split (KLAC) does not block scoring", not any("KLAC" in o for o in off), off)
except Exception as e:
    rec("A10", "trust", "component split not blocked", False, repr(e))

# ---- B. DETERMINISM ----
ROOT = os.environ.get("HERMES_DATA_DIR")
if ROOT and Path(ROOT, "data/history").exists():
    from hermes_escape_top import pipeline
    try:
        a = pipeline.score_pipeline("2026-06-12", shadow=True, run_type="scheduled")
        b = pipeline.score_pipeline("2026-06-12", shadow=True, run_type="manual_rerun")
        rec("B11", "determinism", "same as_of -> identical input_hash", a["input_hash"] == b["input_hash"])
        rec("B12", "determinism", "same as_of -> identical statuses",
            {k: a["scores"][k]["status"] for k in ("MSTR", "FNGU", "SOXL")} == {k: b["scores"][k]["status"] for k in ("MSTR", "FNGU", "SOXL")})
        rec("B13", "determinism", "run_type differs but input_hash identical (run_ts excluded from hash)",
            a["input_hash"] == b["input_hash"] and a["run_type"] != b["run_type"])
        c = pipeline.score_pipeline("2026-06-12", shadow=True, run_type="scheduled")
        rec("B14", "determinism", "third run -> identical scores bit-for-bit",
            {k: round(a["scores"][k]["final_score"], 9) for k in ("MSTR", "FNGU", "SOXL")} ==
            {k: round(c["scores"][k]["final_score"], 9) for k in ("MSTR", "FNGU", "SOXL")})
    except Exception as e:
        for i in ("B11", "B12", "B13", "B14"):
            rec(i, "determinism", "determinism run", False, repr(e))
else:
    for i, d in [("B11", "input_hash"), ("B12", "statuses"), ("B13", "run_ts excluded"), ("B14", "bit-for-bit")]:
        rec(i, "determinism", d + " (SKIP: no HERMES_DATA_DIR clean root)", True, "skipped")

# ---- C. FRESHNESS / SLO ----
from hermes_escape_top.core.data.adapters import apply_soft_data_slo
import copy
def _slo(on): return {"features": {"use_soft_data_max_age": on}, "soft_data_slo": {"default_max_age_days": 13, "max_age_days": {"dollar": 6}}}
def _recs(): return {"dollar": {"name": "dollar", "value": 0.4, "data_available": True, "latency_days": 9, "reason": "", "fields": {"p": 0.4}},
                     "naaim": {"name": "naaim", "value": 0.9, "data_available": True, "latency_days": 3, "reason": "", "fields": {"p": 0.9}},
                     "gex": {"name": "gex", "value": None, "data_available": False, "latency_days": 0, "reason": "off", "fields": {}}}
try:
    r = apply_soft_data_slo(_recs(), _slo(True))
    rec("C17", "freshness", "over-age dollar -> degraded missing (flag ON)", r["dollar"]["data_available"] is False and r["dollar"]["value"] is None)
    rec("C19", "freshness", "within-SLO naaim untouched", r["naaim"]["value"] == 0.9)
    rec("C20", "freshness", "already-missing gex left alone", r["gex"]["reason"] == "off")
except Exception as e:
    for i in ("C17", "C19", "C20"):
        rec(i, "freshness", "SLO", False, repr(e))
try:
    snap = _recs(); rec("C18", "freshness", "flag OFF -> strict no-op", apply_soft_data_slo(copy.deepcopy(snap), _slo(False)) == snap)
except Exception as e:
    rec("C18", "freshness", "SLO no-op", False, repr(e))

# ---- D. STABILITY ----
try: rec("D21", "stability", "empty history -> no crash", isinstance(_scan_history({"QQQ.csv": ""}), list))
except Exception as e: rec("D21", "stability", "empty history", False, repr(e))
try: rec("D22", "stability", "single-row history -> no crash", isinstance(_scan_history({"QQQ.csv": "2026-06-08,1,1,1,700,700,1\n"}), list))
except Exception as e: rec("D22", "stability", "single-row", False, repr(e))
from hermes_escape_top.core.decision.verdict import status_from_score
try:
    cfg = {"status_thresholds": {"EXIT": 75, "DEFENSIVE_EXIT": 70, "REDUCE": 50, "TRIM": 35, "WATCH": 20, "_note": "x"}}
    rec("D23", "stability", "_note threshold key -> no crash, EXIT@80", status_from_score(80, cfg) == "EXIT")
except Exception as e: rec("D23", "stability", "_note landmine", False, repr(e))
try:
    rec("D25", "stability", "all-NaN soft record -> SLO no crash",
        isinstance(apply_soft_data_slo({"dollar": {"name": "dollar", "value": float("nan"), "data_available": True, "latency_days": 2, "reason": "", "fields": {"p": float("nan")}}}, _slo(True)), dict))
except Exception as e: rec("D25", "stability", "NaN soft", False, repr(e))

# ---- E. LOGIC ----
try:
    cfg = {"status_thresholds": {"EXIT": 75, "DEFENSIVE_EXIT": 70, "REDUCE": 50, "TRIM": 35, "WATCH": 20}}
    seq = [status_from_score(x, cfg) for x in (10, 25, 40, 55, 72, 80)]
    order = ["HOLD", "WATCH", "TRIM", "REDUCE", "DEFENSIVE_EXIT", "EXIT"]
    rec("E28", "logic", "status ladder monotonic in score", all(order.index(seq[i]) <= order.index(seq[i + 1]) for i in range(len(seq) - 1)), seq)
    rec("E29", "logic", "threshold 75 -> EXIT inclusive", status_from_score(75, cfg) == "EXIT")
    rec("E30", "logic", "74.99 -> not EXIT", status_from_score(74.99, cfg) != "EXIT")
    rec("E27", "logic", "relief=0 == base mapping", status_from_score(60, cfg) == status_from_score(60, cfg, relief=0.0))
except Exception as e:
    for i in ("E27", "E28", "E29", "E30"):
        rec(i, "logic", "logic", False, repr(e))

# ---- F. CONFIG byte-identical (indicator cache) — proper in-process flag toggle ----
if ROOT and Path(ROOT, "data/history").exists():
    try:
        from hermes_escape_top import pipeline as _pl, config as _cfgmod
        base_cfg = _cfgmod.load_config()
        cfg_off = copy.deepcopy(base_cfg); cfg_off["features"]["use_indicator_cache"] = False
        cfg_on = copy.deepcopy(base_cfg); cfg_on["features"]["use_indicator_cache"] = True
        # write temp config files and pass via config_path (avoids monkeypatch pitfalls)
        import tempfile as _tf
        po = Path(_tf.mktemp(suffix=".json")); po.write_text(json.dumps(cfg_off))
        pn = Path(_tf.mktemp(suffix=".json")); pn.write_text(json.dumps(cfg_on))
        roff = _pl.score_pipeline("2026-06-12", config_path=po, shadow=True, run_type="scheduled")
        ron = _pl.score_pipeline("2026-06-12", config_path=pn, shadow=True, run_type="scheduled")
        rec("F31", "config", "indicator cache ON vs OFF -> identical input_hash", roff["input_hash"] == ron["input_hash"], f"{roff['input_hash'][:8]} vs {ron['input_hash'][:8]}")
        rec("F33", "config", "indicator cache ON vs OFF -> identical statuses",
            {k: roff["scores"][k]["status"] for k in ("MSTR", "FNGU", "SOXL")} == {k: ron["scores"][k]["status"] for k in ("MSTR", "FNGU", "SOXL")})
        po.unlink(missing_ok=True); pn.unlink(missing_ok=True)
    except Exception as e:
        for i in ("F31", "F33"):
            rec(i, "config", "cache byte-identical", False, repr(e))
else:
    for i in ("F31", "F33"):
        rec(i, "config", "cache byte-identical (SKIP: no clean root)", True, "skipped")

# ---- write report ----
npass = sum(1 for r in RESULTS if r["pass"])
out = Path("building/reports/system_validation_report.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({"pass": npass, "total": len(RESULTS), "results": RESULTS}, indent=1, ensure_ascii=False))
fails = [r for r in RESULTS if not r["pass"]]
print(f"VALIDATION {npass}/{len(RESULTS)} pass; fails={[r['id'] for r in fails]}")
raise SystemExit(1 if fails else 0)
