#!/usr/bin/env python3
"""Pre-deploy / pre-trust validation smoke gate.

Catches the "fake data -> fake advice" class BEFORE it reaches the live dashboard
and the operator's eyes, by asserting a handful of invariants on the current
state. Each check maps to a real 2026-06 incident the unit suite did NOT catch
(all three were found by live use). Read-only; exits non-zero with a report on
any FATAL failure so deploy_to_live / the daily run can refuse to ship a degraded
state.

Checks (FATAL unless noted):
  1. FRED publish_date is per-row and not future-stamped -> the 2026-06-13
     realtime_start outage that zeroed A10 and broke backtest PIT.
  2. Every flag-ON soft source is available in the latest official payload ->
     the same outage's symptom (real_rate/A10 silently MISSING).
  3. The rendered decision evidence carries no NA/undefined leak -> the
     2026-06-14 "A模块 NA" / "BRK.B NA" render bugs.
  4. Data manifest is not in DRIFT -> stale/corrupt-history guard.
  5. (WARN) No unexplained soft status flip vs the previous official run ->
     the 前后一致性 the operator cares about; a flip without a hard valve is
     surfaced but does not fail the gate (legit threshold crossings happen).

Usage:
  python3 -m hermes_escape_top.scripts.predeploy_smoke
  python3 -m hermes_escape_top.scripts.predeploy_smoke --json
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Tuple

from ..config import load_config, resolve_path


# FRED-sourced soft series -> their feature flag. Only flag-ON series are checked.
FRED_SOFT_SOURCES = {
    "real_rate": "data_real_rate",
    "dollar": "data_dollar",
    "hy_oas": "data_hy_oas",
    "yield_curve": "data_yield_curve",
    "nfci": "data_nfci",
}
# Soft sources that are off/absent by design — never a smoke failure.
_EXPECTED_OFF = {"gex", "valuation"}

CheckResult = Tuple[str, bool, str]  # (name, ok, detail)


def _read_recent_official_payloads(config: Dict[str, Any], n: int = 2) -> List[Dict[str, Any]]:
    """Tail-read the audit; return up to ``n`` most-recent OFFICIAL (scheduled)
    payloads for distinct as_of, oldest->newest. Tail-read so a large log is not
    parsed front to back."""
    path = resolve_path(config, "archive_dir") / "audit_log.jsonl"
    if not path.exists():
        return []
    chunk = 12 * 1024 * 1024
    with path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - chunk))
        data = fh.read()
    lines = data.split(b"\n")
    if size > chunk:
        lines = lines[1:]
    by_day: Dict[str, Dict[str, Any]] = {}
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except Exception:
            continue
        pl = rec.get("payload") if isinstance(rec, dict) else None
        pl = pl if isinstance(pl, dict) else rec
        if not isinstance(pl, dict) or "scores" not in pl:
            continue
        if str(pl.get("run_type", "scheduled")) != "scheduled":
            continue
        day = str(pl.get("as_of", ""))[:10]
        if day:
            by_day[day] = pl
    return [by_day[d] for d in sorted(by_day)[-n:]]


def check_fred_publish_dates(config: Dict[str, Any]) -> CheckResult:
    import pandas as pd

    feats = config.get("features", {}) or {}
    base = resolve_path(config, "soft_history_dir")
    bad: List[str] = []
    for name, flag in FRED_SOFT_SOURCES.items():
        if not feats.get(flag, False):
            continue
        path = base / f"{name}.csv"
        if not path.exists():
            bad.append(f"{name}: CSV missing")
            continue
        df = pd.read_csv(path, parse_dates=["date", "publish_date"])
        if df.empty or "publish_date" not in df.columns:
            continue
        if len(df) > 1 and df["publish_date"].nunique() <= 1:
            bad.append(f"{name}: publish_date collapsed to one value "
                       f"({df['publish_date'].iloc[-1].date()}) — realtime_start regression")
            continue
        lag = (df["publish_date"] - df["date"]).dt.days
        if float(lag.max()) > 5:
            bad.append(f"{name}: publish_date lags up to {int(lag.max())}d (>5; future-stamp?)")
    return ("FRED publish_date per-row", not bad, "OK" if not bad else "; ".join(bad))


def check_on_sources_available(config: Dict[str, Any], payload: Dict[str, Any]) -> CheckResult:
    feats = config.get("features", {}) or {}
    records = (payload.get("soft_data") or {}).get("records") or {}
    missing: List[str] = []
    try:
        from ..core.data.risk_signals import _all_risk_sources
        for src in _all_risk_sources():
            flag = getattr(src, "feature_flag", "")
            name = getattr(src, "name", "")
            if not feats.get(flag, False) or name in _EXPECTED_OFF:
                continue
            rec = records.get(name) or {}
            if rec and not rec.get("data_available", True):
                missing.append(f"{name}: {rec.get('reason', 'MISSING')}")
    except Exception as exc:  # noqa: BLE001
        return ("ON soft sources available", False, f"check error: {exc!r}")
    return ("ON soft sources available", not missing, "OK" if not missing else "; ".join(missing))


def check_no_na_in_evidence(payload: Dict[str, Any]) -> CheckResult:
    try:
        from ..web.render import _render_evidence_strip
        html = _render_evidence_strip(payload)
    except Exception as exc:  # noqa: BLE001
        return ("decision evidence no-NA", False, f"render error: {exc!r}")
    leaks = [t for t in ("A模块 NA", "BRK.B NA", "undefined", "NaN") if t in html]
    return ("decision evidence no-NA", not leaks, "OK" if not leaks else f"leaked: {leaks}")


def check_manifest_not_drift(config: Dict[str, Any]) -> CheckResult:
    try:
        from ..web.refresh import manifest_status
        status = str((manifest_status(config) or {}).get("status", "") or "")
    except Exception as exc:  # noqa: BLE001
        return ("manifest not DRIFT", False, f"manifest_status error: {exc!r}")
    return ("manifest not DRIFT", status != "DRIFT", status or "unknown")


def check_no_unexplained_flip(prev: Optional[Dict[str, Any]], curr: Optional[Dict[str, Any]]) -> CheckResult:
    if not prev or not curr:
        return ("no unexplained soft flip", True, "insufficient official history (skipped)")
    issues: List[str] = []
    for sym in ("MSTR", "FNGU", "SOXL"):
        ps = (prev.get("scores") or {}).get(sym) or {}
        cs = (curr.get("scores") or {}).get(sym) or {}
        if not ps or not cs or ps.get("status") == cs.get("status"):
            continue
        if not (ps.get("hard_valve_hits") or cs.get("hard_valve_hits")):
            issues.append(f"{sym}: {ps.get('status')}->{cs.get('status')} (no hard valve)")
    return ("no unexplained soft flip", not issues, "OK" if not issues else "; ".join(issues))


def run_smoke(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run all checks; return {ok, fatal_ok, checks:[{name,ok,fatal,detail}]}."""
    config = config or load_config()
    payloads = _read_recent_official_payloads(config, n=2)
    curr = payloads[-1] if payloads else {}
    prev = payloads[-2] if len(payloads) >= 2 else None

    fatal: List[CheckResult] = [
        check_fred_publish_dates(config),
        check_on_sources_available(config, curr),
        check_no_na_in_evidence(curr),
        check_manifest_not_drift(config),
    ]
    warn: List[CheckResult] = [check_no_unexplained_flip(prev, curr)]

    checks = ([{"name": n, "ok": ok, "fatal": True, "detail": d} for n, ok, d in fatal]
              + [{"name": n, "ok": ok, "fatal": False, "detail": d} for n, ok, d in warn])
    fatal_ok = all(ok for _, ok, _ in fatal)
    return {
        "ok": fatal_ok,
        "fatal_ok": fatal_ok,
        "as_of": str(curr.get("as_of", "")) if curr else None,
        "checks": checks,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Pre-deploy validation smoke gate")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args()
    result = run_smoke()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"[smoke] as_of={result.get('as_of')}  overall={'PASS' if result['ok'] else 'FAIL'}")
        for c in result["checks"]:
            mark = "✓" if c["ok"] else ("✗" if c["fatal"] else "⚠")
            tag = "" if c["fatal"] else " (warn)"
            print(f"  {mark} {c['name']}{tag}: {c['detail']}")
    sys.exit(0 if result["ok"] else 2)


if __name__ == "__main__":
    main()
