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
    """Return (runtime_root, package_parent) for both repo and installed skill layouts."""
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
from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.store import LocalStore

TRADE_SYMBOLS = ["MSTR", "FNGU", "SOXL"]


def _subprocess_env() -> Dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(PACKAGE_PARENT) + (os.pathsep + existing if existing else "")
    return env


def _latest_available_as_of() -> str:
    """Use the latest common cached bar date instead of today's calendar date."""
    try:
        config = load_config()
        store = LocalStore(config)
        candidates = []
        for symbol in ["QQQ", "SPY", *TRADE_SYMBOLS]:
            hist = store.load_history(symbol)
            if hist is None or getattr(hist, "empty", True):
                continue
            last = hist.index[-1]
            last_date = last.date() if hasattr(last, "date") else date.fromisoformat(str(last)[:10])
            candidates.append(last_date)
        if candidates:
            return min(candidates).isoformat()
    except Exception as exc:
        print(f"[M4-1] WARNING: latest available date detection failed: {exc!r}")
    return date.today().isoformat()


# ── Step 1: refresh OHLCV history ────────────────────────────────────────────

def refresh_history(as_of: str) -> None:
    """Fetch the latest OHLCV bar via the package's backfill-history command."""
    print(f"[M4-1] Refreshing OHLCV history up to {as_of}…")
    result = subprocess.run(
        [PYTHON, "-m", "hermes_escape_top.cli", "backfill-history",
         "--end", as_of, "--repair-overlap-days", "3"],
        cwd=str(BASE_DIR),
        env=_subprocess_env(),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("[M4-1] WARNING: backfill-history returned non-zero; proceeding with cached data.")
        print(result.stderr[-500:] if result.stderr else "")
    else:
        print("[M4-1] History refresh OK.")


# ── Step 2: run the package score pipeline ────────────────────────────────────

def run_score_pipeline(as_of: str, shadow: bool = True) -> Dict[str, Any]:
    print(f"[M4-1] Running score_pipeline({as_of}, shadow={shadow})…")
    payload = pipeline.score_pipeline(as_of, shadow=shadow)
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
        plans[sym] = {
            "phase0_unlocked": False,
            "phase0_checks": {"time_lock": False, "emotion_lock": False, "structure_lock": False},
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

def write_artifacts(translated: Dict[str, Any], orders: Dict[str, Any],
                    as_of: str, shadow: bool = True) -> Dict[str, Path]:
    if shadow:
        data_dir = BASE_DIR / "data" / "shadow"
        report_dir = BASE_DIR / "reports" / "shadow"
        order_dir = BASE_DIR / "orders" / "shadow"
    else:
        data_dir = BASE_DIR / "data"
        report_dir = BASE_DIR / "reports"
        order_dir = BASE_DIR / "orders"

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

def main() -> None:
    p = argparse.ArgumentParser(description="M4-1 package run-daily wrapper")
    p.add_argument("--as-of", default=None, help="YYYY-MM-DD (default: today)")
    p.add_argument("--skip-refresh", action="store_true", help="Skip OHLCV history refresh")
    p.add_argument("--live", action="store_true",
                   help="Write to live data/reports/orders dirs (shadow by default)")
    p.add_argument("--commit-state", action="store_true",
                   help="Update state.json (only with --live)")
    args = p.parse_args()

    shadow = not args.live
    refresh_end = args.as_of or date.today().isoformat()

    if shadow:
        print(f"[M4-1] SHADOW mode — writing to data/shadow/ (production untouched)")
    else:
        print(f"[M4-1] LIVE mode — writing to live dirs")

    if not args.skip_refresh:
        refresh_history(refresh_end)

    as_of = args.as_of or _latest_available_as_of()
    if args.as_of is None:
        print(f"[M4-1] Auto-selected latest available as_of={as_of}")

    payload = run_score_pipeline(as_of, shadow=shadow)
    translated = translate(payload)
    orders = translated.get("orders_preview", {})
    write_artifacts(translated, orders, as_of, shadow=shadow)
    if args.commit_state:
        if shadow:
            print("[M4-1] WARNING: --commit-state ignored in shadow mode.")
        else:
            state_path = commit_state(translated, as_of)
            print(f"[M4-1] state committed: {state_path}")

    print(f"[M4-1] Done. as_of={as_of} mode={'shadow' if shadow else 'LIVE'}")


if __name__ == "__main__":
    main()
