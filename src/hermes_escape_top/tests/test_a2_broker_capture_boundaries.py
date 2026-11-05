"""Characterize broker capture boundaries; no production capture wiring."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from hermes_escape_top import pipeline
from hermes_escape_top.core.data.run_transaction import (
    load_score_run_transaction,
    score_run_transaction,
)
from hermes_escape_top.core.data.transaction_evidence import business_paths
from hermes_escape_top.core.safe_io import pipeline_lock
from hermes_escape_top.ibkr import executions, positions


@pytest.fixture(autouse=True)
def forbid_broker_network(monkeypatch):
    def reject(*_args, **_kwargs):
        pytest.fail("broker boundary probe attempted a network connection")

    monkeypatch.setattr("socket.socket.connect", reject)
    monkeypatch.setattr("socket.create_connection", reject)


def _position_snapshot(value=100_000.0):
    return positions.PositionSnapshot(
        account_id="A2-SYNTHETIC", net_liq=value, gross_position_value=0.0,
        total_cash=value, unrealized_pnl=0.0, realized_pnl=0.0,
        sync_time="2026-05-30T12:00:00+00:00", source="tws",
    )


def test_connected_position_reader_persists_cache_outside_business_inventory(tmp_path, monkeypatch):
    cache = tmp_path / "positions_cache.json"
    monkeypatch.setattr(positions, "_SNAPSHOT_PATH", cache)
    broker = SimpleNamespace(
        accountValues=lambda: [SimpleNamespace(tag="NetLiquidation", value="100000", currency="USD")],
        managedAccounts=lambda: ["A2-SYNTHETIC"],
        positions=lambda: [],
    )

    snapshot = positions._read_from_tws(broker, {"ibkr": {"readonly": True}}, 992)

    assert json.loads(cache.read_text()) == snapshot.to_dict()
    assert cache.name not in {path.split("/")[-1] for path in business_paths("2026-05-29")}


def test_connected_execution_reader_persists_cache_outside_business_inventory(tmp_path, monkeypatch):
    cache = tmp_path / "executions_cache.json"
    monkeypatch.setattr(executions, "_CACHE_PATH", cache)
    monkeypatch.setattr(executions, "_tcp_port_open", lambda *_args: True)
    monkeypatch.setattr(executions, "_ensure_thread_event_loop", lambda: None)

    class Broker:
        def connect(self, *_args, **kwargs):
            assert kwargs["readonly"] is True

        def reqExecutions(self, _filter):
            return []

        def disconnect(self):
            pass

    monkeypatch.setitem(sys.modules, "ib_insync", SimpleNamespace(IB=Broker, ExecutionFilter=SimpleNamespace))

    snapshot = executions.read_executions({"ibkr": {"enabled": True, "ports": [4001]}})

    assert snapshot.source == "tws"
    assert json.loads(cache.read_text()) == snapshot.to_dict()
    assert cache.name not in {path.split("/")[-1] for path in business_paths("2026-05-29")}


def test_execution_summary_does_not_identify_consumed_fill_records():
    first = executions.ExecutionSnapshot(
        records=[executions.ExecutionRecord(
            exec_id="synthetic-fill", symbol="MSTR", side="BOT", shares=1.0, price=100.0,
            time="2026-05-29T12:00:00+00:00", account="A2-SYNTHETIC",
        )],
        sync_time="2026-05-30T12:00:00+00:00",
    ).to_dict()
    second = json.loads(json.dumps(first))
    second["records"][0]["shares"] = 2.0

    assert first != second
    assert pipeline._execution_snapshot_summary(first) == pipeline._execution_snapshot_summary(second)


@pytest.mark.parametrize("reader", ["positions", "executions"])
def test_broker_error_handlers_do_not_propagate_arbitrary_read_exceptions(tmp_path, monkeypatch, reader):
    def fail(_config):
        raise OSError("synthetic capture storage failure")

    if reader == "positions":
        monkeypatch.setattr(positions, "read_positions", fail)
        result = pipeline._ibkr_payload({"ibkr": {"enabled": True}}, {}, {})
        assert result == {"error": "synthetic capture storage failure", "source": "unavailable"}
    else:
        monkeypatch.setattr(executions, "read_executions", fail)
        result = pipeline._execution_sync(
            {"ibkr": {"enabled": True}}, tmp_path / "state.sqlite", {},
            {"source": "tws", "sync_time": "2026-05-30T12:00:00+00:00"}, "2026-05-29", True,
        )
        assert result["status"] == "ERROR"
        assert result["reason"] == "synthetic capture storage failure"


@pytest.mark.parametrize("reader", ["positions", "executions"])
def test_v2_business_rollback_does_not_restore_unregistered_broker_cache(tmp_path, monkeypatch, reader):
    data = tmp_path / "data"
    archive = data / "archive"
    archive.mkdir(parents=True)
    cache = data / f"{reader}_cache.json"
    cache.write_text('{"before": true}')
    if reader == "positions":
        monkeypatch.setattr(positions, "_SNAPSHOT_PATH", cache)
        snapshot = _position_snapshot()
        save = positions._save_snapshot
    else:
        monkeypatch.setattr(executions, "_CACHE_PATH", cache)
        snapshot = executions.ExecutionSnapshot(sync_time="2026-05-30T12:00:00+00:00", source="tws")
        save = executions._save_cache
    capture_id = "a" * 32
    capture = archive / "decision_inputs" / capture_id
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with pytest.raises(RuntimeError, match="synthetic post-read failure"):
            with score_run_transaction(
                archive, [data / path for path in sorted(business_paths("2026-05-29"))],
                metadata={"as_of": "2026-05-29", "run_type": "scheduled", "shadow": False},
                evidence_artifacts=[capture / "manifest.json", capture / "broker.json"],
                capture_id=capture_id, _lease=lease,
            ) as transaction:
                save(snapshot)
                raise RuntimeError("synthetic post-read failure")

    assert load_score_run_transaction(archive, transaction.run_id)["status"] == "ROLLED_BACK"
    assert json.loads(cache.read_text()) == snapshot.to_dict()
    assert not any((data / path).exists() for path in business_paths("2026-05-29"))
