"""Current scoring results survive later wrapper failures for truthful diagnostics."""
from __future__ import annotations

import hashlib
import json

import pytest

from hermes_escape_top.core.data.run_transaction import load_score_run_transaction
from hermes_escape_top.core.data.transaction_evidence import business_paths
from hermes_escape_top.core.safe_io import pipeline_lock
from hermes_escape_top.scripts import run_daily_package as daily
from test_a2_production_capture import capture_root as capture_root
from test_broker_input_capture import broker_run as broker_run
from test_commit_observation_receipt import receipt_run as receipt_run
from test_score_transaction_v2 import AS_OF


_WRITE_HEALTH = daily._write_system_health_report


@pytest.fixture
def health_run(receipt_run, monkeypatch):
    monkeypatch.setattr(daily, "_write_system_health_report", _WRITE_HEALTH)
    monkeypatch.setattr(daily, "_system_health_generator_identity", lambda: {
        "generator_release_hash": "isolated-postcommit-fix", "generator_policy_sha256": "b" * 64,
    })
    root = daily._system_health_report_dir()
    root.mkdir(parents=True)
    (root / f"system_health_{AS_OF}.json").write_text(json.dumps({
        "as_of": AS_OF, "input_hash": "previous-input", "run_receipt": {"status": "OK"},
    }))
    (root / f"system_health_{AS_OF}.md").write_text("previous report\n")
    return receipt_run


def _business_bytes(archive):
    return {name: (archive.parent / name).read_bytes() for name in business_paths(AS_OF)}


def _assert_failed_commit(run, before, failed_step, *, capture=True):
    receipt = json.loads((run.archive / "run_receipt.json").read_bytes())
    payload = json.loads((run.archive / "audit_log.jsonl").read_text().splitlines()[-1])["payload"]
    record = load_score_run_transaction(run.archive, payload["persistence"]["run_id"])
    assert record["status"] == "COMMITTED"
    business = [row for row in record["artifacts"] if row["role"] == "BUSINESS"] if capture else record["artifacts"]
    assert len(business) == 7
    assert {row["path"] for row in business} == business_paths(AS_OF)
    assert _business_bytes(run.archive) == before
    assert not (run.archive / ".score_run_transactions/active.json").exists()
    assert receipt["status"] == "FAILED" and receipt["ok"] is False
    assert receipt["failed_step"] == failed_step
    if capture:
        observation = receipt["commit_observation"]
        journal = run.archive / f".score_run_transactions/runs/{observation['run_id']}/manifest.json"
        assert observation["journal_sha256"] == hashlib.sha256(journal.read_bytes()).hexdigest()
        assert observation["run_id"] == payload["persistence"]["run_id"]
        assert observation["capture_id"] == payload["persistence"]["capture_id"]
        assert observation["input_hash"] == payload["input_hash"]
        assert observation["decision_id"] == payload["decision_evidence"]["decision_id"]
    else:
        assert "commit_observation" not in receipt
        assert payload["persistence"]["protocol"] == "recoverable-journal-v1"
        assert not (run.archive / "decision_inputs").exists()
    return receipt, payload


def _assert_failed_current_report(run, before, failed_step, *, capture=True):
    receipt, payload = _assert_failed_commit(run, before, failed_step, capture=capture)
    path = daily._system_health_report_dir() / f"system_health_{AS_OF}.json"
    report = json.loads(path.read_bytes())
    assert report["input_hash"] == payload["input_hash"]
    assert report["decision_hash"] == payload["decision_evidence"]["decision_hash"]
    assert report["run_receipt"] == receipt
    assert report["health"]["level"] == "CRITICAL"
    assert next(row for row in report["audit_dimensions"] if row["id"] == "scheduled_receipt")["status"] == "FAIL"
    assert "FAILED" in path.with_suffix(".md").read_text()
    archived = list((path.parent / "system_health_runs").glob("*.json"))
    assert len(archived) == 1 and json.loads(archived[0].read_bytes()) == report
    return receipt, payload


@pytest.mark.parametrize("capture", [False, True])
@pytest.mark.parametrize("implicit_date", [False, True])
def test_translation_failure_writes_current_health_without_undoing_commit(
    health_run, monkeypatch, capture, implicit_date,
):
    before = {}
    error = OSError("synthetic translation failure after score commit")

    def fail(_payload):
        before.update(_business_bytes(health_run.archive))
        raise error

    monkeypatch.setattr(daily, "translate", fail)
    if implicit_date:
        health_run.args.as_of = None
        monkeypatch.setattr(daily, "_latest_available_as_of", lambda: AS_OF)
    with pipeline_lock(path=health_run.archive / ".pipeline.lock") as lease:
        with pytest.raises(OSError) as caught:
            daily._run_daily_with_receipt(health_run.args, _lease=lease, capture_inputs=capture)
    assert caught.value is error
    _assert_failed_current_report(health_run, before, "translate", capture=capture)


@pytest.mark.parametrize("capture", [False, True])
@pytest.mark.parametrize("failed_step,target", [
    ("artifact_write", "write_artifacts"),
    ("post_run_diff", "_post_run_diff"),
    ("state_commit", "commit_state"),
])
def test_later_wrapper_failure_keeps_commit_and_current_failed_health(
    health_run, monkeypatch, capture, failed_step, target,
):
    before = {}
    error = OSError(f"synthetic {failed_step} failure after score commit")

    def fail(*_args, **_kwargs):
        before.update(_business_bytes(health_run.archive))
        raise error

    monkeypatch.setattr(daily, target, fail)
    health_run.args.commit_state = failed_step == "state_commit"
    with pipeline_lock(path=health_run.archive / ".pipeline.lock") as lease:
        with pytest.raises(RuntimeError if failed_step == "state_commit" else OSError) as caught:
            daily._run_daily_with_receipt(health_run.args, _lease=lease, capture_inputs=capture)
    if failed_step == "state_commit":
        assert str(error) in str(caught.value)
        assert "state commit failed" in str(caught.value)
    else:
        assert caught.value is error
    _assert_failed_current_report(health_run, before, failed_step, capture=capture)


