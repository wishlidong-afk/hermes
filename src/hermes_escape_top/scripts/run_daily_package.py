#!/usr/bin/env python3
"""M4-1: Package-based run-daily operational wrapper.

Replaces the monolith's escape_top_system.main(["run-daily"]) with the
hermes_escape_top package, while writing artifacts in a schema compatible
with the existing downstream consumers (format_escape_top_plain.py,
format_escape_top_html.py, assemble_report.sh).

SHADOW MODE (default): writes to data/shadow/ so the existing daily run
is completely unaffected until you flip run_daily.py (M4-3 human gate).
LIVE MODE (--live): writes to data/ reports/ orders/ replacing monolith output.

Usage:
    python3 scripts/run_daily_package.py              # shadow run today
    python3 scripts/run_daily_package.py --as-of 2026-05-29
    python3 scripts/run_daily_package.py --live       # live mode (M4-3)
    python3 scripts/run_daily_package.py --commit-state  # live + write state.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

SCRIPT_PATH = Path(__file__).resolve()


def _discover_runtime_paths() -> tuple[Path, Path]:
    """Return (runtime_root, package_parent) for both repo and installed layouts.

    package_parent is the directory that CONTAINS the hermes_escape_top package, so
    `python -m hermes_escape_top...` and every subprocess PYTHONPATH resolve no
    matter how deep this file sits. Found by walking UP to the first ancestor that
    holds the package — the old code only checked parents[1], so it resolved
    correctly only from a shallower 'loose' copy (escape-top/scripts/...), which is
    exactly what forced the loose copy to exist and silently drift. Walking up lets
    the package module self-locate from escape-top/hermes_escape_top/scripts/ too,
    so there can be ONE engine. Installed layout returns the same (escape-top,
    escape-top) the loose copy did — behavior-identical, just position-robust."""
    runtime_override = os.environ.get("HERMES_RUNTIME_ROOT")
    for parent in SCRIPT_PATH.parents:
        if (parent / "hermes_escape_top" / "__init__.py").exists():
            if runtime_override:
                return Path(runtime_override).expanduser().resolve(), parent
            # Repo nests the package under src/; keep runtime_root at the repo root.
            if parent.name == "src":
                return parent.parent, parent
            return parent, parent
    # Fallback: original heuristic if the package can't be located by walk-up.
    local_root = SCRIPT_PATH.parents[1]
    if (local_root / "hermes_escape_top").exists():
        return local_root, local_root
    repo_root = SCRIPT_PATH.parents[3] if len(SCRIPT_PATH.parents) > 3 else SCRIPT_PATH.parents[1]
    if (repo_root / "src" / "hermes_escape_top").exists():
        return repo_root, repo_root / "src"
    return local_root, local_root


BASE_DIR, PACKAGE_PARENT = _discover_runtime_paths()
VENV_PYTHON = BASE_DIR.parent.parent.parent.parent / ".hermes" / "hermes-agent" / "venv" / "bin" / "python"


def _interpreter_has_deps(py: str) -> bool:
    """True only if ``py`` can import the science stack the engine needs.

    The hermes-agent venv is a minimal uv environment that may lack
    numpy/pandas; preferring it blindly broke the OHLCV-refresh subprocess
    (ModuleNotFoundError → live run silently fell back to cached data). Only
    use a candidate interpreter that can actually run the pipeline.
    """
    try:
        import subprocess as _sp
        return _sp.run([py, "-c", "import numpy, pandas, scipy"],
                       capture_output=True, timeout=30).returncode == 0
    except Exception:
        return False


# Prefer the agent venv only if it has the deps; otherwise use the interpreter
# already running this script (guaranteed importable — it just imported them).
PYTHON = (
    str(VENV_PYTHON)
    if VENV_PYTHON.exists() and _interpreter_has_deps(str(VENV_PYTHON))
    else sys.executable
)

sys.path.insert(0, str(PACKAGE_PARENT))

from hermes_escape_top import pipeline
from hermes_escape_top.config import load_config, resolve_path
from hermes_escape_top.core.data.store import LocalStore, safe_symbol
from hermes_escape_top.core.safe_io import assert_pipeline_lease
from hermes_escape_top.scripts.backfill_history import all_backfill_symbols, backfill, write_coverage_report
from hermes_escape_top.scripts import refresh_external

TRADE_SYMBOLS = ["MSTR", "FNGU", "SOXL"]


def _subprocess_env() -> Dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(PACKAGE_PARENT) + (os.pathsep + existing if existing else "")
    return env


def _last_bar_dates() -> Dict[str, date]:
    """Last cached OHLCV bar date per gating symbol (QQQ, SPY, trade symbols).
    Shared by as_of selection and the laggard self-heal."""
    out: Dict[str, date] = {}
    try:
        config = load_config()
        store = LocalStore(config)
        for symbol in ["QQQ", "SPY", *TRADE_SYMBOLS]:
            hist = store.load_history(symbol)
            if hist is None or getattr(hist, "empty", True):
                continue
            last = hist.index[-1]
            out[symbol] = last.date() if hasattr(last, "date") else date.fromisoformat(str(last)[:10])
    except Exception as exc:
        print(f"[M4-1] WARNING: last-bar detection failed: {exc!r}")
    return out


def _latest_available_as_of() -> str:
    """Use the latest common cached bar date instead of today's calendar date.

    as_of = the *min* last bar across gating symbols, so the run never scores a
    day for which any symbol is missing its bar. The self-heal step (run right
    after the batch refresh) repairs symbols that lag their peers only because
    of transient batch rate-limiting, so this min reflects genuine availability
    rather than a fetch hiccup."""
    dates = _last_bar_dates()
    if dates:
        return min(dates.values()).isoformat()
    return date.today().isoformat()


# ── Step 1: refresh OHLCV history ────────────────────────────────────────────

def refresh_history(as_of: str, *, _lease: Any) -> None:
    """Fetch the latest OHLCV bar inside the daily transaction lease."""
    print(f"[M4-1] Refreshing OHLCV history up to {as_of}…")
    config = load_config()
    assert_pipeline_lease(
        _lease,
        path=resolve_path(config, "archive_dir") / ".pipeline.lock",
    )
    results = backfill(
        all_backfill_symbols(config),
        start="2018-01-01",
        end=as_of,
        store_dir=resolve_path(config, "history_dir"),
        repair_overlap_days=3,
    )
    write_coverage_report(results, BASE_DIR / "reports" / "N0_history_coverage.md")
    print("[M4-1] History refresh OK.")


def _heal_lagging_symbols(
    end: str,
    *,
    _lease: Any,
    max_passes: int = 2,
    delay_s: float = 3.0,
) -> None:
    """Re-fetch, individually, any symbol whose last cached bar lags its peers.

    A batch backfill can hit Yahoo rate-limiting and return stale data for a
    subset of symbols (2026-06-17: MSTR stuck at 06-15 while QQQ/SPY/SOXL had
    06-16). Because as_of = min(last bar across symbols), one rate-limited
    laggard silently pins the whole run a day behind. A single-symbol re-fetch
    sidesteps the batch contention (verified: MSTR fetched alone returned 06-16).
    Retries are spaced by ``delay_s`` because the throttle is bursty — back-to-
    back calls observed failing while a call seconds later succeeded.

    Conservative by construction: the target is the *max* last bar already
    reached by some peer — never a calendar date — so when all symbols share the
    same date (weekend/holiday, or a genuine vendor gap) there are no laggards
    and this is a no-op. It never fabricates a bar; a laggard that still cannot
    advance after the retries correctly leaves as_of held back. The re-fetch goes
    through the same _sanity_check_download guard, so it cannot bypass the
    cross-wiring protection. Non-fatal: any error leaves the batch result intact.
    """
    try:
        import time

        config = load_config()
        assert_pipeline_lease(
            _lease,
            path=resolve_path(config, "archive_dir") / ".pipeline.lock",
        )
        for attempt in range(max_passes):
            dates = _last_bar_dates()
            if not dates:
                return
            target = max(dates.values())
            laggards = sorted(s for s, d in dates.items() if d < target)
            if not laggards:
                return
            if attempt:
                time.sleep(delay_s)  # let a bursty Yahoo throttle clear before retrying
            print(f"[M4-1] self-heal: {laggards} lag peers' latest bar "
                  f"{target.isoformat()}; re-fetching individually")
            for sym in laggards:
                result = backfill(
                    [sym],
                    start="2018-01-01",
                    end=end,
                    store_dir=resolve_path(config, "history_dir"),
                    repair_overlap_days=3,
                )
                if not result.get(sym) or not result[sym].updated:
                    print(f"[M4-1] self-heal: {sym} did not advance; leaving cached.")
        residual = _last_bar_dates()
        if residual:
            tgt = max(residual.values())
            still = sorted(s for s, d in residual.items() if d < tgt)
            if still:
                print(f"[M4-1] self-heal: {still} still lag {tgt.isoformat()} after "
                      f"{max_passes} passes; as_of holds conservatively.")
    except Exception as exc:
        print(f"[M4-1] WARNING: self-heal step failed ({exc!r}); using batch result.")


# ── Step 1a: refresh ledgered external sources ───────────────────────────────

def refresh_external_sources() -> list[dict]:
    """Refresh ledgered external feeds before the broad legacy soft refresh.

    Non-fatal by design: ExternalSourceRunner validates and atomically promotes
    good data; on failure the cached CSV remains authoritative and the ledger
    records the error for health/WebUI. A transient FRED outage must not abort the
    daily scoring run.
    """
    source_ids = tuple(refresh_external.SOURCE_IDS)
    print(f"[M4-1a] Refreshing external source ledger sources ({', '.join(source_ids)})…")
    runs: list[dict] = []
    for source_id in source_ids:
        try:
            run = refresh_external.refresh_source(source_id)
            runs.append(run)
            print(
                f"[M4-1a] {source_id} external refresh {run.get('status')} "
                f"latest={run.get('latest_promoted_as_of') or run.get('latest_normalized_as_of')}"
            )
        except Exception as exc:
            run = {
                "source_id": source_id,
                "status": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
            }
            runs.append(run)
            print(f"[M4-1a] WARNING: {source_id} external refresh failed ({exc!r}); keeping cached data.")
    return runs


# ── Step 1b: refresh legacy slow soft data (non-runner sources) ───────────────

def refresh_soft_data() -> None:
    """Refresh slow-moving soft-data CSVs not yet owned by ExternalSourceRunner.

    Non-fatal: a failure here does not block scoring; the scoring engine will
    use whatever cached soft data exists and report staleness via health.py.
    AAII is excluded (no auto-parseable endpoint; requires manual download or
    Claude-in-Chrome session per prior procedure). NAAIM is refreshed earlier
    through ExternalSourceRunner, so this legacy block must not write it again.
    """
    print("[M4-1b] Refreshing legacy soft data sources (FRED risk signals + COT)…")
    result = subprocess.run(
        [PYTHON, "-m", "hermes_escape_top.scripts.backfill_soft_data",
         "--only", "fred"],
        cwd=str(BASE_DIR),
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print("[M4-1b] WARNING: FRED net-liquidity refresh failed; proceeding with cached data.")
        print(result.stderr[-300:] if result.stderr else "")
    else:
        print("[M4-1b] FRED net-liquidity OK.")

    result2 = subprocess.run(
        [PYTHON, "-m", "hermes_escape_top.scripts.backfill_soft_data",
         "--only", "fred_risk"],
        cwd=str(BASE_DIR),
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result2.returncode != 0:
        print("[M4-1b] WARNING: FRED risk signals refresh failed; proceeding with cached data.")
    else:
        print("[M4-1b] FRED risk signals OK.")

    result4 = subprocess.run(
        [PYTHON, "-m", "hermes_escape_top.scripts.backfill_soft_data",
         "--only", "cot"],
        cwd=str(BASE_DIR),
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result4.returncode != 0:
        print("[M4-1b] WARNING: COT NQ refresh failed (weekly — normal if CFTC site is down); continuing.")
    else:
        print("[M4-1b] COT NQ OK.")

    result5 = subprocess.run(
        [PYTHON, "-m", "hermes_escape_top.scripts.backfill_occ_pcr",
         "--weeks", "3"],
        cwd=str(BASE_DIR),
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result5.returncode != 0:
        print("[M4-1b] WARNING: OCC PCR refresh failed (weekly Friday report); continuing.")
    else:
        print("[M4-1b] OCC equity PCR OK.")

    result6 = subprocess.run(
        [PYTHON, "-m", "hermes_escape_top.scripts.refresh_cboe_daily_pcr"],
        cwd=str(BASE_DIR),
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result6.returncode != 0:
        print("[M4-1b] WARNING: CBOE daily PCR refresh failed/rejected (cache kept); continuing.")
        print((result6.stdout or result6.stderr or "")[-200:])
    else:
        print("[M4-1b] CBOE daily PCR OK.")

    result7 = subprocess.run(
        [PYTHON, "-m", "hermes_escape_top.scripts.refresh_aaii_public"],
        cwd=str(BASE_DIR),
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result7.returncode != 0:
        print("[M4-1b] WARNING: AAII public probe failed (weekly — member-session fallback per runbook); continuing.")
    else:
        print("[M4-1b] AAII public probe OK.")

    # BTC funding/DVOL (data_btc_funding defaults ON): its own script was never
    # wired here, so the source drifted 13d stale (2026-06-02) while still being
    # scored. Deribit/OKX, stdlib-only, non-fatal like the rest.
    result8 = subprocess.run(
        [PYTHON, "-m", "hermes_escape_top.scripts.backfill_crypto_micro"],
        cwd=str(BASE_DIR),
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result8.returncode != 0:
        print("[M4-1b] WARNING: BTC funding/DVOL refresh failed (Deribit/OKX); continuing.")
    else:
        print("[M4-1b] BTC funding/DVOL OK.")


# ── Step 2: run the package score pipeline ────────────────────────────────────

def run_score_pipeline(
    as_of: str,
    shadow: bool = True,
    run_type: str = "manual_rerun",
    *,
    _lease: Any,
) -> Dict[str, Any]:
    print(f"[M4-1] Running score_pipeline({as_of}, shadow={shadow}, run_type={run_type})…")
    payload = pipeline._score_pipeline_locked(
        as_of,
        shadow=shadow,
        run_type=run_type,
        _lease=_lease,
    )
    print(f"[M4-1] score_pipeline OK. Schema: {payload.get('schema_version')}")
    return payload


# ── Step 3: translate to monolith-compatible schema ──────────────────────────

def _pct(v: Optional[float]) -> Optional[int]:
    if v is None:
        return None
    return int(round(float(v) * 100))


def _route_label(route: Dict[str, Any]) -> str:
    step = str(route.get("defcon") or route.get("protocol_step") or "").upper()
    destination = route.get("destination") or route.get("destination_symbol")
    if step == "DEFCON1" or destination == "BOXX":
        return "☢️ 宏观核爆：资金撤入 BOXX/现金防空洞"
    if step == "DEFCON2" or destination == "BRK.B":
        return "内部破位/高低切：资金撤入 BRK.B"
    if step == "DEFCON3":
        return "降维防守：资金切入对应 1 倍标的"
    return "路由未触发"


def _route_weights(route: Dict[str, Any]) -> Dict[str, float]:
    raw = route.get("weights")
    if isinstance(raw, dict) and raw:
        return {str(k): float(v) for k, v in raw.items()}
    destination = route.get("destination") or route.get("destination_symbol")
    return {str(destination): 1.0} if destination else {}


def _route_text(route: Dict[str, Any]) -> str:
    weights = _route_weights(route)
    if not weights:
        return "斩仓资金路由：未触发。"
    parts = "，".join(f"{sym} {weight:.0%}" for sym, weight in weights.items())
    return f"斩仓资金路由：{_route_label(route)}。目的地：{parts}。"


def _monolith_result(sym: str, pkg_scores: Dict[str, Any], pkg_routing: Dict[str, Any],
                     pkg_sizing: Dict[str, Any]) -> Dict[str, Any]:
    """Build the per-symbol result dict in the monolith's schema."""
    s = pkg_scores.get(sym, {})
    r = pkg_routing.get(sym, {}) or {}

    sell_frac = s.get("sell_fraction", 0.0)
    sell_pct = _pct(sell_frac) or 0
    status = s.get("status", "HOLD")
    total = round(float(s.get("final_score") or s.get("total_score") or 0), 2)
    raw = round(float(s.get("raw_total") or total), 2)
    missing_w = round(float(s.get("missing_weight") or s.get("missing_score_weight") or 0), 2)
    effective = round(100.0 - missing_w, 2)
    hard_hits = list(s.get("hard_valve_hits") or [])

    # Module scores & items
    modules: Dict[str, Any] = {}
    for mod in "ABCD":
        factors = s.get("factor_scores", {}).get(mod, [])
        mod_score = round(sum(float(f.get("score", 0)) for f in factors), 2)
        items = []
        for f in factors:
            pts = float(f.get("score", 0))
            if pts > 0:
                items.append({
                    "label": f.get("factor_id", f.get("name", "")),
                    "points": pts,
                    "reason": f.get("explain", ""),
                    "flag": "red" if pts >= 3 else "yellow",
                })
        modules[mod] = {"score": mod_score, "items": items, "missing": []}

    # Module scores from ScoreResult.module_scores (more accurate)
    ms = s.get("module_scores", {})
    for mod in "ABCD":
        if mod in ms:
            modules.setdefault(mod, {})["score"] = ms[mod]

    # Capital route
    dest = r.get("destination") or r.get("destination_symbol")
    route_weights = _route_weights(r)
    capital_route = {
        "applies": dest is not None and dest not in ("", "-"),
        "destination": dest,
        "destination_symbol": dest,
        "weights": route_weights,
        "label": _route_label(r) if dest else "",
        "protocol_step": r.get("defcon") or r.get("protocol_step", "NO_ROUTE"),
        "sell_proceeds_pct": sell_pct,
        "status": status,
        "reason": r.get("reason", ""),
        "hard_ids": hard_hits,
        "hard_triggered": bool(hard_hits),
    }

    return {
        "symbol": sym,
        "status": status,
        "sell_pct": sell_pct,
        "total_score": total,
        "raw_score": raw,
        "effective_max_score": effective,
        "calibrated_score": total,
        "missing_score_weight": missing_w,
        "missing_fields": list(s.get("explain", []))[:5],
        "hard_trigger": {
            "triggered": bool(hard_hits),
            "ids": hard_hits,
            "reason": "; ".join(hard_hits),
        },
        "modules": modules,
        "capital_route": capital_route,
        "flag_counts": {
            "red": sum(1 for f in sum((m.get("items", []) for m in modules.values()), []) if f.get("flag") == "red"),
        },
    }


