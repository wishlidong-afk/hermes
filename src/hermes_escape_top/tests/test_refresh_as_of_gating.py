"""The 更新持仓 (refresh positions) button is an IBKR-only overlay refresh.

It must not run score_pipeline or refresh market history. A fresh position read
should update the dashboard's external-position layer while keeping the official
strategy record unchanged.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.web import refresh as refresh_mod
from hermes_escape_top.web.refresh import apply_ibkr_position_overlay, refresh_positions_only
from hermes_escape_top.ibkr.positions import PositionRecord, PositionSnapshot


@contextmanager
def _fake_lock(*args, **kwargs):
    yield object()  # stand-in lease; the scoring call is mocked out


def test_refresh_positions_only_reads_ibkr_without_scoring_or_history(tmp_path):
    archive = tmp_path / "archive"
    base_payload = {
        "as_of": "2026-06-30",
        "input_hash": "official-hash",
        "sizing": {"SOXL": {"target_weight": 0.1}},
        "routing": {},
    }
    snap = PositionSnapshot(
        account_id="U_TEST",
        net_liq=100_000.0,
        gross_position_value=12_000.0,
        total_cash=88_000.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        positions=[
            PositionRecord(
                symbol="SOXL",
                sec_type="STK",
                quantity=100.0,
                avg_cost=100.0,
                market_value=12_000.0,
            )
        ],
        sync_time="2026-07-01T01:00:00+00:00",
        source="tws",
        snapshot_stale=False,
        client_id=991,
    )

    with mock.patch.object(refresh_mod, "load_config", return_value={"ibkr": {"enabled": True}}), \
         mock.patch.object(refresh_mod, "resolve_path", return_value=archive), \
         mock.patch.object(refresh_mod, "pipeline_lock", _fake_lock), \
         mock.patch.object(refresh_mod, "recover_incomplete_score_run", create=True) as recover, \
         mock.patch.object(refresh_mod, "read_positions", return_value=snap) as read_positions, \
         mock.patch.object(refresh_mod, "_score_pipeline_locked", side_effect=AssertionError("must not score")):
        out = refresh_positions_only("latest", blocking=False, base_payload=base_payload)

    read_positions.assert_called_once()
    recover.assert_called_once()
    assert recover.call_args.args == (archive,)
    assert out["as_of"] == "2026-06-30"
    assert out["ibkr"]["source"] == "tws"
    assert out["ibkr"]["snapshot_stale"] is False
    assert out["ibkr_refresh_status"]["score_pipeline"] is False
    assert out["ibkr_refresh_status"]["history_refreshed"] is False
    assert (archive / "ibkr_position_overlay.json").exists()


def _write_overlay(archive: Path, **fields) -> None:
    archive.mkdir(parents=True, exist_ok=True)
    overlay = {"ibkr": {
        "source": "tws",
        "net_liq": 100.0,
        "sync_time": datetime.now(timezone.utc).isoformat(),
        "snapshot_stale": False,
    }}
    overlay.update(fields)
    (archive / "ibkr_position_overlay.json").write_text(json.dumps(overlay), encoding="utf-8")


def _apply(archive: Path, payload: dict) -> dict:
    with mock.patch.object(refresh_mod, "load_config", return_value={}), \
         mock.patch.object(refresh_mod, "resolve_path", return_value=archive):
        return apply_ibkr_position_overlay(payload)


def test_overlay_merges_on_matching_as_of_and_hash(tmp_path):
    archive = tmp_path / "archive"
    _write_overlay(archive, as_of="2026-06-30", base_input_hash="h1")
    out = _apply(archive, {"as_of": "2026-06-30", "input_hash": "h1", "ibkr": {"source": "stale"}})
    assert out["ibkr"]["source"] == "tws"          # overlay applied


def test_overlay_rejected_on_as_of_mismatch(tmp_path):
    archive = tmp_path / "archive"
    _write_overlay(archive, as_of="2026-06-30", base_input_hash="h1")
    out = _apply(archive, {"as_of": "2026-07-01", "input_hash": "h1", "ibkr": {"source": "kept"}})
    assert out["ibkr"]["source"] == "kept"         # untouched


def test_overlay_rejected_when_hash_differs(tmp_path):
    archive = tmp_path / "archive"
    _write_overlay(archive, as_of="2026-06-30", base_input_hash="h1")
    out = _apply(archive, {"as_of": "2026-06-30", "input_hash": "h2", "ibkr": {"source": "kept"}})
    assert out["ibkr"]["source"] == "kept"


def test_overlay_rejected_when_overlay_hash_missing_but_payload_scored(tmp_path):
    # The fix: an overlay written before any official run (base_input_hash=None)
    # must NOT bleed onto a later, different official run for the same as_of.
    archive = tmp_path / "archive"
    _write_overlay(archive, as_of="2026-06-30", base_input_hash=None)
    out = _apply(archive, {"as_of": "2026-06-30", "input_hash": "official-h", "ibkr": {"source": "kept"}})
    assert out["ibkr"]["source"] == "kept"


def test_overlay_applies_when_payload_has_no_hash(tmp_path):
    # Fresh-system / empty-dashboard fallback: no official run yet, so the
    # just-refreshed position layer should still show.
    archive = tmp_path / "archive"
    _write_overlay(archive, as_of="2026-06-30", base_input_hash=None)
    out = _apply(archive, {"as_of": "2026-06-30", "ibkr": {"source": "stale"}})
    assert out["ibkr"]["source"] == "tws"


def test_overlay_refreshes_action_context_when_ibkr_state_changes(tmp_path):
    archive = tmp_path / "archive"
    _write_overlay(
        archive,
        as_of="2026-06-30",
        base_input_hash="h1",
        ibkr={
            "source": "tws",
            "net_liq": 100000.0,
            "sync_time": datetime.now(timezone.utc).isoformat(),
            "snapshot_stale": False,
        },
    )
    day = date(2026, 6, 30)
    snapshot = SymbolSnapshot(
        "SOXL",
        day,
        {"close": Field("close", 100.0, "unit", day)},
    )
    payload = {
        "as_of": "2026-06-30",
        "input_hash": "h1",
        "snapshots": {"SOXL": snapshot.to_dict()},
        "data_quality": {"level": "HIGH", "overall_score": 97.0},
        "ibkr": {"source": "snapshot", "snapshot_stale": True},
        "scores": {
            "SOXL": {
                "status": "HOLD",
                "final_score": 5.0,
                "sell_fraction": 0.0,
                "hard_valve_hits": [],
                "missing_weight": 0.0,
                "factor_scores": {},
            }
        },
        "sizing": {"SOXL": {"sleeve_cap": 0.3, "target_weight": 0.1}},
        "routing": {"SOXL": {"applies": False}},
        "reentry": {"SOXL": {}},
        "posterior_pnl": {"portfolio_value": 100000.0},
        "decision_layers": {
            "SOXL": {
                "action_confidence": {
                    "level": "MEDIUM",
                    "score": 70.0,
                    "reasons": ["IBKR is snapshot/stale or unavailable"],
                }
            }
        },
        "today_ops": {"ibkr_stale": True},
    }

    out = _apply(archive, payload)

    confidence = out["decision_layers"]["SOXL"]["action_confidence"]
    assert out["ibkr"]["source"] == "tws"
    assert out["today_ops"]["ibkr_stale"] is False
    assert "IBKR is snapshot/stale or unavailable" not in confidence["reasons"]
