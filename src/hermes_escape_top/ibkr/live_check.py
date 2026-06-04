"""Read-only IBKR live verification.

This module is an explicit live gate: cached snapshots are useful for the
dashboard, but they do not count as a live IBKR verification.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from hermes_escape_top.config import CONFIG_PATH, load_config, resolve_path
from hermes_escape_top.ibkr.positions import read_positions
from hermes_escape_top.pipeline import score_pipeline


def run_live_check(
    as_of: str,
    config_path: Path = CONFIG_PATH,
    write_report: bool = True,
) -> Dict[str, Any]:
    """Verify that IBKR is live, then run one read-only strategy refresh."""
    config = load_config(config_path)
    checked_at = datetime.now(timezone.utc).isoformat()
    snap = read_positions(config)
    payload: Dict[str, Any] = {
        "schema_version": "hermes-ibkr-live-check-v1",
        "as_of": str(as_of)[:10],
        "checked_at": checked_at,
        "read_only": True,
        "ok": False,
        "status": "IBKR_NOT_LIVE",
        "preflight": {
            "host": config.get("ibkr", {}).get("host", "127.0.0.1"),
            "ports": config.get("ibkr", {}).get("ports", []),
            "source": snap.source,
            "account_id": snap.account_id,
            "net_liq": snap.net_liq,
            "positions": len(snap.positions),
            "sync_time": snap.sync_time,
            "error": snap.error,
        },
    }

    if snap.source != "tws":
        payload["message"] = (
            "IBKR Gateway/TWS is not live. Cached snapshots are not accepted "
            "for live verification."
        )
        return _finalize(payload, config, write_report)

    score = score_pipeline(as_of, config_path=config_path, shadow=False)
    ibkr = score.get("ibkr") or {}
    payload.update({
        "ok": ibkr.get("source") == "tws",
        "status": "LIVE_OK" if ibkr.get("source") == "tws" else "SCORE_IBKR_NOT_TWS",
        "message": "Live IBKR read and strategy refresh completed." if ibkr.get("source") == "tws" else "Initial IBKR read was live, but score refresh did not return source=tws.",
        "audit_log_path": score.get("audit_log_path"),
        "signal_journal_path": score.get("signal_journal_path"),
        "score_summary": _score_summary(score),
        "ibkr": _ibkr_summary(ibkr),
    })
    return _finalize(payload, config, write_report)


def _score_summary(score: Dict[str, Any]) -> Dict[str, Any]:
    rows = {}
    for symbol, row in (score.get("scores") or {}).items():
        rows[symbol] = {
            "status": row.get("status"),
            "final_score": row.get("final_score"),
            "sell_fraction": row.get("sell_fraction"),
            "hard_valves": row.get("hard_valve_hits", []),
            "target_weight": (score.get("sizing") or {}).get(symbol, {}).get("target_weight"),
            "route": (score.get("routing") or {}).get(symbol, {}),
        }
    return rows


def _ibkr_summary(ibkr: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": ibkr.get("source"),
        "account_id": ibkr.get("account_id"),
        "net_liq": ibkr.get("net_liq"),
        "sync_time": ibkr.get("sync_time"),
        "max_abs_delta": ibkr.get("max_abs_delta"),
        "all_within_tolerance": ibkr.get("all_within_tolerance"),
        "error": ibkr.get("error"),
        "trade_symbols": ibkr.get("trade_symbols", []),
        "route_legs": ibkr.get("route_legs", []),
    }


def _finalize(payload: Dict[str, Any], config: Dict[str, Any], write_report: bool) -> Dict[str, Any]:
    if not write_report:
        return payload
    report_paths = _write_reports(payload, config)
    payload["report_paths"] = report_paths
    return payload


def _write_reports(payload: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, str]:
    archive = resolve_path(config, "archive_dir") / "live_checks"
    archive.mkdir(parents=True, exist_ok=True)
    try:
        stamp = datetime.fromisoformat(str(payload.get("checked_at", "")).replace("Z", "+00:00")).strftime("%Y%m%dT%H%M%SZ")
    except Exception:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    as_of = str(payload.get("as_of", "unknown"))[:10]
    json_path = archive / f"ibkr_live_check_{as_of}_{stamp}.json"
    md_path = archive / f"ibkr_live_check_{as_of}_{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(payload), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def _render_markdown(payload: Dict[str, Any]) -> str:
    lines = [
        f"# IBKR Live Check — {payload.get('as_of')}",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- OK: `{payload.get('ok')}`",
        f"- Read-only: `{payload.get('read_only')}`",
        f"- Checked at: `{payload.get('checked_at')}`",
        f"- Message: {payload.get('message', '')}",
        "",
        "## Preflight",
        "",
        f"- Source: `{payload.get('preflight', {}).get('source')}`",
        f"- Account: `{payload.get('preflight', {}).get('account_id')}`",
        f"- NetLiq: `{payload.get('preflight', {}).get('net_liq')}`",
        f"- Positions: `{payload.get('preflight', {}).get('positions')}`",
        f"- Error: `{payload.get('preflight', {}).get('error')}`",
        "",
    ]
    score_summary = payload.get("score_summary") or {}
    if score_summary:
        lines += [
            "## Strategy Summary",
            "",
            "| Symbol | Status | Score | Sell% | Target | Hard Valves |",
            "|---|---|---:|---:|---:|---|",
        ]
        for symbol, row in sorted(score_summary.items()):
            sell = row.get("sell_fraction")
            target = row.get("target_weight")
            lines.append(
                f"| {symbol} | {row.get('status')} | {row.get('final_score')} | "
                f"{float(sell or 0):.0%} | {float(target or 0):.2%} | "
                f"{','.join(row.get('hard_valves') or []) or '-'} |"
            )
        lines.append("")
    return "\n".join(lines)