def _ibkr_position_map(ibkr: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    positions: Dict[str, Dict[str, Any]] = {}
    for row in ibkr.get("trade_symbols", []) or []:
        symbol = str(row.get("symbol", ""))
        if symbol:
            positions[symbol] = row
    return positions


def _build_orders_preview(results: Dict[str, Any], ibkr: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ibkr = ibkr or {}
    positions = _ibkr_position_map(ibkr)
    out: Dict[str, Any] = {}
    for sym in TRADE_SYMBOLS:
        r = results.get(sym, {})
        sell_pct = int(r.get("sell_pct") or 0)
        status = r.get("status", "HOLD")
        route = r.get("capital_route", {})
        if sell_pct > 0:
            position = positions.get(sym, {})
            actual_shares = abs(float(position.get("actual_shares") or 0.0))
            actual_notional = abs(float(position.get("actual_notional") or 0.0))
            qty = actual_shares * sell_pct / 100.0 if actual_shares else None
            notional = actual_notional * sell_pct / 100.0 if actual_notional else None
            action = "SELL_PREVIEW" if qty is not None else "SIGNAL_ONLY"
            instruction = (
                f"按当前 IBKR 快照预览卖出 {sym} {qty:.2f} 股（约 ${notional:,.0f}），"
                f"占当前持仓 {sell_pct}%。未提交真实订单。"
                if qty is not None
                else f"卖出当前 {sym} 持仓的 {sell_pct}%；未读取到可用 IBKR 股数，未提交真实订单。"
            )
            out[sym] = {
                "action": action,
                "quantity": round(qty, 4) if qty is not None else None,
                "estimated_notional": round(notional, 2) if notional is not None else None,
                "sell_pct": sell_pct,
                "reason": status,
                "capital_route": route,
                "route_instruction": _route_text(route) if route.get("applies") else "斩仓资金路由：未触发。",
                "instruction": instruction,
                "not_submitted": True,
                "ibkr_source": ibkr.get("source", "unavailable"),
                "sizing_engine": "optimize_targets_v1",
            }
        else:
            out[sym] = {
                "action": "NONE",
                "sell_pct": 0,
                "reason": status,
                "not_submitted": True,
            }
    return out


def _build_action_plan(results: Dict[str, Any], orders: Dict[str, Any]) -> Dict[str, Any]:
    directives = []
    for sym in TRADE_SYMBOLS:
        r = results.get(sym, {})
        o = orders.get(sym, {})
        sell = int(r.get("sell_pct") or 0)
        status = r.get("status", "HOLD")
        hard = r.get("hard_trigger", {})
        # directive: map status → monolith action verb (what format scripts display)
        directive_map = {
            "EXIT": "EXIT_100%", "DEFENSIVE_EXIT": "DEFENSIVE_EXIT",
            "REDUCE": "REDUCE_60%", "TRIM": "TRIM_35%",
            "WATCH": "WATCH", "HOLD": "HOLD",
        }
        directive = directive_map.get(status, status)
        if hard.get("triggered"):
            directive = "HARD_EXIT_100%"
        directives.append({
            "symbol": sym,
            "directive": directive,
            "status": status,
            "sell_pct": sell,
            "order_action": o.get("action", "NONE"),
            "score": r.get("total_score", 0),
            "missing_weight": r.get("missing_score_weight", 0),
            "hard_triggered": hard.get("triggered", False),
            "top_reasons": [item.get("reason", "") for item in
                            sum((r.get("modules", {}).get(m, {}).get("items", []) for m in "ABCD"), [])
                            if float(item.get("points", 0)) >= 2][:3],
            "order_instruction": o.get("instruction", ""),
        })
    n_sell = sum(1 for d in directives if d["sell_pct"] > 0)
    summary = (f"今日 {n_sell}/3 标的有减仓信号" if n_sell else "今日三标的均无减仓信号") + "（包引擎 optimize_targets_v1）"
    return {
        "schema_version": "escape-top-action-plan-package-v1",
        "summary": summary,
        "account_source": "package_pipeline",
        "directives": directives,
    }


def _build_reentry_plan(pkg_reentry: Dict[str, Any]) -> Dict[str, Any]:
    """Map package reentry output to monolith reentry_plan schema."""
    plans: Dict[str, Any] = {}
    for sym in TRADE_SYMBOLS:
        r = pkg_reentry.get(sym, {}) or {}
        action = str(r.get("action", "WAIT"))
        directive = "PHASE0_LOCKED"
        if action in ("HOLD", "WATCH"):
            directive = "PHASE0_LOCKED"
        elif action == "REDUCE":
            directive = "LOCKED_SELL_RISK_ACTIVE"
        else:
            directive = action
        # Real lock states from reentry[sym].locks (added 2026-06-12); the old
        # hardcoded False trio made the daily report lie about lock progress.
        locks = r.get("locks") or {}
        def _passed(name: str) -> bool:
            return bool((locks.get(name) or {}).get("passed"))
        plans[sym] = {
            "phase0_unlocked": all(_passed(k) for k in ("valve_or_sell", "time", "score", "structure")) if locks else False,
            "phase0_checks": {
                "time_lock": _passed("time"),
                "emotion_lock": _passed("score"),
                "structure_lock": _passed("structure"),
            },
            "directive": directive,
            "action": "WAIT",
            "cash_pool_action_pct": 0,
            "reason": str(r.get("reason", "package reentry pending")),
            "t1": {"triggered": False, "stop_loss": None},
            "t2": {"triggered": False, "trailing_stop": None},
            "t3": {"triggered": False, "reserve_hold": False},
        }
    return {
        "schema_version": "escape-top-reentry-v1.0",
        "summary": "包引擎 reentry_plan（package optimize_targets_v1）",
        "macro_new_252d_high": False,
        "plans": plans,
    }


def _state_path() -> Path:
    return BASE_DIR / "state.json"


def _load_state() -> Dict[str, Any]:
    path = _state_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("symbols", {})
                return data
        except Exception:
            pass
    return {"schema_version": "escape-top-state-v1", "updated_at": None, "symbols": {}}


def _business_days_between(start: Optional[str], end: str) -> int:
    if not start:
        return 0
    try:
        d0 = date.fromisoformat(str(start)[:10])
        d1 = date.fromisoformat(str(end)[:10])
    except Exception:
        return 0
    if d1 <= d0:
        return 0
    days = 0
    cur = d0
    while cur < d1:
        cur = date.fromordinal(cur.toordinal() + 1)
        if cur.weekday() < 5:
            days += 1
    return days


def _build_state_suggestions(results: Dict[str, Any], as_of: str) -> Dict[str, Any]:
    current = _load_state()
    current_symbols = current.get("symbols", {}) if isinstance(current.get("symbols"), dict) else {}
    suggestions: Dict[str, Any] = {}
    cooldown_days = 11
    for sym in TRADE_SYMBOLS:
        r = results.get(sym, {})
        status = str(r.get("status", "HOLD"))
        sell_pct = int(r.get("sell_pct") or 0)
        prev = current_symbols.get(sym, {}) if isinstance(current_symbols.get(sym), dict) else {}
        current_state = str(prev.get("state", "HOLDING"))

        if sell_pct > 0:
            next_state = "COOLDOWN"
            remaining = cooldown_days if current_state != "COOLDOWN" else int(prev.get("cooldown_days_left", cooldown_days))
            reason = f"{status} sell signal; enter/keep 11-trading-day jail"
        elif current_state == "COOLDOWN":
            elapsed = _business_days_between(prev.get("last_exit_date"), as_of)
            remaining = max(0, cooldown_days - elapsed)
            next_state = "COOLDOWN" if remaining > 0 else "WATCHING"
            reason = "cooldown active" if remaining > 0 else "cooldown complete; wait for reentry audit"
        elif current_state in {"WATCH", "WATCHING", "EXITED"}:
            next_state = "WATCHING"
            remaining = 0
            reason = "no sell signal; keep watching for reentry audit"
        else:
            next_state = "HOLDING"
            remaining = 0
            reason = "no sell signal"

        suggestions[sym] = {
            "current_state": current_state,
            "next_state": next_state,
            "reason": reason,
            "last_score": r.get("total_score", 0),
            "last_action": status,
            "cooldown_days_left": remaining,
            "sell_pct": sell_pct,
            "hard_triggered": bool(r.get("hard_trigger", {}).get("triggered")),
        }
    return {"symbols": suggestions}


def commit_state(translated: Dict[str, Any], as_of: str) -> Path:
    state = _load_state()
    state.setdefault("symbols", {})
    symbols = state["symbols"] if isinstance(state.get("symbols"), dict) else {}
    suggestions = translated.get("state_suggestions", {}).get("symbols", {})
    for sym in TRADE_SYMBOLS:
        suggestion = suggestions.get(sym, {})
        prev = symbols.get(sym, {}) if isinstance(symbols.get(sym), dict) else {}
        next_state = suggestion.get("next_state", prev.get("state", "HOLDING"))
        updated = dict(prev)
        updated.update({
            "state": next_state,
            "last_score": suggestion.get("last_score", prev.get("last_score")),
            "last_action": suggestion.get("last_action", prev.get("last_action")),
            "last_action_date": as_of,
            "cooldown_days_left": suggestion.get("cooldown_days_left", 0),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        if next_state == "COOLDOWN" and (prev.get("state") != "COOLDOWN" or not prev.get("last_exit_date")):
            updated["last_exit_date"] = as_of
        updated.setdefault("reentry", {})
        symbols[sym] = updated
    state["symbols"] = symbols
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def translate(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Translate package score_pipeline payload → monolith daily_score_precheck schema."""
    as_of = str(payload.get("as_of", ""))[:10]
    pkg_scores = payload.get("scores", {})
    pkg_routing = payload.get("routing", {})
    pkg_sizing = payload.get("sizing", {})
    pkg_reentry_raw = payload.get("reentry", {})

    results: Dict[str, Any] = {}
    for sym in TRADE_SYMBOLS:
        if sym in pkg_scores:
            results[sym] = _monolith_result(sym, pkg_scores, pkg_routing, pkg_sizing)

    orders = _build_orders_preview(results, payload.get("ibkr", {}))
    action_plan = _build_action_plan(results, orders)
    reentry_plan = _build_reentry_plan(pkg_reentry_raw)
    regime = payload.get("regime", {})
    dq = payload.get("data_quality", {})

    # Build dataset stub for format_escape_top_plain.py compatibility
    dataset: Dict[str, Any] = {
        "as_of": as_of,
        "data_confidence": "Medium",
        "market": {
            "QQQ": {
                "close": regime.get("inputs", {}).get("QQQ.close"),
                "ema20": regime.get("inputs", {}).get("QQQ.ema20"),
                "ma200": regime.get("inputs", {}).get("QQQ.ma200"),
            },
            "VIX": {"close": regime.get("inputs", {}).get("^VIX.close")},
        },
        "symbols": {sym: {"status": results.get(sym, {}).get("status")} for sym in TRADE_SYMBOLS},
    }

    # Risk / confidence info from sizing
    risk_summary = payload.get("portfolio_risk", {})
    confidence_mode = None
    for sym_size in pkg_sizing.values():
        if isinstance(sym_size, dict) and "optimizer_confidence" in sym_size:
            confidence_mode = f"{sym_size['optimizer_confidence']:.3f}"
            break

    return {
        "schema_version": "escape-top-score-v2.5-package",
        "as_of": as_of,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_confidence": f"Package({confidence_mode})" if confidence_mode else "Package",
        "data_quality_profile": dq,
        "dataset": dataset,
        "results": results,
        "portfolio_risk_shadow": risk_summary,
        "state_suggestions": _build_state_suggestions(results, as_of),
        "orders_preview": orders,
        "action_plan": action_plan,
        "reentry_plan": reentry_plan,
        "package_payload": {
            "schema_version": payload.get("schema_version"),
            "sizing": pkg_sizing,
            "mirror": payload.get("mirror"),
            "ibkr": payload.get("ibkr"),
            "posterior_pnl": payload.get("posterior_pnl"),
            "audit_log_path": payload.get("audit_log_path"),
            "signal_journal_path": payload.get("signal_journal_path"),
        },
    }


# ── Step 4: write artifacts ───────────────────────────────────────────────────

def _artifact_root() -> Path:
    """BASE_DIR unless HERMES_DATA_DIR re-roots runtime outputs (T8: keep
    runs from dirtying the git working tree)."""
    override = os.environ.get("HERMES_DATA_DIR")
    return Path(override).expanduser() if override else BASE_DIR


def write_artifacts(translated: Dict[str, Any], orders: Dict[str, Any],
                    as_of: str, shadow: bool = True) -> Dict[str, Path]:
    root = _artifact_root()
    if shadow:
        data_dir = root / "data" / "shadow"
        report_dir = root / "reports" / "shadow"
        order_dir = root / "orders" / "shadow"
    else:
        data_dir = root / "data"
        report_dir = root / "reports"
        order_dir = root / "orders"

    for d in (data_dir, report_dir, order_dir):
        d.mkdir(parents=True, exist_ok=True)

    score_path = data_dir / f"daily_score_precheck_{as_of}.json"
    order_path = order_dir / f"orders_preview_{as_of}.json"
    report_path = report_dir / f"daily_report_{as_of}.md"

    score_path.write_text(json.dumps(translated, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    order_path.write_text(json.dumps(orders, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(_render_markdown(translated, as_of), encoding="utf-8")

    mode = "shadow" if shadow else "LIVE"
    print(f"[M4-1] [{mode}] {score_path}")
    print(f"[M4-1] [{mode}] {order_path}")
    print(f"[M4-1] [{mode}] {report_path}")
    return {"score": score_path, "order": order_path, "report": report_path}


def _render_markdown(t: Dict[str, Any], as_of: str) -> str:
    lines = [f"# Hermes 逃顶日报（package engine） — {as_of}", "",
             f"引擎: `hermes_escape_top` (optimize_targets_v1)",
             f"置信度: {t.get('data_confidence')}",
             ""]
    lines += ["## 今日指令卡", "",
              "| 标的 | 状态 | 卖出% | 硬触发 | 订单 | 路由 |",
              "|---|---|---:|---|---|---|"]
    for sym in TRADE_SYMBOLS:
        r = t.get("results", {}).get(sym, {})
        o = t.get("orders_preview", {}).get(sym, {})
        ht = r.get("hard_trigger", {})
        route = o.get("route_instruction", "—")
        lines.append(f"| {sym} | {r.get('status','?')} | {r.get('sell_pct',0)}% | {'⚠️ '+','.join(ht.get('ids',[])) if ht.get('triggered') else '—'} | {o.get('action','—')} | {route} |")
    lines += ["", "## 分数拆解", "",
              "| 标的 | Total | Raw | Missing | A | B | C | D |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for sym in TRADE_SYMBOLS:
        r = t.get("results", {}).get(sym, {})
        ms = r.get("modules", {})
        scores = " | ".join(str(round(ms.get(m, {}).get("score", 0), 1)) for m in "ABCD")
        lines.append(f"| {sym} | {r.get('total_score',0)} | {r.get('raw_score',0)} | {r.get('missing_score_weight',0)} | {scores} |")
    lines += ["", "---", f"*Generated by run_daily_package.py at {t.get('generated_at', '?')}*", ""]
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def _csv_last_date(path: Path) -> Optional[str]:
    """First column of the last non-empty row, or None."""
    try:
        last = None
        with path.open() as fh:
            for line in fh:
                if line.strip():
                    last = line
        if last is None:
            return None
        first = last.split(",", 1)[0].strip()
        return first if first and first[0].isdigit() else None
    except OSError:
        return None


def _history_integrity_scan(config) -> list:
    """Defense-in-depth after refresh: residual cross-wired bars abort a live
    run — a stale decision plus an alert beats scoring on garbage
    (2026-06-12: 13 files got other tickers' prices, all three symbols
    flipped to fake EXIT). ^vol indices get a wider band (VIX can double
    legitimately). A legit raw-price split can trip this — rare, and a human
    look is exactly what that case deserves.
    """
    import csv as _csv
    from hermes_escape_top.config import resolve_path

    offenders = []
    history_dir = resolve_path(config, "history_dir")
    for symbol in _integrity_watch_symbols(config):
        path = history_dir / f"{safe_symbol(symbol)}.csv"
        if not path.exists():
            continue
        limit = 3.0 if symbol.startswith("^") else 1.5
        try:
            rows = list(_csv.reader(path.open()))[-12:]
        except OSError:
            continue
        if rows:
            latest = rows[-1]
            try:
                latest_close = float(latest[4])
                latest_valid = latest_close > 0
            except (ValueError, IndexError):
                latest_valid = False
            if not latest_valid:
                latest_date = latest[0] if latest else "unknown"
                offenders.append(f"{path.name} latest row {latest_date} missing close")
        closes = []
        for r in rows:
            try:
                closes.append((r[0], float(r[4])))
            except (ValueError, IndexError):
                continue
        for (d1, c1), (d2, c2) in zip(closes, closes[1:]):
            if c1 > 0 and not (1.0 / limit <= c2 / c1 <= limit):
                offenders.append(f"{path.name} {d1} {c1:.2f} -> {d2} {c2:.2f}")
    return offenders


def _integrity_watch_symbols(config) -> list:
    symbols = set((config.get("symbols") or {}).keys())
    symbols.update(config.get("market_symbols") or [])
    for values in (config.get("radars") or {}).values():
        symbols.update(values)
    symbols.update({
        "QQQ",
        "SOXX",
        "SMH",
        "SPY",
        "^VIX",
        "^VIX3M",
        "^SOX",
        "BTC-USD",
        "BOXX",
        "DBMF",
        "GLD",
        "IAU",
        "BRK.B",
        "BIL",
        "SHV",
    })
    return sorted(str(symbol) for symbol in symbols if symbol)

def _preflight_report(shadow: bool, as_of: str) -> None:
    """[T5] One-screen "can today's output be trusted" check before scoring.

    Informational, except the never-order red line: a live run aborts when
    ibkr.readonly is not true.
    """
    print(f"[preflight] mode={'shadow' if shadow else 'LIVE'} as_of={as_of}")
    try:
        config = load_config()
    except Exception as exc:
        print(f"[preflight] WARNING: config load failed: {exc!r}")
        return
    readonly = (config.get("ibkr") or {}).get("readonly", True)
    if readonly is not True and not shadow:
        print("[preflight] CRITICAL: ibkr.readonly is not true — never-order red line. Aborting.")
        sys.exit(2)
    print(f"[preflight] ibkr.readonly={str(readonly).lower()}")

    from hermes_escape_top.config import resolve_path

    last_bar = _csv_last_date(resolve_path(config, "history_dir") / "QQQ.csv")
    lag_note = ""
    if last_bar:
        try:
            from hermes_escape_top.web.refresh import _completed_trading_days_after
            lag_note = f" ({_completed_trading_days_after(last_bar)} trading days behind)"
        except Exception:
            pass
    print(f"[preflight] OHLCV QQQ last bar: {last_bar or 'MISSING'}{lag_note}")

    soft_dir = resolve_path(config, "soft_history_dir")
    if soft_dir.exists():
        today = date.fromisoformat(as_of)
        features = config.get("features", {})
        for csv_path in sorted(soft_dir.glob("*.csv")):
            d = _csv_last_date(csv_path)
            age = (today - date.fromisoformat(d)).days if d else None
            if features.get(f"data_{csv_path.stem}") is False:
                # Disabled candidate factor — not scored, so its staleness is moot.
                # Don't flag STALE (the C "假陈旧" false alarm that read as a problem).
                desc = "OFF (已禁用，陈旧无妨)"
            elif age is None:
                desc = "EMPTY"
            elif age < 0:
                desc = "newer than as_of"
            else:
                desc = f"age={age}d" + ("  <-- STALE" if age > 10 else "")
            print(f"[preflight]   soft {csv_path.stem:<24} {d or '-':<12} {desc}")

    archive_dir = resolve_path(config, "archive_dir")
    writable = archive_dir.exists() and os.access(archive_dir, os.W_OK)
    print(f"[preflight] archive_dir writable: {'OK' if writable else 'NOT WRITABLE'}")


def _audit_prev_entry(audit_path: Path, before_as_of: str) -> Optional[Dict[str, Any]]:
    """Last audit entry with as_of < before_as_of.

    Reads only the file tail: audit_log.jsonl is hundreds of MB and one
    payload line is ~1MB — never parse it front to back.
    """
    if not audit_path.exists():
        return None
    chunk = 16 * 1024 * 1024
    with audit_path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - chunk))
        data = fh.read()
    lines = data.split(b"\n")
    if size > chunk:
        lines = lines[1:]  # drop the likely-partial first line
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if str(entry.get("as_of", "")) < before_as_of:
            return entry
    return None


def _factor_movers(old_s: Dict[str, Any], new_s: Dict[str, Any], top_n: int = 5):
    """Top factors by |score delta| between two score dicts."""
    def fmap(s: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for factors in (s.get("factor_scores") or {}).values():
            for f in factors or []:
                out[f.get("factor_id")] = (float(f.get("score") or 0.0), f.get("explain") or "")
        return out

    old_f, new_f = fmap(old_s), fmap(new_s)
    moves = []
    for fid in set(old_f) | set(new_f):
        delta = new_f.get(fid, (0.0, ""))[0] - old_f.get(fid, (0.0, ""))[0]
        if abs(delta) > 1e-9:
            moves.append((fid, delta, (new_f.get(fid) or old_f.get(fid))[1]))
    moves.sort(key=lambda m: -abs(m[1]))
    return moves[:top_n]


def _shallow_diff(old: Any, new: Any) -> list:
    if not isinstance(old, dict) or not isinstance(new, dict):
        return []
    changes = []
    for k in sorted(set(old) | set(new)):
        ov, nv = old.get(k), new.get(k)
        if ov == nv:
            continue
        if isinstance(ov, (dict, list)) or isinstance(nv, (dict, list)):
            changes.append(f"{k}: changed")
        else:
            changes.append(f"{k}: {ov} -> {nv}")
    return changes


def _post_run_diff(payload: Dict[str, Any], as_of: str, shadow: bool) -> None:
    """[T6] Explain what changed vs the previous audit entry.

    Answers "why is today's advice different from yesterday's" — compact
    stdout summary + full markdown artifact next to the daily report.
    """
    try:
        config = load_config()
        from hermes_escape_top.config import resolve_path
        audit_path = resolve_path(config, "archive_dir") / "audit_log.jsonl"
        prev_entry = _audit_prev_entry(audit_path, as_of)
    except Exception as exc:
        print(f"[M4-diff] WARNING: diff unavailable: {exc!r}")
        return
    if not prev_entry:
        print("[M4-diff] no earlier audit entry — diff skipped")
        return
    prev = prev_entry.get("payload") or {}
    prev_as_of = prev_entry.get("as_of")
    print(f"[M4-diff] vs previous audit entry {prev_as_of}:")
    md = [f"# Daily diff {prev_as_of} -> {as_of}", ""]

    for sym in TRADE_SYMBOLS:
        new_s = (payload.get("scores") or {}).get(sym) or {}
        old_s = (prev.get("scores") or {}).get(sym) or {}
        if not new_s or not old_s:
            continue
        def _r(v: Any) -> Any:
            return round(float(v), 1) if isinstance(v, (int, float)) else v

        headline = (f"{sym}: {old_s.get('status')} -> {new_s.get('status')}, "
                    f"score {_r(old_s.get('final_score'))} -> {_r(new_s.get('final_score'))}, "
                    f"sell {_r(old_s.get('sell_fraction'))} -> {_r(new_s.get('sell_fraction'))}")
        print(f"[M4-diff]   {headline}")
        md += [f"## {sym}", "", f"- {headline}"]

        mod_old = old_s.get("module_scores") or {}
        mod_new = new_s.get("module_scores") or {}
        mods = ", ".join(f"{m} {mod_old.get(m, 0)} -> {mod_new.get(m, 0)}"
                         for m in sorted(set(mod_old) | set(mod_new))
                         if mod_old.get(m) != mod_new.get(m))
        if mods:
            md.append(f"- modules: {mods}")

        valves_old = set(old_s.get("hard_valve_hits") or [])
        valves_new = set(new_s.get("hard_valve_hits") or [])
        if valves_old != valves_new:
            valve_line = f"valves +{sorted(valves_new - valves_old)} -{sorted(valves_old - valves_new)}"
            print(f"[M4-diff]     {valve_line}")
            md.append(f"- {valve_line}")

        movers = _factor_movers(old_s, new_s)
        if movers:
            md.append("- top factor movers:")
            for fid, delta, explain in movers:
                md.append(f"  - {fid}: {delta:+.1f} — {explain}")

        for block in ("routing", "reentry"):
            changes = _shallow_diff((prev.get(block) or {}).get(sym),
                                    (payload.get(block) or {}).get(sym))
            if changes:
                print(f"[M4-diff]     {block}: " + "; ".join(changes[:3]))
                md.append(f"- {block}: " + "; ".join(changes))
        md.append("")

    out_dir = _artifact_root() / "reports" / ("shadow" if shadow else "")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"daily_diff_{as_of}.md"
    out_path.write_text("\n".join(md))
    print(f"[M4-diff] written: {out_path}")


def _refresh_next5_unlock() -> None:
    """Refresh the NEXT-5 meta-model unlock progress (non-fatal). Keeps the unlock
    status file current as 20-day labels accumulate, so the gate isn't tracked off
    a stale snapshot."""
    result = subprocess.run(
        [PYTHON, "-m", "hermes_escape_top.scripts.check_next5_unlock"],
        cwd=str(BASE_DIR), env=_subprocess_env(), capture_output=True, text=True, timeout=60,
    )
    for line in (result.stdout or result.stderr or "").strip().splitlines()[-3:]:
        print(f"[NEXT5] {line}")


def _refreeze_manifest() -> None:
    """Re-freeze the data manifest to the just-refreshed history (non-fatal).

    The daily refresh advances history CSV hashes; the frozen manifest then reads
    as DRIFT (health CRITICAL) until something re-freezes it. The 8766 button used
    to be the only path, so the alert recurred every day after a refresh. Called
    only after the integrity scan passes, so it never blesses corrupt bars.
    """
    try:
        from hermes_escape_top.web.refresh import force_refresh_manifest
        res = force_refresh_manifest(load_config())
        print(f"[manifest] re-frozen to refreshed history: {res.get('status', res)}")
    except Exception as exc:
        print(f"[manifest] WARNING: re-freeze failed ({exc!r}); manifest may show DRIFT until manual refresh.")


def _write_run_receipt(
    as_of: str,
    run_type: str,
    steps_ok: bool = True,
    step_error: str = "",
    *,
    status: Optional[str] = None,
    started_at: Optional[str] = None,
    failed_step: str = "",
) -> Optional[Dict[str, Any]]:
    """End-of-run self-attestation written by the scheduled daily run.

    Called LAST, after every required step (incl. state commit). ``steps_ok=False``
    forces a red receipt so a run that failed a required step can never certify
    green just because the data-state self-checks happen to pass.

    Stamps WHEN the official run completed plus a few end-state invariants, so the
    dashboard can show a positive 'ran today, self-checked green' — the one signal
    health.py cannot infer from data state (a job that silently never fires leaves
    data that may still look fresh; a stale-orchestration copy that skips a step
    leaves the receipt's own check failing). Recomputed independently of the step
    calls, so it audits the real end state, not a step's self-report. Non-fatal.
    """
    path: Optional[Path] = None
    try:
        from hermes_escape_top.config import resolve_path
        config = load_config()
        path = resolve_path(config, "archive_dir") / "run_receipt.json"
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        started_at = started_at or now
        requested_status = status or ("OK" if steps_ok else "FAILED")
        if requested_status == "RUNNING":
            receipt = {
                "status": "RUNNING",
                "run_at": now,
                "started_at": started_at,
                "finished_at": None,
                "as_of": str(as_of),
                "run_type": run_type,
                "ok": False,
                "failed_step": "",
                "error": "",
                "checks": [],
            }
            _atomic_write_json(path, receipt)
            print(f"[receipt] RUNNING -> {path.name}")
            return receipt

        checks = []
        if requested_status == "FAILED" or not steps_ok:
            checks.append({"name": "run_steps", "ok": False,
                           "detail": step_error or "a required step failed before the receipt"})
        dates = _last_bar_dates()
        if dates:
            latest_bar = max(dates.values()).isoformat()
            laggards = sorted(s for s, d in dates.items() if d.isoformat() < latest_bar)
            checks.append({
                "name": "as_of_latest",
                "ok": not laggards,
                "detail": f"as_of={as_of} · 最新K线={latest_bar}"
                          + (f" · 掉队 {laggards}" if laggards else " · 全标的齐平"),
            })
        try:
            from hermes_escape_top.web.refresh import manifest_status
            ms = str((manifest_status(config) or {}).get("status", "?"))
            checks.append({"name": "manifest", "ok": ms == "OK", "detail": ms})
        except Exception as exc:
            checks.append({"name": "manifest", "ok": False, "detail": f"check err: {exc!r}"[:60]})
        ok = requested_status == "OK" and all(c["ok"] for c in checks)
        final_status = "OK" if ok else "FAILED"
        receipt = {
            "status": final_status,
            "run_at": now,
            "started_at": started_at,
            "finished_at": now,
            "as_of": str(as_of),
            "run_type": run_type,
            "ok": ok,
            "failed_step": failed_step if final_status == "FAILED" else "",
            "error": step_error if final_status == "FAILED" else "",
            "checks": checks,
        }
        _atomic_write_json(path, receipt)
        print(f"[receipt] self-check {'OK' if ok else 'FAIL'} -> {path.name}")
        return receipt
    except Exception as exc:
        # A stale OK receipt is more dangerous than a missing receipt. If the
        # replacement itself failed, remove the prior attestation so health
        # becomes CRITICAL instead of continuing to show yesterday's green run.
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        print(f"[receipt] WARNING: receipt write failed ({exc!r}); continuing.")
        return None


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _build_daily_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="M4-1 package run-daily wrapper")
    parser.add_argument("--as-of", default=None, help="YYYY-MM-DD (default: today)")
    parser.add_argument("--skip-refresh", action="store_true", help="Skip OHLCV history refresh")
    parser.add_argument("--live", action="store_true",
                        help="Write to live data/reports/orders dirs (shadow by default)")
    parser.add_argument("--commit-state", action="store_true",
                        help="Update state.json (only with --live)")
    parser.add_argument("--run-type", default="manual_rerun",
                        choices=["scheduled", "manual_rerun", "shadow"],
                        help="Who triggered this run; the launchd daily job passes 'scheduled'. "
                             "The WebUI pins the latest scheduled run as the official daily advice "
                             "and shows manual_rerun separately as non-official preview.")
    parser.add_argument("--lock-timeout", type=float, default=600.0,
                        help=argparse.SUPPRESS)
    return parser


def _run_daily_with_receipt(args: argparse.Namespace, *, _lease: Any) -> None:
    scheduled = bool(args.live and args.run_type == "scheduled")
    context = {
        "as_of": str(args.as_of or date.today().isoformat()),
        "step": "startup",
    }
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    if scheduled:
        running = _write_run_receipt(
            context["as_of"],
            args.run_type,
            status="RUNNING",
            started_at=started_at,
        )
        if running is None:
            raise RuntimeError("scheduled run cannot start without a RUNNING receipt")
    try:
        _execute_daily(args=args, _lease=_lease, _run_context=context)
        if scheduled:
            finished = _write_run_receipt(
                context["as_of"],
                args.run_type,
                status="OK",
                started_at=started_at,
            )
            if finished is None or finished.get("status") != "OK":
                raise RuntimeError("scheduled run end-state receipt failed")
    except BaseException as exc:
        if scheduled:
            _write_run_receipt(
                context["as_of"],
                args.run_type,
                steps_ok=False,
                step_error=f"{type(exc).__name__}: {exc}",
                status="FAILED",
                started_at=started_at,
                failed_step=str(context.get("step") or "unknown"),
            )
        raise


def _execute_daily(
    *,
    args: argparse.Namespace,
    _lease: Any,
    _run_context: Dict[str, str],
) -> None:
    shadow = not args.live
    refresh_end = args.as_of or date.today().isoformat()

    if shadow:
        print(f"[M4-1] SHADOW mode — writing to data/shadow/ (production untouched)")
    else:
        print(f"[M4-1] LIVE mode — writing to live dirs")

    if not args.skip_refresh:
        _run_context["step"] = "history_refresh"
        # A hung source must never kill the scoring run — degrade to cached
        # data (the same philosophy each refresh step already applies to
        # non-zero exits; subprocess.TimeoutExpired previously escaped it).
        try:
            refresh_history(refresh_end, _lease=_lease)
        except Exception as exc:
            print(f"[M4-1] WARNING: history refresh crashed ({exc!r}); proceeding with cached bars.")
        _heal_lagging_symbols(refresh_end, _lease=_lease)
        _run_context["step"] = "external_source_refresh"
        try:
            refresh_external_sources()
        except Exception as exc:
            print(f"[M4-1a] WARNING: external source refresh crashed ({exc!r}); proceeding with cached data.")
        _run_context["step"] = "soft_data_refresh"
        try:
            refresh_soft_data()
        except Exception as exc:
            print(f"[M4-1b] WARNING: soft refresh crashed ({exc!r}); proceeding with cached data.")

    as_of = args.as_of or _latest_available_as_of()
    _run_context["as_of"] = str(as_of)
    if args.as_of is None:
        print(f"[M4-1] Auto-selected latest available as_of={as_of}")

    _run_context["step"] = "preflight"
    _preflight_report(shadow, as_of)

    _run_context["step"] = "history_integrity"
    offenders = _history_integrity_scan(load_config())
    if offenders:
        for line in offenders:
            print(f"[integrity] CRITICAL corrupted bar: {line}")
        if not shadow:
            print("[integrity] ABORTING live run — refusing to score on corrupted history (stale beats garbage).")
            sys.exit(3)
        print("[integrity] WARNING: shadow run continues despite corruption.")

    # Re-freeze the data manifest after a clean refresh: the daily OHLCV update
    # changes history CSV hashes, so without this the manifest sits in permanent
    # DRIFT (health CRITICAL) every day. The integrity scan above already verified
    # the bars are clean — verify-then-freeze. Live, and only when a refresh ran.
    if not shadow and not args.skip_refresh:
        _run_context["step"] = "manifest_refreeze"
        _refreeze_manifest()

    _run_context["step"] = "score_pipeline"
    payload = run_score_pipeline(
        as_of,
        shadow=shadow,
        run_type=args.run_type,
        _lease=_lease,
    )
    _run_context["step"] = "translate"
    translated = translate(payload)
    orders = translated.get("orders_preview", {})
    _run_context["step"] = "artifact_write"
    write_artifacts(translated, orders, as_of, shadow=shadow)
    _run_context["step"] = "post_run_diff"
    _post_run_diff(payload, as_of, shadow)
    _run_context["step"] = "next5_refresh"
    try:
        _refresh_next5_unlock()
    except Exception as exc:
        print(f"[NEXT5] WARNING: unlock scan failed ({exc!r}); continuing.")
    if not shadow:
        _run_context["step"] = "audit_rotation"
        try:
            from hermes_escape_top.core.data.audit import rotate_audit_log
            from hermes_escape_top.config import resolve_path
            arch = rotate_audit_log(resolve_path(load_config(), "archive_dir") / "audit_log.jsonl")
            if arch:
                print(f"[audit] rotated; full history archived -> {arch.name}")
        except Exception as exc:
            print(f"[audit] WARNING: rotation skipped ({exc!r}); continuing.")
    commit_error = ""
    if args.commit_state:
        if shadow:
            print("[M4-1] WARNING: --commit-state ignored in shadow mode.")
        else:
            _run_context["step"] = "state_commit"
            try:
                state_path = commit_state(translated, as_of)
                print(f"[M4-1] state committed: {state_path}")
            except Exception as exc:
                commit_error = f"state commit failed: {exc!r}"
                print(f"[M4-1] ERROR: {commit_error}")
    if commit_error:
        raise RuntimeError(commit_error)

    _run_context["step"] = "complete"
    print(f"[M4-1] Done. as_of={as_of} mode={'shadow' if shadow else 'LIVE'}")


def main() -> None:
    # #3: every data-mutating run serializes against the WebUI refresh endpoints
    # and any other daily run via one flock on <archive_dir>/.pipeline.lock. The
    # cron MUST run, so it waits its turn (blocking) rather than bailing — but
    # never hangs past the timeout if a holder is stuck.
    from hermes_escape_top.core.safe_io import PipelineBusy, pipeline_lock

    args = _build_daily_parser().parse_args()
    try:
        with pipeline_lock(blocking=True, timeout=max(float(args.lock_timeout), 0.0)) as lease:
            _run_daily_with_receipt(args, _lease=lease)
    except PipelineBusy as exc:
        print(f"[M4-1] ABORT: {exc}; another run/refresh held the lock too long.")
        sys.exit(1)


if __name__ == "__main__":
    main()
