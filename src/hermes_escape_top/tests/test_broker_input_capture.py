"""Broker capture uses synthetic responses and isolated cache targets."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from types import SimpleNamespace

import pytest

from hermes_escape_top import pipeline
from hermes_escape_top.config import load_config, resolve_path
from hermes_escape_top.core.data.manifest import write_manifest
from hermes_escape_top.core.data.run_transaction import (
    PersistenceRecoveryError, load_score_run_transaction, pending_score_run_transaction, score_run_transaction,
)
from hermes_escape_top.core.data.transaction_evidence import business_paths
from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.data.state_store import latest_execution_confirmations, record_execution_confirmation
from hermes_escape_top.core.reentry.plan import build_reentry_plan
from hermes_escape_top.core.reporting.broker_capture import BrokerCapture
from hermes_escape_top.core.safe_io import pipeline_lock
from hermes_escape_top.core.scoring.result import ScoreResult
from hermes_escape_top.ibkr import executions, positions
from test_a2_production_capture import capture_root as capture_root


def test_position_read_can_defer_cache_without_losing_response(tmp_path, monkeypatch):
    cache = tmp_path / "positions.json"
    cache.write_text('{"old": true}')
    monkeypatch.setattr(positions, "_SNAPSHOT_PATH", cache)
    broker = SimpleNamespace(
        accountValues=lambda: [SimpleNamespace(tag="NetLiquidation", value="100000", currency="USD")],
        managedAccounts=lambda: ["A2-SYNTHETIC"], positions=lambda: [],
    )
    snapshot = positions._read_from_tws(broker, {}, 992, publish_cache=False)
    assert snapshot.source == "tws"
    assert snapshot.net_liq == 100000.0
    assert cache.read_bytes() == b'{"old": true}'
    positions.publish_positions_cache(snapshot)
    assert json.loads(cache.read_bytes()) == snapshot.to_dict()


def test_execution_read_can_defer_cache_without_losing_fills(tmp_path, monkeypatch):
    cache = tmp_path / "executions.json"
    cache.write_text('{"old": true}')
    monkeypatch.setattr(executions, "_CACHE_PATH", cache)
    monkeypatch.setattr(executions, "_tcp_port_open", lambda *_args: True)
    monkeypatch.setattr(executions, "_ensure_thread_event_loop", lambda: None)

    class Broker:
        def connect(self, *_args, **kwargs):
            assert kwargs["readonly"] is True

        def reqExecutions(self, _filter):
            return [SimpleNamespace(
                contract=SimpleNamespace(symbol="SOXL", currency="USD"),
                execution=SimpleNamespace(execId="synthetic-fill", side="BOT", shares=12, price=42.5,
                                          time="2026-05-29T12:00:00+00:00", acctNumber="A2-SYNTHETIC"),
            )]

        def disconnect(self):
            pass

    monkeypatch.setitem(sys.modules, "ib_insync", SimpleNamespace(IB=Broker, ExecutionFilter=SimpleNamespace))
    snapshot = executions.read_executions({"ibkr": {"enabled": True}}, publish_cache=False)
    assert snapshot.records[0].shares == 12
    assert cache.read_bytes() == b'{"old": true}'
    executions.publish_executions_cache(snapshot)
    assert json.loads(cache.read_bytes()) == snapshot.to_dict()


@pytest.fixture
def broker_run(capture_root, tmp_path, monkeypatch):
    config = load_config()
    config["ibkr"]["enabled"] = True
    config["ibkr"]["executions"]["enabled"] = True
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    write_manifest(resolve_path(config, "history_dir"), capture_root / "data_manifest_latest.json")
    cache_paths = {"positions": tmp_path / "positions.json", "executions": tmp_path / "executions.json"}
    for path in cache_paths.values():
        path.write_text('{"old": true}')
    monkeypatch.setattr(positions, "_SNAPSHOT_PATH", cache_paths["positions"])
    monkeypatch.setattr(executions, "_CACHE_PATH", cache_paths["executions"])
    responses = {
        "positions": positions.PositionSnapshot(
            account_id="A2-SYNTHETIC", net_liq=100000, gross_position_value=2500, total_cash=97500,
            unrealized_pnl=123, realized_pnl=456, sync_time="2026-05-29T21:00:00+00:00", client_id=992,
            positions=[positions.PositionRecord("SOXL", "STK", 12, 42.5, 510)],
        ),
        "executions": executions.ExecutionSnapshot(
            sync_time="2026-05-29T21:00:00+00:00", client_id=1042,
            records=[executions.ExecutionRecord("synthetic-fill", "SOXL", "BOT", 12, 42.5,
                                                "2026-05-29T20:50:00+00:00", account="A2-SYNTHETIC")],
        ),
    }
    calls = []

    def reader(name):
        def read(_config, *, publish_cache=True):
            assert publish_cache is False
            calls.append(name)
            return responses[name]
        return read

    monkeypatch.setattr(positions, "read_positions", reader("positions"))
    monkeypatch.setattr(executions, "read_executions", reader("executions"))
    return SimpleNamespace(archive=capture_root, config_path=config_path, caches=cache_paths,
                           responses=responses, calls=calls)


def test_capture_records_full_broker_responses_and_defers_publication(broker_run, monkeypatch):
    def before_commit(checkpoint):
        if checkpoint == "signal_journal":
            assert all(path.read_bytes() == b'{"old": true}' for path in broker_run.caches.values())

    monkeypatch.setattr(pipeline, "_persistence_checkpoint", before_commit)
    for module, name in ((positions, "publish_positions_cache"), (executions, "publish_executions_cache")):
        publish = getattr(module, name)

        def after_commit(snapshot, publish=publish):
            manifests = list((broker_run.archive / ".score_run_transactions/runs").glob("*/manifest.json"))
            record = json.loads(manifests[0].read_bytes())
            assert record["status"] == "COMMITTED"
            assert pending_score_run_transaction(broker_run.archive) is None
            publish(snapshot)

        monkeypatch.setattr(module, name, after_commit)
    payload = pipeline.score_pipeline("2026-05-29", config_path=broker_run.config_path,
                                      include_ibkr=True, run_type="scheduled", capture_inputs=True)
    record = load_score_run_transaction(broker_run.archive, payload["persistence"]["run_id"])
    assert record["status"] == "COMMITTED"
    assert broker_run.calls == ["positions", "executions"]
    bundle = broker_run.archive / "decision_inputs" / payload["persistence"]["capture_id"]
    tape = json.loads((bundle / "broker.json").read_bytes())
    for name, response in broker_run.responses.items():
        assert tape["reads"][name]["snapshot"] == response.to_dict()
        assert json.loads(broker_run.caches[name].read_bytes()) == response.to_dict()
    assert json.loads((bundle / "payload.json").read_bytes()) == payload


@pytest.mark.parametrize("boundary", ["observe", "write", "commit"])
def test_capture_failure_never_publishes_broker_cache(broker_run, monkeypatch, boundary):
    def fail(*_args, **_kwargs):
        raise OSError("synthetic capture failure")

    if boundary == "observe":
        from hermes_escape_top.core.reporting.broker_capture import BrokerCapture
        monkeypatch.setattr(BrokerCapture, "observed", fail)
    elif boundary == "write":
        write = pipeline.RuntimeCapture._write

        def fail_tape(self, name, content):
            write(self, name, content)
            if name == "broker.json":
                fail()

        monkeypatch.setattr(pipeline.RuntimeCapture, "_write", fail_tape)
    else:
        from hermes_escape_top.core.data import run_transaction
        write = run_transaction._write_manifest

        def fail_commit(archive, record):
            if record["status"] == "COMMITTED":
                fail()
            write(archive, record)

        monkeypatch.setattr(run_transaction, "_write_manifest", fail_commit)

    with pytest.raises(OSError, match="synthetic capture failure"):
        pipeline.score_pipeline("2026-05-29", config_path=broker_run.config_path,
                                include_ibkr=True, run_type="scheduled", capture_inputs=True)
    assert all(path.read_bytes() == b'{"old": true}' for path in broker_run.caches.values())
    assert all(not (broker_run.archive.parent / path).exists() for path in business_paths("2026-05-29"))
    manifests = list((broker_run.archive / ".score_run_transactions/runs").glob("*/manifest.json"))
    assert len(manifests) == 1
    assert json.loads(manifests[0].read_bytes())["status"] == "ROLLED_BACK"
    assert not (broker_run.archive / "broker_cache_publications").exists()


def _run(broker_run, *, include_ibkr=True):
    return pipeline.score_pipeline("2026-05-29", config_path=broker_run.config_path,
                                   include_ibkr=include_ibkr, run_type="scheduled", capture_inputs=True)


def _tape(broker_run, payload):
    bundle = broker_run.archive / "decision_inputs" / payload["persistence"]["capture_id"]
    return json.loads((bundle / "broker.json").read_bytes())


def test_default_off_retains_eager_broker_cache_behavior(broker_run, monkeypatch):
    for module, name in ((positions, "positions"), (executions, "executions")):
        publish = positions.publish_positions_cache if name == "positions" else executions.publish_executions_cache

        def read(_config, *, publish_cache=True, name=name, publish=publish):
            assert publish_cache is True
            broker_run.calls.append(name)
            publish(broker_run.responses[name])
            return broker_run.responses[name]

        monkeypatch.setattr(module, f"read_{name}", read)

    def before_commit(checkpoint):
        if checkpoint == "signal_journal":
            assert all(json.loads(broker_run.caches[name].read_bytes()) == response.to_dict()
                       for name, response in broker_run.responses.items())

    monkeypatch.setattr(pipeline, "_persistence_checkpoint", before_commit)
    payload = pipeline.score_pipeline("2026-05-29", config_path=broker_run.config_path,
                                      include_ibkr=True, run_type="scheduled")
    assert payload["persistence"]["protocol"] == "recoverable-journal-v1"
    assert broker_run.calls == ["positions", "executions"]
    assert not (broker_run.archive / "decision_inputs").exists()
    assert not (broker_run.archive / "broker_cache_publications").exists()


def test_cache_publication_failure_is_auxiliary_not_business_rollback(broker_run, monkeypatch, caplog):
    def fail(_snapshot):
        raise OSError("synthetic cache full")

    monkeypatch.setattr(positions, "publish_positions_cache", fail)
    payload = _run(broker_run)
    run_id = payload["persistence"]["run_id"]
    assert load_score_run_transaction(broker_run.archive, run_id)["status"] == "COMMITTED"
    assert all((broker_run.archive.parent / path).exists() for path in business_paths("2026-05-29"))
    assert broker_run.caches["positions"].read_bytes() == b'{"old": true}'
    assert json.loads(broker_run.caches["executions"].read_bytes()) == broker_run.responses["executions"].to_dict()
    receipt = json.loads((broker_run.archive / "broker_cache_publications" / f"{run_id}.json").read_bytes())
    assert receipt["caches"]["positions"] == {"status": "FAILED", "error": "synthetic cache full"}
    assert receipt["caches"]["executions"]["status"] == "PUBLISHED"
    assert "synthetic cache full" in caplog.text
    bundle = broker_run.archive / "decision_inputs" / payload["persistence"]["capture_id"]
    assert json.loads((bundle / "payload.json").read_bytes()) == payload


@pytest.mark.parametrize("branch", ["excluded", "disabled", "execution_disabled", "snapshot", "unavailable", "no_match"])
def test_capture_records_read_and_skip_branches_without_claiming_live(broker_run, branch):
    config = json.loads(broker_run.config_path.read_bytes())
    if branch == "disabled":
        config["ibkr"]["enabled"] = False
    elif branch == "execution_disabled":
        config["ibkr"]["executions"]["enabled"] = False
    elif branch in {"snapshot", "unavailable"}:
        response = broker_run.responses["positions"]
        response.source = branch
        response.error = "synthetic gateway unavailable"
        response.snapshot_stale = True
        response.snapshot_age_seconds = 12345
    elif branch == "no_match":
        broker_run.responses["executions"].records = []
    broker_run.config_path.write_text(json.dumps(config))
    payload = _run(broker_run, include_ibkr=branch != "excluded")
    tape = _tape(broker_run, payload)
    expected_calls = {
        "excluded": [], "disabled": [], "execution_disabled": ["positions"],
        "snapshot": ["positions"], "unavailable": ["positions"], "no_match": ["positions", "executions"],
    }[branch]
    assert broker_run.calls == expected_calls
    for name in ("positions", "executions"):
        row = tape["reads"][name]
        if name in expected_calls:
            assert row["snapshot"] == broker_run.responses[name].to_dict()
            assert row["status"] == "RETURNED"
        else:
            assert row["status"] == "NOT_READ"
            assert row["reason"] and row["snapshot"] is None
        live = name in expected_calls and row["snapshot"]["source"] == "tws"
        assert (broker_run.caches[name].read_bytes() != b'{"old": true}') is live
    if branch == "no_match":
        assert payload["execution_sync"]["status"] == "NO_MATCH"
    assert tape["outcomes"] == {"positions": payload["ibkr"], "executions": payload["execution_sync"]}


@pytest.mark.parametrize("reader", ["positions", "executions"])
def test_broker_read_error_is_captured_without_fake_return(broker_run, monkeypatch, reader):
    def fail(_config, *, publish_cache):
        assert publish_cache is False
        broker_run.calls.append(reader)
        raise ConnectionError("synthetic read failed")

    monkeypatch.setattr(positions if reader == "positions" else executions, f"read_{reader}", fail)
    payload = _run(broker_run)
    row = _tape(broker_run, payload)["reads"][reader]
    assert row == {"status": "ERROR", "snapshot": None, "reason": None, "error": "synthetic read failed"}
    assert broker_run.caches[reader].read_bytes() == b'{"old": true}'
    if reader == "positions":
        assert payload["ibkr"]["source"] == "unavailable"
        assert broker_run.calls == ["positions"]
    else:
        assert payload["execution_sync"]["status"] == "ERROR"


def test_execution_fallback_is_complete_but_not_published_or_confirmed(broker_run):
    response = broker_run.responses["executions"]
    response.source = "snapshot"
    response.snapshot_stale = True
    response.error = "synthetic fallback"
    response.snapshot_age_seconds = 4567
    response.records.append(executions.ExecutionRecord(
        "second-fill", "SOXL", "SLD", 8, 40, "2026-05-29T20:55:00+00:00", account="A2-SYNTHETIC",
    ))
    payload = _run(broker_run)
    assert _tape(broker_run, payload)["reads"]["executions"]["snapshot"] == response.to_dict()
    assert payload["execution_sync"]["status"] == "DEGRADED"
    assert payload["execution_sync"]["latest_confirmations"] == {}
    assert broker_run.caches["executions"].read_bytes() == b'{"old": true}'


def test_response_mutation_after_consumption_rolls_back(broker_run, monkeypatch):
    def mutate(checkpoint):
        if checkpoint == "signal_journal":
            broker_run.responses["positions"].net_liq += 1

    monkeypatch.setattr(pipeline, "_persistence_checkpoint", mutate)
    with pytest.raises(ValueError, match="broker response changed after consumption"):
        _run(broker_run)
    assert all(path.read_bytes() == b'{"old": true}' for path in broker_run.caches.values())
    assert all(not (broker_run.archive.parent / path).exists() for path in business_paths("2026-05-29"))


@pytest.mark.parametrize("boundary", ["unknown_commit", "committed_cleanup"])
def test_incomplete_transaction_exit_never_publishes_cache(broker_run, monkeypatch, boundary):
    from hermes_escape_top.core.data import run_transaction
    if boundary == "committed_cleanup":
        def fail(_path):
            raise OSError("synthetic cleanup failure")
        monkeypatch.setattr(run_transaction, "_clear_active", fail)
        error, message = OSError, "synthetic cleanup failure"
    else:
        write = run_transaction._write_manifest
        read = run_transaction.load_score_run_transaction

        def fail_after_commit(archive, record):
            write(archive, record)
            if record["status"] == "COMMITTED":
                raise OSError("synthetic commit ambiguity")

        def unreadable_commit(archive, run_id):
            record = read(archive, run_id)
            if record["status"] == "COMMITTED":
                raise OSError("synthetic journal read failure")
            return record

        monkeypatch.setattr(run_transaction, "_write_manifest", fail_after_commit)
        monkeypatch.setattr(run_transaction, "load_score_run_transaction", unreadable_commit)
        error, message = PersistenceRecoveryError, "commit outcome unknown"
    with pytest.raises(error, match=message):
        _run(broker_run)
    assert all(path.read_bytes() == b'{"old": true}' for path in broker_run.caches.values())
    assert all((broker_run.archive.parent / path).exists() for path in business_paths("2026-05-29"))
    assert not (broker_run.archive / "broker_cache_publications").exists()


def test_cache_receipt_failure_does_not_rollback_committed_state(broker_run, monkeypatch, caplog):
    from hermes_escape_top.core.reporting import broker_capture

    def fail(*_args):
        raise OSError("synthetic receipt full")

    monkeypatch.setattr(broker_capture, "atomic_write_json", fail)
    payload = _run(broker_run)
    assert load_score_run_transaction(broker_run.archive, payload["persistence"]["run_id"])["status"] == "COMMITTED"
    assert not list((broker_run.archive / "broker_cache_publications").glob("*.json"))
    assert "receipt unavailable: synthetic receipt full" in caplog.text
    assert all(json.loads(broker_run.caches[name].read_bytes()) == response.to_dict()
               for name, response in broker_run.responses.items())


def test_cache_target_change_is_reported_not_written(broker_run, monkeypatch, tmp_path):
    other = tmp_path / "unexpected.json"

    def change(checkpoint):
        if checkpoint == "signal_journal":
            monkeypatch.setattr(positions, "_SNAPSHOT_PATH", other)

    monkeypatch.setattr(pipeline, "_persistence_checkpoint", change)
    payload = _run(broker_run)
    receipt = json.loads((broker_run.archive / "broker_cache_publications" /
                          f'{payload["persistence"]["run_id"]}.json').read_bytes())
    assert receipt["caches"]["positions"]["status"] == "FAILED"
    assert broker_run.caches["positions"].read_bytes() == b'{"old": true}'
    assert not other.exists()


@pytest.mark.parametrize("name", ["positions", "executions"])
def test_explicit_publisher_rejects_non_live_response(broker_run, name):
    response = broker_run.responses[name]
    response.source = "snapshot"
    publish = positions.publish_positions_cache if name == "positions" else executions.publish_executions_cache
    with pytest.raises(ValueError, match="live"):
        publish(response)
    assert broker_run.caches[name].read_bytes() == b'{"old": true}'


def test_cache_publication_rejects_pending_transaction_and_invalid_lease(broker_run):
    capture = BrokerCapture(True)
    capture.observed("positions", broker_run.responses["positions"])
    capture.observed("executions", broker_run.responses["executions"])
    with pipeline_lock(path=broker_run.archive / ".pipeline.lock") as lease:
        with pytest.raises(RuntimeError, match="abort uncommitted probe"):
            with score_run_transaction(broker_run.archive, [], metadata={}, _lease=lease) as transaction:
                with pytest.raises(RuntimeError, match="invalid pipeline lease"):
                    capture.publish(transaction, _lease=None)
                with pytest.raises(ValueError, match="matching COMMITTED capture"):
                    capture.publish(transaction, _lease=lease)
                raise RuntimeError("abort uncommitted probe")
    assert all(path.read_bytes() == b'{"old": true}' for path in broker_run.caches.values())


def test_cache_publication_rejects_committed_transaction_without_capture(broker_run):
    capture = BrokerCapture(True)
    capture.observed("positions", broker_run.responses["positions"])
    capture.observed("executions", broker_run.responses["executions"])
    with pipeline_lock(path=broker_run.archive / ".pipeline.lock") as lease:
        with score_run_transaction(broker_run.archive, [], metadata={}, _lease=lease) as transaction:
            pass
        with pytest.raises(ValueError, match="matching COMMITTED capture"):
            capture.publish(transaction, _lease=lease)
    assert all(path.read_bytes() == b'{"old": true}' for path in broker_run.caches.values())


@pytest.mark.parametrize("tranche", ["T1", "T2"])
def test_successful_confirmation_replays_full_tape_in_independent_process(
    broker_run, tmp_path, tranche,
):
    import pandas as pd

    as_of = date(2026, 5, 29)
    radar = SymbolSnapshot("SOXX", as_of, {
        name: Field(name, value, "synthetic-market", as_of)
        for name, value in {"close": 102.0, "ema20": 100.0, "macd": 0.2, "macd_signal": 0.1}.items()
    })
    history = pd.DataFrame({"Close": [100.0] * 20}, index=pd.date_range("2026-05-01", periods=20))
    config = load_config(broker_run.config_path)
    plan = build_reentry_plan(
        "SOXL", ScoreResult("SOXL", as_of), {"SOXX": radar}, {"SOXX": history}, config,
        days_since_last_sell=999, t1_active=tranche == "T2",
    )
    assert plan.eligible and plan.tranche == tranche
    state = tmp_path / "confirmation.sqlite"
    replay = tmp_path / "replay.sqlite"
    if tranche == "T2":
        for path in (state, replay):
            record_execution_confirmation(path, symbol="SOXL", tranche="T1",
                                          confirmed_at="2026-05-28T21:00:00+00:00")
    capture = BrokerCapture(True)
    capture.skipped("positions", "confirmation-stage probe does not read positions")
    result = pipeline._execution_sync(
        config, state, {"SOXL": plan}, {"source": "tws", "sync_time": "2026-05-29T21:00:00+00:00"},
        as_of.isoformat(), True, broker=capture,
    )
    assert result["status"] == "OK" and result["inserted_count"] == 1
    raw = capture.tape({"ibkr": {}, "execution_sync": result})["reads"]["executions"]["snapshot"]
    assert raw == broker_run.responses["executions"].to_dict()
    script = '''
import json, os, socket, sys
from pathlib import Path
from hermes_escape_top import pipeline
from hermes_escape_top.ibkr import executions
from hermes_escape_top.core.data.state_store import latest_execution_confirmations
from hermes_escape_top.core.reentry.plan import ReentryPlan
def deny(*args, **kwargs):
    raise AssertionError("replay attempted network")
socket.socket.connect = deny
socket.create_connection = deny
data = json.load(sys.stdin)
calls = []
def read(config, *, publish_cache=True):
    assert publish_cache is True
    calls.append("executions")
    return executions.ExecutionSnapshot.from_dict(data["snapshot"])
executions.read_executions = read
result = pipeline._execution_sync(
    data["config"], Path(sys.argv[1]), {"SOXL": ReentryPlan(**data["plan"])},
    {"source": "tws", "sync_time": "2026-05-29T21:00:00+00:00"}, "2026-05-29", True)
assert result["status"] == "OK" and result["inserted_count"] == 1
assert calls == ["executions"]
print(json.dumps({"pid": os.getpid(), "latest": latest_execution_confirmations(Path(sys.argv[1]))}))
'''
    completed = subprocess.run(
        [sys.executable, "-c", script, str(replay)], check=True, capture_output=True, text=True,
        input=json.dumps({"config": config, "plan": plan.to_dict(), "snapshot": raw}),
    )
    restored = json.loads(completed.stdout)
    import os
    assert restored["pid"] != os.getpid()
    expected = latest_execution_confirmations(state)
    assert restored["latest"] == expected
    assert expected["SOXL"]["tranche"] == tranche and expected["SOXL"]["source"] == "ibkr_executions"
    assert expected["SOXL"]["payload"]["shares"] == 12.0
    assert broker_run.calls == ["executions"]
    assert all(path.read_bytes() == b'{"old": true}' for path in broker_run.caches.values())
