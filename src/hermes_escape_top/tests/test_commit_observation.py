"""The commit writer issues an observation outside the scoring artifacts."""
from __future__ import annotations

import hashlib
import json
import os
import select
import signal
import subprocess
import sys

import pytest

from hermes_escape_top import pipeline
from hermes_escape_top.core.data import run_transaction
from hermes_escape_top.core.reporting.broker_publication_status import read_broker_publication_status
from hermes_escape_top.core.safe_io import assert_pipeline_lease, pipeline_lock
from test_a2_production_capture import capture_root as capture_root
from test_broker_input_capture import broker_run as broker_run
from test_score_transaction_v2 import AS_OF, CAPTURE_ID, _finalize, _paths


def test_writer_observes_exact_committed_bytes_under_the_current_lease(tmp_path):
    archive, business, evidence = _paths(tmp_path)
    observations = []
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        def observe(value):
            assert_pipeline_lease(lease, path=archive / ".pipeline.lock")
            path = archive / f".score_run_transactions/runs/{value['run_id']}/manifest.json"
            assert value["journal_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
            assert json.loads(path.read_bytes())["status"] == "COMMITTED"
            observations.append(value)

        with run_transaction.score_run_transaction(
            archive, business, metadata={"as_of": AS_OF, "run_type": "scheduled", "shadow": False},
            _lease=lease, evidence_artifacts=evidence, capture_id=CAPTURE_ID,
            commit_observer=observe,
        ) as transaction:
            assert observations == []
            for path in business:
                path.write_bytes(b"committed business")
            _finalize(transaction, evidence, lease)
    record = run_transaction.load_score_run_transaction(archive, transaction.run_id)
    assert observations == [{
        "schema_version": "hermes-score-commit-observation-v1",
        "protocol": "recoverable-journal-v2",
        "run_id": transaction.run_id, "capture_id": CAPTURE_ID, "as_of": AS_OF,
        "decision_id": "decision-fixture", "input_hash": "b" * 64,
        "journal_sha256": hashlib.sha256((archive / f".score_run_transactions/runs/{transaction.run_id}/manifest.json").read_bytes()).hexdigest(),
        "committed_at": record["committed_at"],
    }]
    assert "commit_observation" not in record


@pytest.mark.parametrize("failure", ["body", "validation", "before_publish", "after_publish", "unknown"])
def test_no_observation_is_issued_on_failed_or_uncertain_commit(tmp_path, monkeypatch, failure):
    archive, business, evidence = _paths(tmp_path)
    observations = []
    original = run_transaction._write_manifest

    def write(root, record):
        if record["status"] == "COMMITTED":
            if failure in {"after_publish", "unknown"}:
                original(root, record)
            if failure == "unknown":
                (root / f".score_run_transactions/runs/{record['run_id']}/manifest.json").write_text("{")
            raise OSError("injected commit failure")
        return original(root, record)

    if failure in {"before_publish", "after_publish", "unknown"}:
        monkeypatch.setattr(run_transaction, "_write_manifest", write)
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with pytest.raises((OSError, RuntimeError, ValueError)):
            with run_transaction.score_run_transaction(
                archive, business, metadata={"as_of": AS_OF, "run_type": "scheduled", "shadow": False},
                _lease=lease, evidence_artifacts=evidence, capture_id=CAPTURE_ID,
                commit_observer=observations.append,
            ) as transaction:
                for path in business:
                    path.write_bytes(b"new business")
                if failure == "body":
                    raise RuntimeError("injected body failure")
                if failure != "validation":
                    _finalize(transaction, evidence, lease)
    assert observations == []
    if failure != "unknown":
        record = run_transaction.load_score_run_transaction(archive, transaction.run_id)
        assert record["status"] == ("COMMITTED" if failure == "after_publish" else "ROLLED_BACK")
    if failure in {"after_publish", "unknown"}:
        assert all(path.read_bytes() == b"new business" for path in business)
    else:
        assert all(not path.exists() for path in business)


@pytest.mark.parametrize("failure", ["observer", "cleanup"])
def test_post_commit_observer_or_cleanup_failure_does_not_rewind(tmp_path, monkeypatch, failure):
    archive, business, evidence = _paths(tmp_path)
    observations = []

    def observe(value):
        observations.append(value)
        if failure == "observer":
            raise OSError("injected observer failure")

    if failure == "cleanup":
        def fail_cleanup(_path):
            raise OSError("injected cleanup failure")
        monkeypatch.setattr(run_transaction, "_clear_active", fail_cleanup)
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with pytest.raises(OSError, match=f"injected {failure} failure"):
            with run_transaction.score_run_transaction(
                archive, business, metadata={"as_of": AS_OF, "run_type": "scheduled", "shadow": False},
                _lease=lease, evidence_artifacts=evidence, capture_id=CAPTURE_ID, commit_observer=observe,
            ) as transaction:
                for path in business:
                    path.write_bytes(b"new business")
                _finalize(transaction, evidence, lease)
    assert len(observations) == 1
    assert all(path.read_bytes() == b"new business" for path in business)
    assert all(path.is_file() for path in evidence)
    assert run_transaction.load_score_run_transaction(archive, transaction.run_id)["status"] == "COMMITTED"


def test_pipeline_exports_observation_without_putting_it_in_business_payload(broker_run):
    observations = []
    payload = pipeline.score_pipeline(
        AS_OF, config_path=broker_run.config_path, include_ibkr=False, run_type="scheduled",
        capture_inputs=True, commit_observer=observations.append,
    )
    assert len(observations) == 1
    observed = observations[0]
    assert observed["run_id"] == payload["persistence"]["run_id"]
    assert observed["capture_id"] == payload["persistence"]["capture_id"]
    assert observed["decision_id"] == payload["decision_evidence"]["decision_id"]
    assert observed["input_hash"] == payload["input_hash"]
    assert "commit_observation" not in payload
    assert set(payload["persistence"]) == {"protocol", "run_id", "capture_id", "recovered_run_id"}
    audit = json.loads((broker_run.archive / "audit_log.jsonl").read_text().splitlines()[-1])["payload"]
    assert "commit_observation" not in audit
    report = read_broker_publication_status(
        archive_dir=broker_run.archive, run_id=observed["run_id"],
        expected_journal_sha256=observed["journal_sha256"],
        decision_id=observed["decision_id"], input_hash=observed["input_hash"],
    )
    assert report["business_status"] == "COMMITTED"
    assert report["status"] == "INFO"


@pytest.mark.parametrize("mode", ["v1", "shadow", "manual"])
def test_observation_requires_scheduled_nonshadow_v2_before_any_journal_write(tmp_path, mode):
    archive, business, evidence = _paths(tmp_path)
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with pytest.raises(ValueError, match="requires non-shadow scheduled v2"):
            run_transaction.score_run_transaction(
                archive, business,
                metadata={"as_of": AS_OF, "run_type": "manual_rerun" if mode == "manual" else "scheduled",
                          "shadow": mode == "shadow"},
                _lease=lease, commit_observer=lambda _: None,
                **({"evidence_artifacts": evidence, "capture_id": CAPTURE_ID} if mode != "v1" else {}),
            )
    assert not (archive / ".score_run_transactions").exists()


_KILLED_COMMIT = '''
import json,os,socket,sys
from pathlib import Path
from hermes_escape_top.core.data import run_transaction as module
from hermes_escape_top.core.safe_io import pipeline_lock
from test_score_transaction_v2 import AS_OF,CAPTURE_ID,_paths,_finalize
socket.socket.connect = lambda *_: (_ for _ in ()).throw(RuntimeError("network forbidden"))
archive,business,evidence = _paths(Path(sys.argv[1]))
phase = sys.argv[2]
(archive/"run_receipt.json").write_text(json.dumps({"status":"RUNNING","as_of":AS_OF}))
original = module._write_manifest
def checkpoint(value):
    print(json.dumps({"pid":os.getpid(),**value}),flush=True)
    sys.stdin.readline()
def write(root,value):
    digest = original(root,value)
    if value["status"] == "COMMITTED" and phase == "before_observation":
        checkpoint({"run_id":value["run_id"],"observation":None})
    return digest
module._write_manifest = write
with pipeline_lock(path=archive/".pipeline.lock") as lease:
    with module.score_run_transaction(
        archive,business,metadata={"as_of":AS_OF,"run_type":"scheduled","shadow":False},
        _lease=lease,evidence_artifacts=evidence,capture_id=CAPTURE_ID,
        commit_observer=lambda value: checkpoint({"run_id":value["run_id"],"observation":value}),
    ) as transaction:
        for path in business: path.write_bytes(b"committed business")
        _finalize(transaction,evidence,lease)
'''


@pytest.mark.parametrize("phase", ["before_observation", "after_observation"])
def test_sigkill_does_not_fabricate_a_finished_receipt_or_rewind_commit(tmp_path, phase):
    child = subprocess.Popen(
        [sys.executable, "-c", _KILLED_COMMIT, str(tmp_path), phase],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert select.select([child.stdout], [], [], 20)[0], "writer did not reach commit checkpoint"
        line = child.stdout.readline()
        assert line, child.stderr.read()
        checkpoint = json.loads(line)
        os.kill(child.pid, signal.SIGKILL)
        child.wait(timeout=10)
        assert child.returncode == -signal.SIGKILL
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=10)
    archive = tmp_path / "data/archive"
    journal = archive / f".score_run_transactions/runs/{checkpoint['run_id']}/manifest.json"
    before = journal.read_bytes()
    observation = checkpoint["observation"]
    if phase == "before_observation":
        assert observation is None
    else:
        assert observation["journal_sha256"] == hashlib.sha256(before).hexdigest()
    assert json.loads((archive / "run_receipt.json").read_bytes())["status"] == "RUNNING"
    recovered = subprocess.run([
        sys.executable, "-c",
        "import os,sys; from pathlib import Path; "
        "from hermes_escape_top.core.safe_io import pipeline_lock; "
        "from hermes_escape_top.core.data.run_transaction import recover_incomplete_score_run; "
        "archive=Path(sys.argv[1]);\n"
        "with pipeline_lock(path=archive/'.pipeline.lock') as lease: "
        "assert recover_incomplete_score_run(archive,_lease=lease) is None\nprint(os.getpid())",
        str(archive),
    ], capture_output=True, text=True, check=True, timeout=20)
    assert int(recovered.stdout) not in {checkpoint["pid"], os.getpid()}
    assert journal.read_bytes() == before
    assert json.loads(before)["status"] == "COMMITTED"
    assert not (archive / ".score_run_transactions/active.json").exists()
