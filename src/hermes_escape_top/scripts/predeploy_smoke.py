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
  2. Every flag-ON risk source is available, except a missing record whose SLO
     expiry exactly matches config + payload evidence (WARN). Any other missing
     record, and any available->MISSING regression vs the previous official run,
     remains fatal — covering always-on sources too, not just flag-gated risk
     sources -> the real_rate/A10 outage symptom.
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
import contextlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ..config import DATA_DIR_ENV, PACKAGE_DIR, load_config, resolve_path
from ..core.data.runtime_root import require_explicit_runtime_data_root


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
_SLO_STALE_REASON = re.compile(r"^stale: latency (?P<latency>\d+)d > max_age (?P<max_age>\d+)d$")


@contextlib.contextmanager
def repo_live_data_root() -> Iterator[Path]:
    """Use live current data when the smoke is run from the repo checkout.

    The repo package still contains development fixture data; running the smoke
    directly from ``src/`` should validate code against live/mirrored runtime
    state, not fail on stale package fixtures. Explicit HERMES_DATA_DIR always
    wins, and packaged/staged releases keep their own data symlink.
    """
    configured = str(os.environ.get(DATA_DIR_ENV) or "").strip()
    if configured:
        yield Path(configured).expanduser().resolve()
        return
    repo_root = _repo_root_for_package(PACKAGE_DIR)
    live_pkg = _live_current_package_dir()
    if repo_root is None:
        yield PACKAGE_DIR.resolve()
        return
    if live_pkg is None:
        yield require_explicit_runtime_data_root("predeploy_smoke")
        return
    previous = os.environ.get(DATA_DIR_ENV)
    os.environ[DATA_DIR_ENV] = str(live_pkg)
    try:
        yield live_pkg.resolve()
    finally:
        if previous is None:
            os.environ.pop(DATA_DIR_ENV, None)
        else:
            os.environ[DATA_DIR_ENV] = previous


def _repo_root_for_package(package_dir: Path) -> Optional[Path]:
    try:
        if package_dir.parent.name != "src":
            return None
        repo = package_dir.parents[1]
    except IndexError:
        return None
    return repo if (repo / ".git").exists() else None


