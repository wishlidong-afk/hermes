"""Real captured score-run interruption and isolated recovery, not power loss."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest


REPO = Path(__file__).resolve().parents[3]


def _rehearse(tmp_path, phase):
    output = tmp_path / f"{phase}.json"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/verify_a2_capture_crash.py"),
         "--phase", phase, "--output", str(output)],
        cwd=REPO, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(output.read_bytes())


def test_prepared_capture_sigkill_restores_seven_roles_in_another_process(tmp_path):
    report = _rehearse(tmp_path, "after_prepare")
    assert report["status"] == "PASS"
    assert report["interrupted_returncode"] == -signal.SIGKILL
    assert report["checkpoint"]["status"] == "PENDING"
    assert report["checkpoint"]["input_binding_present"] is False
    assert report["recovery_status"] == "RECOVERED_ROLLBACK"
    assert report["business_matches_before"] is True
    assert report["registered_business_roles"] == report["business_roles_compared"] == 7
    assert report["capture_evidence_removed"] is True
    assert report["active_absent"] is True
    assert report["wal_row_only_in_wal_before_capture"] is True
    assert report["network_attempts"] == 0
    assert len(set(report["worker_pids"])) == 3
    assert report["deployment"] == "HOLD"
    assert report["natural_run_evidence"] is False


def test_schema_mutation_sigkill_restores_the_actual_old_schema(tmp_path):
    report = _rehearse(tmp_path, "after_schema")
    assert report["interrupted_returncode"] == -signal.SIGKILL
    assert report["checkpoint"]["status"] == "PENDING"
    assert report["legacy_schema_fixture"] is True
    assert report["business_changed_at_checkpoint"] is True
    assert report["business_matches_before"] is True
    assert report["recovery_status"] == "RECOVERED_ROLLBACK"
    assert report["capture_evidence_removed"] is True
    assert report["active_absent"] is True
    assert report["network_attempts"] == 0


def test_partial_business_writes_sigkill_restores_all_old_rows_and_absences(tmp_path):
    report = _rehearse(tmp_path, "during_write")
    assert report["checkpoint"]["status"] == "PENDING"
    assert report["checkpoint"]["input_binding_present"] is False
    assert report["business_changed_at_checkpoint"] is True
    assert report["checkpoint"]["business"]["archive/audit_log.jsonl"] == (
        report["before"]["business"]["archive/audit_log.jsonl"]
    )
    assert report["business_matches_before"] is True
    assert report["recovery_status"] == "RECOVERED_ROLLBACK"
    assert report["capture_evidence_removed"] is True
    assert report["active_absent"] is True


def test_bound_but_uncommitted_capture_sigkill_removes_the_complete_evidence(tmp_path):
    report = _rehearse(tmp_path, "after_binding")
    assert report["checkpoint"]["status"] == "PENDING"
    assert report["checkpoint"]["input_binding_present"] is True
    assert report["checkpoint"]["all_evidence_present"] is True
    assert report["business_changed_at_checkpoint"] is True
    assert report["business_matches_before"] is True
    assert report["capture_evidence_removed"] is True
    assert report["recovery_status"] == "RECOVERED_ROLLBACK"
    assert report["active_absent"] is True


def test_sigkill_after_commit_preserves_business_evidence_and_external_anchor(tmp_path):
    report = _rehearse(tmp_path, "after_commit")
    assert report["interrupted_returncode"] == -signal.SIGKILL
    assert report["checkpoint"]["status"] == report["recovery_status"] == "COMMITTED"
    assert report["checkpoint"]["input_binding_present"] is True
    assert report["business_matches_before"] is False
    assert report["business_matches_checkpoint"] is True
    assert report["capture_evidence_removed"] is False
    assert report["capture_evidence_preserved"] is True
    assert report["committed_journal_unchanged"] is True
    assert report["committed_inputs_restored"] is True
    assert report["active_absent"] is True
    assert report["network_attempts"] == 0


def test_cleanup_exception_does_not_undo_the_already_committed_capture(tmp_path):
    report = _rehearse(tmp_path, "cleanup_error")
    assert report["interrupted_returncode"] == 1
    assert report["injected_cleanup_error_observed"] is True
    assert report["checkpoint"]["status"] == report["recovery_status"] == "COMMITTED"
    assert report["business_matches_checkpoint"] is True
    assert report["capture_evidence_preserved"] is True
    assert report["committed_journal_unchanged"] is True
    assert report["committed_inputs_restored"] is True
    assert report["active_absent"] is True


@pytest.mark.parametrize("mode", ["capture", "recover"])
def test_crash_worker_rejects_an_arbitrary_data_root_before_any_write(tmp_path, mode):
    root = tmp_path / "capture"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/verify_a2_capture_crash.py"), "--worker",
         str(root), str(tmp_path / "config.json"), mode, "--phase", "after_prepare"],
        cwd=REPO, env={**os.environ, "HERMES_DATA_DIR": str(root), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 1
    assert "explicitly created capture crash root" in result.stderr
    assert not root.exists()
