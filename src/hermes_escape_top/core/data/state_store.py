from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


def write_state_snapshot(path: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Persist one complete scoring payload into the unified Hermes state DB.

    The existing CSV/JSONL/SQLite artifacts remain in place for backwards
    compatibility; this database is the single queryable "what did the system
    know and decide" ledger for the WebUI and future automation.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    now = _now()
    with sqlite3.connect(path) as conn:
        _ensure_schema(conn)
        score_run_id = _insert_score_run(conn, payload, now)
        _insert_decisions(conn, score_run_id, payload)
        _insert_factors(conn, score_run_id, payload)
        _insert_data_sources(conn, score_run_id, payload)
        _insert_posterior(conn, score_run_id, payload)
        _insert_calibration(conn, payload)
        _insert_ibkr_snapshot(conn, payload.get("as_of"), payload.get("ibkr") or {}, now)
        meta = {
            "db_path": str(path),
            "score_run_id": score_run_id,
            "written_at": now,
        }
        payload["state"] = meta
        conn.execute(
            "UPDATE score_runs SET payload_json=? WHERE id=?",
            (_dumps(payload), score_run_id),
        )
    return meta


def write_refresh_run(
    path: Path,
    *,
    requested_as_of: Any,
    effective_as_of: Any,
    status: str,
    steps: Iterable[Dict[str, Any]],
    refresh_status: Dict[str, Any],
    payload_hash: Optional[str] = None,
) -> Dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    now = _now()
    steps_list = list(steps)
    with sqlite3.connect(path) as conn:
        _ensure_schema(conn)
        cur = conn.execute(
            """
            INSERT INTO refresh_runs
            (requested_as_of, effective_as_of, status, steps_json, refresh_status_json, payload_hash, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(requested_as_of),
                str(effective_as_of),
                status,
                _dumps(steps_list),
                _dumps(refresh_status),
                payload_hash,
                now,
                now,
            ),
        )
        run_id = int(cur.lastrowid)
    return {"state_db_path": str(path), "refresh_run_id": run_id, "status": status, "steps": steps_list}


def latest_execution_confirmations(path: Path) -> Dict[str, Dict[str, Any]]:
    """Return the latest manually/imported execution confirmation per symbol.

    It is intentionally read-only and empty-safe: until IBKR executions are
    wired, the system displays "no confirmed tranche" rather than inventing one.
    """
    if not path.exists():
        return {}
    with sqlite3.connect(path) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT symbol, tranche, status, source, confirmed_at, payload_json
            FROM execution_confirmations
            WHERE id IN (
              SELECT MAX(id) FROM execution_confirmations GROUP BY symbol
            )
            """
        ).fetchall()
    out: Dict[str, Dict[str, Any]] = {}
    for symbol, tranche, status, source, confirmed_at, payload_json in rows:
        try:
            payload = json.loads(payload_json or "{}")
        except Exception:
            payload = {}
        out[str(symbol)] = {
            "symbol": symbol,
            "tranche": tranche,
            "status": status,
            "source": source,
            "confirmed_at": confirmed_at,
            "payload": payload,
        }
    return out


def _insert_score_run(conn: sqlite3.Connection, payload: Dict[str, Any], now: str) -> int:
    dq = payload.get("data_quality") or {}
    ibkr = payload.get("ibkr") or {}
    cur = conn.execute(
        """
        INSERT INTO score_runs
        (as_of, schema_version, config_version, input_hash, data_quality_level, data_quality_score,
         ibkr_source, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(payload.get("as_of", ""))[:10],
            payload.get("schema_version"),
            payload.get("config_version"),
            payload.get("input_hash") or _hash_payload(payload),
            dq.get("level"),
            _float(dq.get("overall_score")),
            ibkr.get("source"),
            _dumps(payload),
            now,
        ),
    )
    return int(cur.lastrowid)


def _insert_decisions(conn: sqlite3.Connection, score_run_id: int, payload: Dict[str, Any]) -> None:
    scores = payload.get("scores") or {}
    sizing = payload.get("sizing") or {}
    routing = payload.get("routing") or {}
    layers = payload.get("decision_layers") or {}
    intents = payload.get("action_intents") or {}
    for symbol, score in sorted(scores.items()):
        route = routing.get(symbol) or {}
        size = sizing.get(symbol) or {}
        intent = intents.get(symbol) or {}
        layer = layers.get(symbol) or {}
        conn.execute(
            """
            INSERT INTO decisions
            (score_run_id, symbol, status, final_score, sell_fraction, target_weight,
             route_defcon, route_destination, hard_valves_json, confidence_level,
             action, target_symbol, target_notional, target_shares, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                score_run_id,
                symbol,
                score.get("status"),
                _float(score.get("final_score")),
                _float(score.get("sell_fraction")),
                _float(size.get("target_weight")),
                route.get("defcon"),
                route.get("destination"),
                _dumps(score.get("hard_valve_hits") or []),
                (layer.get("action_confidence") or {}).get("level"),
                intent.get("action"),
                intent.get("target_symbol"),
                _float(intent.get("target_notional")),
                _float(intent.get("target_shares")),
                _dumps({"score": score, "sizing": size, "routing": route, "layer": layer, "intent": intent}),
            ),
        )


def _insert_factors(conn: sqlite3.Connection, score_run_id: int, payload: Dict[str, Any]) -> None:
    for symbol, score in sorted((payload.get("scores") or {}).items()):
        for module, rows in (score.get("factor_scores") or {}).items():
            for row in rows or []:
                conn.execute(
                    """
                    INSERT INTO factor_values
                    (score_run_id, symbol, module, factor_id, score, max_score, missing_json, explain, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        score_run_id,
                        symbol,
                        module,
                        row.get("factor_id") or row.get("name"),
                        _float(row.get("score")),
                        _float(row.get("max_score")),
                        _dumps(row.get("missing_fields") or []),
                        row.get("explain", ""),
                        _dumps(row),
                    ),
                )


def _insert_data_sources(conn: sqlite3.Connection, score_run_id: int, payload: Dict[str, Any]) -> None:
    breakdown = payload.get("data_quality_breakdown") or {}
    for row in breakdown.get("sources") or []:
        conn.execute(
            """
            INSERT INTO data_sources
            (score_run_id, name, category, as_of, status, is_proxy, latency_days, quality_penalty, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                score_run_id,
                row.get("name"),
                row.get("category"),
                row.get("as_of"),
                row.get("status"),
                int(bool(row.get("is_proxy"))),
                _float(row.get("latency_days")),
                _float(row.get("quality_penalty")),
                _dumps(row),
            ),
        )


def _insert_posterior(conn: sqlite3.Connection, score_run_id: int, payload: Dict[str, Any]) -> None:
    posterior = payload.get("posterior_pnl") or {}
    portfolio_value = _float(posterior.get("portfolio_value"))
    for system, rows in [("escape", posterior.get("escape") or {}), ("mirror", posterior.get("mirror") or {})]:
        for sleeve, row in sorted(rows.items()):
            conn.execute(
                """
                INSERT INTO posterior_pnl
                (score_run_id, system, sleeve, symbol, target_weight, notional, shares, pnl, return_pct, portfolio_value, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    score_run_id,
                    system,
                    sleeve,
                    row.get("symbol"),
                    _float(row.get("target_weight")),
                    _float(row.get("notional")),
                    _float(row.get("shares")),
                    _float(row.get("pnl")),
                    _float(row.get("return_pct")),
                    portfolio_value,
                    _dumps(row),
                ),
            )


def _insert_calibration(conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
    posterior = payload.get("posterior_pnl") or {}
    portfolio_value = _float(posterior.get("portfolio_value"))
    as_of = str(payload.get("as_of", ""))[:10]
    for system, rows in [("escape", posterior.get("escape") or {}), ("mirror", posterior.get("mirror") or {})]:
        for sleeve, row in sorted(rows.items()):
            conn.execute(
                """
                INSERT INTO calibration_logs
                (as_of, system, sleeve, symbol, pnl, return_pct, notional, portfolio_value, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    as_of,
                    system,
                    sleeve,
                    row.get("symbol"),
                    _float(row.get("pnl")),
                    _float(row.get("return_pct")),
                    _float(row.get("notional")),
                    portfolio_value,
                    _dumps(row),
                    _now(),
                ),
            )


def _insert_ibkr_snapshot(conn: sqlite3.Connection, as_of: Any, ibkr: Dict[str, Any], now: str) -> None:
    if not ibkr:
        return
    conn.execute(
        """
        INSERT INTO ibkr_snapshots
        (as_of, source, account_id, net_liq, sync_time, snapshot_stale, client_id, error, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(as_of or "")[:10],
            ibkr.get("source"),
            ibkr.get("account_id"),
            _float(ibkr.get("net_liq")),
            ibkr.get("sync_time"),
            int(bool(ibkr.get("snapshot_stale"))),
            ibkr.get("client_id"),
            ibkr.get("error"),
            _dumps(ibkr),
            now,
        ),
    )


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS score_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          as_of TEXT NOT NULL,
          schema_version TEXT,
          config_version TEXT,
          input_hash TEXT,
          data_quality_level TEXT,
          data_quality_score REAL,
          ibkr_source TEXT,
          payload_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS decisions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          score_run_id INTEGER NOT NULL,
          symbol TEXT NOT NULL,
          status TEXT,
          final_score REAL,
          sell_fraction REAL,
          target_weight REAL,
          route_defcon TEXT,
          route_destination TEXT,
          hard_valves_json TEXT,
          confidence_level TEXT,
          action TEXT,
          target_symbol TEXT,
          target_notional REAL,
          target_shares REAL,
          payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS factor_values (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          score_run_id INTEGER NOT NULL,
          symbol TEXT NOT NULL,
          module TEXT NOT NULL,
          factor_id TEXT,
          score REAL,
          max_score REAL,
          missing_json TEXT,
          explain TEXT,
          payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_sources (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          score_run_id INTEGER NOT NULL,
          name TEXT,
          category TEXT,
          as_of TEXT,
          status TEXT,
          is_proxy INTEGER,
          latency_days REAL,
          quality_penalty REAL,
          payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS refresh_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          requested_as_of TEXT,
          effective_as_of TEXT,
          status TEXT,
          steps_json TEXT NOT NULL,
          refresh_status_json TEXT NOT NULL,
          payload_hash TEXT,
          started_at TEXT NOT NULL,
          completed_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ibkr_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          as_of TEXT,
          source TEXT,
          account_id TEXT,
          net_liq REAL,
          sync_time TEXT,
          snapshot_stale INTEGER,
          client_id INTEGER,
          error TEXT,
          payload_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS posterior_pnl (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          score_run_id INTEGER NOT NULL,
          system TEXT NOT NULL,
          sleeve TEXT NOT NULL,
          symbol TEXT,
          target_weight REAL,
          notional REAL,
          shares REAL,
          pnl REAL,
          return_pct REAL,
          portfolio_value REAL,
          payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS calibration_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          as_of TEXT,
          system TEXT NOT NULL,
          sleeve TEXT NOT NULL,
          symbol TEXT,
          pnl REAL,
          return_pct REAL,
          notional REAL,
          portfolio_value REAL,
          payload_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS execution_confirmations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          symbol TEXT NOT NULL,
          tranche TEXT NOT NULL,
          status TEXT NOT NULL,
          source TEXT NOT NULL,
          confirmed_at TEXT NOT NULL,
          payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_score_runs_as_of ON score_runs(as_of)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_decisions_run_symbol ON decisions(score_run_id, symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_refresh_runs_as_of ON refresh_runs(effective_as_of)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ibkr_snapshots_as_of ON ibkr_snapshots(as_of)")


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _hash_payload(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(_dumps(payload).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
