from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


DEFAULT_STATE_RETENTION = {
    "score_runs": 500,
    "refresh_runs": 200,
    "ibkr_snapshots": 200,
    "calibration_logs": 1000,
    "execution_confirmations": 500,
}


def write_state_snapshot(
    path: Path,
    payload: Dict[str, Any],
    *,
    retention: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
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
        _insert_reentry_states(conn, score_run_id, payload)
        _insert_ibkr_snapshot(conn, payload.get("as_of"), payload.get("ibkr") or {}, now)
        meta = {
            "db_path": str(path),
            "score_run_id": score_run_id,
            "written_at": now,
        }
        payload["state"] = meta
        _apply_retention_conn(conn, retention)
        payload["ibkr_history"] = _recent_ibkr_snapshots_conn(conn, limit=5)
        payload["calibration_history"] = _recent_calibration_logs_conn(conn, limit=12)
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
    retention: Optional[Dict[str, int]] = None,
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
        _apply_retention_conn(conn, retention)
    return {"state_db_path": str(path), "refresh_run_id": run_id, "status": status, "steps": steps_list}


def record_execution_confirmation(
    path: Path,
    *,
    symbol: str,
    tranche: str,
    status: str = "CONFIRMED",
    source: str = "manual_web",
    confirmed_at: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Append a manual/imported execution confirmation for reentry tracking."""
    if not symbol or not tranche:
        raise ValueError("symbol and tranche are required")
    path.parent.mkdir(parents=True, exist_ok=True)
    confirmed_at = confirmed_at or _now()
    payload = payload or {}
    with sqlite3.connect(path) as conn:
        _ensure_schema(conn)
        cur = conn.execute(
            """
            INSERT INTO execution_confirmations
            (symbol, tranche, status, source, confirmed_at, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                symbol.upper(),
                tranche,
                status,
                source,
                confirmed_at,
                _dumps(payload),
            ),
        )
        confirmation_id = int(cur.lastrowid)
    return {
        "state_db_path": str(path),
        "confirmation_id": confirmation_id,
        "symbol": symbol.upper(),
        "tranche": tranche,
        "status": status,
        "source": source,
        "confirmed_at": confirmed_at,
    }


def sync_execution_confirmations(
    path: Path,
    confirmations: Iterable[Dict[str, Any]],
    *,
    retention: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Append imported execution confirmations with external-key dedupe.

    Automatic IBKR confirmation is intentionally append-only.  The dedupe key is
    stored in payload_json so the schema stays backwards-compatible with manual
    confirmations already recorded by the WebUI.
    """
    rows = list(confirmations or [])
    path.parent.mkdir(parents=True, exist_ok=True)
    inserted = []
    skipped = []
    with sqlite3.connect(path) as conn:
        _ensure_schema(conn)
        for row in rows:
            symbol = str(row.get("symbol") or "").upper()
            tranche = str(row.get("tranche") or "")
            source = str(row.get("source") or "ibkr_executions")
            external_key = str(row.get("external_key") or "")
            if not symbol or not tranche:
                skipped.append({"reason": "missing_symbol_or_tranche", "row": row})
                continue
            if external_key and _confirmation_key_exists(conn, symbol, tranche, source, external_key):
                skipped.append({"reason": "duplicate_external_key", "symbol": symbol, "tranche": tranche, "external_key": external_key})
                continue
            payload = dict(row.get("payload") or {})
            if external_key:
                payload["external_key"] = external_key
            payload["auto_confirmation"] = row
            cur = conn.execute(
                """
                INSERT INTO execution_confirmations
                (symbol, tranche, status, source, confirmed_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    tranche,
                    str(row.get("status") or "AUTO_CONFIRMED"),
                    source,
                    str(row.get("confirmed_at") or _now()),
                    _dumps(payload),
                ),
            )
            inserted.append({
                "confirmation_id": int(cur.lastrowid),
                "symbol": symbol,
                "tranche": tranche,
                "source": source,
                "external_key": external_key,
            })
        _apply_retention_conn(conn, retention)
    return {
        "state_db_path": str(path),
        "inserted": inserted,
        "skipped": skipped,
        "inserted_count": len(inserted),
        "skipped_count": len(skipped),
    }


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


def apply_retention(path: Path, policy: Optional[Dict[str, int]] = None) -> Dict[str, int]:
    """Apply state DB retention and return row counts deleted per table group."""
    if not path.exists():
        return {}
    with sqlite3.connect(path) as conn:
        _ensure_schema(conn)
        return _apply_retention_conn(conn, policy)


def recent_ibkr_snapshots(path: Path, limit: int = 5) -> list[Dict[str, Any]]:
    if not path.exists():
        return []
    with sqlite3.connect(path) as conn:
        _ensure_schema(conn)
        return _recent_ibkr_snapshots_conn(conn, limit=limit)


def recent_calibration_logs(path: Path, limit: int = 12) -> list[Dict[str, Any]]:
    if not path.exists():
        return []
    with sqlite3.connect(path) as conn:
        _ensure_schema(conn)
        return _recent_calibration_logs_conn(conn, limit=limit)


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


def _insert_reentry_states(conn: sqlite3.Connection, score_run_id: int, payload: Dict[str, Any]) -> None:
    reentry = payload.get("reentry") or {}
    reentry_state = payload.get("reentry_state") or {}
    states = reentry_state.get("states") or {}
    confirmations = reentry_state.get("execution_confirmations") or {}
    for symbol in sorted(set(reentry) | set(states)):
        plan = reentry.get(symbol) or {}
        state = states.get(symbol) or {}
        confirmation = confirmations.get(symbol) or {}
        conn.execute(
            """
            INSERT INTO reentry_states
            (score_run_id, symbol, suggested_tranche, eligible, locked_reason,
             t1_active, t2_active, confirmed_tranche, confirmed_status, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                score_run_id,
                symbol,
                plan.get("tranche"),
                int(bool(plan.get("eligible"))),
                plan.get("locked_reason"),
                int(bool(state.get("t1_active"))),
                int(bool(state.get("t2_active"))),
                confirmation.get("tranche"),
                confirmation.get("status"),
                _dumps({"plan": plan, "state": state, "confirmation": confirmation}),
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


def _recent_ibkr_snapshots_conn(conn: sqlite3.Connection, limit: int = 5) -> list[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, as_of, source, account_id, net_liq, sync_time, snapshot_stale, client_id, error, created_at
        FROM ibkr_snapshots
        ORDER BY id DESC
        LIMIT ?
        """,
        (max(1, int(limit)),),
    ).fetchall()
    out = []
    for row in rows:
        out.append({
            "id": row[0],
            "as_of": row[1],
            "source": row[2],
            "account_id": row[3],
            "net_liq": row[4],
            "sync_time": row[5],
            "snapshot_stale": bool(row[6]),
            "client_id": row[7],
            "error": row[8],
            "created_at": row[9],
        })
    return out


def _recent_calibration_logs_conn(conn: sqlite3.Connection, limit: int = 12) -> list[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, as_of, system, sleeve, symbol, pnl, return_pct, notional, portfolio_value, created_at
        FROM calibration_logs
        ORDER BY id DESC
        LIMIT ?
        """,
        (max(1, int(limit)),),
    ).fetchall()
    out = []
    for row in rows:
        out.append({
            "id": row[0],
            "as_of": row[1],
            "system": row[2],
            "sleeve": row[3],
            "symbol": row[4],
            "pnl": row[5],
            "return_pct": row[6],
            "notional": row[7],
            "portfolio_value": row[8],
            "created_at": row[9],
        })
    return out


def _confirmation_key_exists(
    conn: sqlite3.Connection,
    symbol: str,
    tranche: str,
    source: str,
    external_key: str,
) -> bool:
    rows = conn.execute(
        """
        SELECT payload_json
        FROM execution_confirmations
        WHERE symbol=? AND tranche=? AND source=?
        ORDER BY id DESC
        LIMIT 100
        """,
        (symbol, tranche, source),
    ).fetchall()
    for (payload_json,) in rows:
        try:
            payload = json.loads(payload_json or "{}")
        except Exception:
            payload = {}
        if str(payload.get("external_key") or "") == external_key:
            return True
    return False


def _apply_retention_conn(conn: sqlite3.Connection, policy: Optional[Dict[str, int]] = None) -> Dict[str, int]:
    cfg = dict(DEFAULT_STATE_RETENTION)
    if policy:
        cfg.update({key: int(value) for key, value in policy.items() if value is not None})
    deleted: Dict[str, int] = {}
    deleted["score_runs"] = _retain_score_runs(conn, cfg.get("score_runs", 500))
    for table, key in [
        ("refresh_runs", "refresh_runs"),
        ("ibkr_snapshots", "ibkr_snapshots"),
        ("calibration_logs", "calibration_logs"),
        ("execution_confirmations", "execution_confirmations"),
    ]:
        deleted[table] = _retain_latest_ids(conn, table, cfg.get(key, DEFAULT_STATE_RETENTION[key]))
    return deleted


def _retain_score_runs(conn: sqlite3.Connection, keep: int) -> int:
    keep_ids = _latest_ids(conn, "score_runs", keep)
    child_tables = ["decisions", "factor_values", "data_sources", "posterior_pnl", "reentry_states"]
    if not keep_ids:
        total = 0
        for table in child_tables:
            conn.execute(f"DELETE FROM {table}")
        cur = conn.execute("DELETE FROM score_runs")
        total += int(cur.rowcount or 0)
        return total
    placeholders = ",".join("?" for _ in keep_ids)
    for table in child_tables:
        conn.execute(f"DELETE FROM {table} WHERE score_run_id NOT IN ({placeholders})", keep_ids)
    cur = conn.execute(f"DELETE FROM score_runs WHERE id NOT IN ({placeholders})", keep_ids)
    return int(cur.rowcount or 0)


def _retain_latest_ids(conn: sqlite3.Connection, table: str, keep: int) -> int:
    keep_ids = _latest_ids(conn, table, keep)
    if not keep_ids:
        cur = conn.execute(f"DELETE FROM {table}")
        return int(cur.rowcount or 0)
    placeholders = ",".join("?" for _ in keep_ids)
    cur = conn.execute(f"DELETE FROM {table} WHERE id NOT IN ({placeholders})", keep_ids)
    return int(cur.rowcount or 0)


def _latest_ids(conn: sqlite3.Connection, table: str, keep: int) -> list[int]:
    if int(keep) <= 0:
        return []
    rows = conn.execute(
        f"SELECT id FROM {table} ORDER BY id DESC LIMIT ?",
        (int(keep),),
    ).fetchall()
    return [int(row[0]) for row in rows]


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
        CREATE TABLE IF NOT EXISTS reentry_states (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          score_run_id INTEGER NOT NULL,
          symbol TEXT NOT NULL,
          suggested_tranche TEXT,
          eligible INTEGER,
          locked_reason TEXT,
          t1_active INTEGER,
          t2_active INTEGER,
          confirmed_tranche TEXT,
          confirmed_status TEXT,
          payload_json TEXT NOT NULL
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reentry_states_run_symbol ON reentry_states(score_run_id, symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_confirmations_symbol ON execution_confirmations(symbol)")


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