@pytest.mark.parametrize("capture", [False, True])
def test_secondary_health_failure_cannot_replace_original_wrapper_error(
    health_run, monkeypatch, capsys, capture,
):
    before = {}
    seen = []
    error = OSError("synthetic original artifact failure")
    report = daily._system_health_report_dir() / f"system_health_{AS_OF}.json"
    previous = report.read_bytes()

    def fail_artifact(*_args, **_kwargs):
        before.update(_business_bytes(health_run.archive))
        raise error

    def fail_health(payload, _as_of, receipt, **_kwargs):
        seen.append((payload, receipt))
        raise OSError("synthetic secondary health storage failure")

    monkeypatch.setattr(daily, "write_artifacts", fail_artifact)
    monkeypatch.setattr(daily, "_write_system_health_report", fail_health)
    with pipeline_lock(path=health_run.archive / ".pipeline.lock") as lease:
        with pytest.raises(OSError) as caught:
            daily._run_daily_with_receipt(health_run.args, _lease=lease, capture_inputs=capture)
    assert caught.value is error
    receipt, payload = _assert_failed_commit(health_run, before, "artifact_write", capture=capture)
    assert len(seen) == 1 and seen[0][0]["input_hash"] == payload["input_hash"]
    assert seen[0][1] == receipt
    assert report.read_bytes() == previous
    assert "synthetic secondary health storage failure" in capsys.readouterr().out


def test_missing_failed_receipt_does_not_manufacture_a_health_attestation(health_run, monkeypatch):
    before = {}
    error = OSError("synthetic original translation failure")
    report = daily._system_health_report_dir() / f"system_health_{AS_OF}.json"
    previous = report.read_bytes()
    write_json = daily._atomic_write_json

    def fail_translate(_payload):
        before.update(_business_bytes(health_run.archive))
        raise error

    def fail_receipt(path, value):
        if path == health_run.archive / "run_receipt.json" and value["status"] == "FAILED":
            raise OSError("synthetic receipt storage failure")
        write_json(path, value)

    monkeypatch.setattr(daily, "translate", fail_translate)
    monkeypatch.setattr(daily, "_atomic_write_json", fail_receipt)
    monkeypatch.setattr(daily, "_write_system_health_report",
                        lambda *_args, **_kwargs: pytest.fail("health cannot invent a missing FAILED receipt"))
    with pipeline_lock(path=health_run.archive / ".pipeline.lock") as lease:
        with pytest.raises(OSError) as caught:
            daily._run_daily_with_receipt(health_run.args, _lease=lease, capture_inputs=True)
    assert caught.value is error
    assert not (health_run.archive / "run_receipt.json").exists()
    payload = json.loads((health_run.archive / "audit_log.jsonl").read_text().splitlines()[-1])["payload"]
    assert load_score_run_transaction(health_run.archive, payload["persistence"]["run_id"])["status"] == "COMMITTED"
    assert _business_bytes(health_run.archive) == before
    assert report.read_bytes() == previous


def test_next_failure_before_score_does_not_reuse_the_previous_result(health_run, monkeypatch):
    with pipeline_lock(path=health_run.archive / ".pipeline.lock") as lease:
        daily._run_daily_with_receipt(health_run.args, _lease=lease, capture_inputs=True)
        report = daily._system_health_report_dir() / f"system_health_{AS_OF}.json"
        previous = report.read_bytes()
        audit = (health_run.archive / "audit_log.jsonl").read_bytes()

        def fail_score(*_args, **_kwargs):
            raise OSError("synthetic next invocation before result")

        monkeypatch.setattr(daily, "run_score_pipeline", fail_score)
        monkeypatch.setattr(daily, "_write_system_health_report",
                            lambda *_args, **_kwargs: pytest.fail("must not reuse the previous score"))
        with pytest.raises(OSError, match="synthetic next invocation before result"):
            daily._run_daily_with_receipt(health_run.args, _lease=lease, capture_inputs=True)
    receipt = json.loads((health_run.archive / "run_receipt.json").read_bytes())
    assert receipt["status"] == "FAILED" and receipt["failed_step"] == "score_pipeline"
    assert "commit_observation" not in receipt
    assert report.read_bytes() == previous
    assert (health_run.archive / "audit_log.jsonl").read_bytes() == audit


def test_unofficial_post_score_failure_does_not_publish_official_health(health_run, monkeypatch):
    health_run.args.run_type = "manual_rerun"
    report = daily._system_health_report_dir() / f"system_health_{AS_OF}.json"
    previous = report.read_bytes()
    reached = []

    def fail_translate(payload):
        reached.append(payload)
        raise OSError("synthetic unofficial translation failure")

    monkeypatch.setattr(daily, "translate", fail_translate)
    monkeypatch.setattr(daily, "_write_system_health_report",
                        lambda *_args, **_kwargs: pytest.fail("manual failure cannot publish official health"))
    with pipeline_lock(path=health_run.archive / ".pipeline.lock") as lease:
        with pytest.raises(OSError, match="synthetic unofficial translation failure"):
            daily._run_daily_with_receipt(health_run.args, _lease=lease)
    assert len(reached) == 1 and reached[0]["run_type"] == "manual_rerun"
    assert not (health_run.archive / "run_receipt.json").exists()
    assert report.read_bytes() == previous