def _live_current_package_dir() -> Optional[Path]:
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    live_pkg = home / ".hermes" / "skills" / "investment" / "escape-top" / "current" / "hermes_escape_top"
    return live_pkg if (live_pkg / "data").exists() else None


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
    for tail_line, raw in enumerate(lines, start=1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(
                f"malformed audit evidence at tail line {tail_line}: {exc}"
            ) from exc
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
    exact_vintage = bool(feats.get("use_fred_vintage_pit", False))
    if exact_vintage:
        vintage_path = base / "fred_vintages.csv"
        if not vintage_path.exists():
            bad.append("fred_vintages.csv missing")
        else:
            try:
                events = pd.read_csv(vintage_path)
                required = {
                    "series_id",
                    "observation_date",
                    "realtime_start",
                    "vintage_date",
                    "response_sha256",
                }
                missing = sorted(required - set(events.columns))
                if missing:
                    bad.append("fred_vintages.csv missing columns: " + ", ".join(missing))
                elif events.duplicated(["series_id", "observation_date", "vintage_date"]).any():
                    bad.append("fred_vintages.csv duplicate ALFRED event keys")
            except Exception as exc:
                bad.append(f"fred_vintages.csv unreadable: {exc}")
    for name, flag in FRED_SOFT_SOURCES.items():
        if not feats.get(flag, False):
            continue
        suffix = "_vintage" if exact_vintage else ""
        path = base / f"{name}{suffix}.csv"
        if not path.exists():
            bad.append(f"{name}: CSV missing")
            continue
        try:
            df = pd.read_csv(path, parse_dates=["date", "publish_date"])
        except Exception as exc:
            bad.append(f"{name}: CSV unreadable: {exc}")
            continue
        if df.empty or "publish_date" not in df.columns:
            continue
        if len(df) > 1 and df["publish_date"].nunique() <= 1:
            bad.append(f"{name}: publish_date collapsed to one value "
                       f"({df['publish_date'].iloc[-1].date()}) — realtime_start regression")
            continue
        if exact_vintage:
            required = {"realtime_start", "vintage_date"}
            if not required.issubset(df.columns):
                bad.append(f"{name}: exact vintage columns missing")
                continue
            realtime = pd.to_datetime(df["realtime_start"], errors="coerce")
            vintage = pd.to_datetime(df["vintage_date"], errors="coerce")
            published = pd.to_datetime(df["publish_date"], errors="coerce")
            if (
                realtime.isna().any()
                or vintage.isna().any()
                or not realtime.equals(vintage)
                or not realtime.equals(published)
            ):
                bad.append(f"{name}: vintage columns disagree")
            if not published.is_monotonic_increasing or published.duplicated().any():
                bad.append(f"{name}: exact publish_date must be unique and monotonic")
        else:
            lag = (df["publish_date"] - df["date"]).dt.days
            if float(lag.max()) > 5:
                bad.append(f"{name}: publish_date lags up to {int(lag.max())}d (>5; future-stamp?)")
    return ("FRED publish_date per-row", not bad, "OK" if not bad else "; ".join(bad))


def check_on_sources_available(config: Dict[str, Any], payload: Dict[str, Any]) -> CheckResult:
    feats = config.get("features", {}) or {}
    records = (payload.get("soft_data") or {}).get("records") or {}
    missing: List[str] = []
    expected_stale: List[str] = []
    try:
        from ..core.data.risk_signals import _all_risk_sources
        for src in _all_risk_sources():
            flag = getattr(src, "feature_flag", "")
            name = getattr(src, "name", "")
            if not feats.get(flag, False) or name in _EXPECTED_OFF:
                continue
            rec = records.get(name)
            if not isinstance(rec, dict) or not rec:
                missing.append(f"{name}: absent")
                continue
            if not rec.get("data_available", False):
                if _is_policy_verified_slo_stale(config, name, rec):
                    expected_stale.append(f"{name}: {rec.get('reason')}")
                else:
                    missing.append(f"{name}: {rec.get('reason', 'MISSING')}")
    except Exception as exc:  # noqa: BLE001
        return ("ON soft sources available", False, f"check error: {exc!r}")
    detail = "; ".join(missing) if missing else "OK"
    if not missing and expected_stale:
        detail = "policy-verified stale accepted: " + "; ".join(expected_stale)
    return ("ON soft sources available", not missing, detail)


def _is_policy_verified_slo_stale(config: Dict[str, Any], name: str, record: Dict[str, Any]) -> bool:
    features = config.get("features", {}) or {}
    if not features.get("use_soft_data_max_age", False):
        return False
    match = _SLO_STALE_REASON.fullmatch(str(record.get("reason", "")))
    if match is None:
        return False
    slo = config.get("soft_data_slo", {}) or {}
    configured = (slo.get("max_age_days", {}) or {}).get(
        name,
        slo.get("default_max_age_days"),
    )
    latency = record.get("latency_days")
    try:
        configured_value = float(configured)
        latency_value = float(latency)
    except (TypeError, ValueError):
        return False
    reason_latency = int(match.group("latency"))
    reason_max_age = int(match.group("max_age"))
    return (
        latency_value == reason_latency
        and configured_value == reason_max_age
        and latency_value > configured_value
    )


def check_expected_slo_stale(config: Dict[str, Any], payload: Dict[str, Any]) -> CheckResult:
    records = (payload.get("soft_data") or {}).get("records") or {}
    stale = [
        f"{name}: {record.get('reason')}"
        for name, record in sorted(records.items())
        if isinstance(record, dict) and _is_policy_verified_slo_stale(config, name, record)
    ]
    return ("policy-verified SLO stale", not stale, "OK" if not stale else "; ".join(stale))


def check_no_source_regression(
    prev: Optional[Dict[str, Any]],
    curr: Optional[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> CheckResult:
    """Flag any soft source that was available in the previous OFFICIAL run but is
    now MISSING — the real_rate-went-dark regression, across ALL sources. This
    closes check_on_sources_available's gap: it only iterated the flag-gated risk
    sources, so a regression in an always-on source (naaim / aaii / cboe_pcr /
    net_liquidity / component_breadth) would have slipped through. Only a true
    regression fails: steady-state-absent / feature-disabled sources and legitimate
    weekly gaps were not available in prev either, so they are never flagged. A
    newly stale source is nonfatal only when its reason, latency and configured SLO
    pass `_is_policy_verified_slo_stale`."""
    if not prev or not curr:
        return ("no soft-source regression", True, "insufficient official history (skipped)")
    prev_recs = (prev.get("soft_data") or {}).get("records") or {}
    curr_recs = (curr.get("soft_data") or {}).get("records") or {}
    regressed: List[str] = []
    for name, prec in prev_recs.items():
        # gex/valuation are off-by-design and flip available<->missing harmlessly
        # (they don't feed advice) — excluding them, like check_on_sources_available.
        if name in _EXPECTED_OFF:
            continue
        if not isinstance(prec, dict) or not prec.get("data_available"):
            continue
        crec = curr_recs.get(name) or {}
        if not crec.get("data_available", False):
            if config is not None and _is_policy_verified_slo_stale(config, name, crec):
                continue
            regressed.append(f"{name}: was available, now MISSING ({crec.get('reason', 'absent')})")
    return ("no soft-source regression", not regressed,
            "OK" if not regressed else "; ".join(regressed))


# Always-on DAILY soft sources that should never be MISSING (no weekly publication
# gap — they refresh/cache every trading day). A missing one is a real failure even
# if it has been missing across both official runs (which the regression delta would
# not catch). Weekly sources (aaii / naaim / cot) are deliberately NOT here: they can
# be legitimately absent, so they're covered by the regression check + SLO/health.
ALWAYS_ON_DAILY = {"net_liquidity", "cboe_pcr", "cboe_indices", "component_breadth"}


def check_always_on_daily_available(payload: Dict[str, Any]) -> CheckResult:
    """Absolute availability for the always-on daily sources — closes the steady-
    state gap the regression delta leaves (a daily source broken across both runs)."""
    records = (payload.get("soft_data") or {}).get("records") or {}
    missing: List[str] = []
    for name in sorted(ALWAYS_ON_DAILY):
        rec = records.get(name)
        if rec is None:
            continue  # not in this build's payload — don't assert a source that isn't wired
        if not rec.get("data_available", False):
            missing.append(f"{name}: {rec.get('reason', 'MISSING')}")
    return ("always-on daily sources available", not missing, "OK" if not missing else "; ".join(missing))


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
    with repo_live_data_root() if config is None else contextlib.nullcontext(None) as data_root:
        config = config or load_config()
        payloads = _read_recent_official_payloads(config, n=2)
        curr = payloads[-1] if payloads else {}
        prev = payloads[-2] if len(payloads) >= 2 else None

        fatal: List[CheckResult] = [
            check_fred_publish_dates(config),
            check_on_sources_available(config, curr),
            check_always_on_daily_available(curr),
            check_no_source_regression(prev, curr, config),
            check_no_na_in_evidence(curr),
            check_manifest_not_drift(config),
        ]
        warn: List[CheckResult] = [
            check_expected_slo_stale(config, curr),
            check_no_unexplained_flip(prev, curr),
        ]

        checks = ([{"name": n, "ok": ok, "fatal": True, "detail": d} for n, ok, d in fatal]
                  + [{"name": n, "ok": ok, "fatal": False, "detail": d} for n, ok, d in warn])
        fatal_ok = all(ok for _, ok, _ in fatal)
        return {
            "ok": fatal_ok,
            "fatal_ok": fatal_ok,
            "as_of": str(curr.get("as_of", "")) if curr else None,
            "data_root": str(data_root) if data_root else None,
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
