"""Post-commit auxiliary publication must not undo the seven business roles."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts/verify_a2_publication_crash.py"


def _run(tmp_path, phase):
    output = tmp_path / f"{phase}.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--phase", phase, "--output", str(output)],
        cwd=REPO, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_bytes())
    assert report["status"] == "PASS"
    assert report["business_status"] == "COMMITTED"
    assert report["business_roles_compared"] == 7
    assert report["business_matches_commit"] is True
    assert report["business_changed_before_publication"] is True
    assert report["journal_unchanged"] is True
    assert report["capture_evidence_preserved"] is True
    assert report["committed_inputs_restored"] is True
    assert report["active_absent"] is True
    assert report["recovery"] is None
    assert report["auxiliary_unchanged_during_recovery"] is True
    assert report["wal_only_before_capture"] is True
    assert report["reader_calls"] == {"positions": 1, "executions": 1}
    assert report["recovery_reader_calls"] == {"positions": 0, "executions": 0}
    assert report["network_attempts"] == 0
    assert len(set(report["worker_pids"])) == 3
    assert report["cache_temporary_files"] == []
    assert report["cache_modes"] == {"positions": 0o600, "executions": 0o600}
    assert report["receipt_mode"] in (None, 0o644)
    assert report["receipt_directory_mode"] in (None, 0o700)
    assert report["registered_business_roles"] == 7
    assert report["publication_lease_checked"] is True
    assert report["official_receipt_unchanged"] is True
    assert report["natural_run_evidence"] is False
    assert report["deployment"] == "HOLD"
    assert report["a2"] == "OPEN"
    return report


def test_position_replace_error_preserves_business_and_reports_only_that_cache_failed(tmp_path):
    report = _run(tmp_path, "positions_error")
    assert report["cache_states"] == {"positions": "OLD", "executions": "NEW"}
    assert report["receipt"]["caches"]["positions"]["status"] == "FAILED"
    assert report["receipt"]["caches"]["executions"]["status"] == "PUBLISHED"
    assert report["injected_failures"] == ["positions"]
    assert report["receipt_matches_run"] is True
    assert report["writer_returncode"] == 0


def test_execution_replace_error_does_not_undo_the_published_position_cache(tmp_path):
    report = _run(tmp_path, "executions_error")
    assert report["cache_states"] == {"positions": "NEW", "executions": "OLD"}
    assert report["receipt"]["caches"]["positions"]["status"] == "PUBLISHED"
    assert report["receipt"]["caches"]["executions"]["status"] == "FAILED"
    assert report["injected_failures"] == ["executions"]
    assert report["receipt_matches_run"] is True


def test_receipt_replace_error_does_not_claim_disk_attestation_or_rollback_caches(tmp_path):
    report = _run(tmp_path, "receipt_error")
    assert report["cache_states"] == {"positions": "NEW", "executions": "NEW"}
    assert report["receipt"] is None
    assert report["receipt_matches_run"] is False
    assert report["injected_failures"] == ["receipt"]
    assert report["receipt_warning_observed"] is True
    assert all(row["status"] == "PUBLISHED" for row in report["returned_receipt"]["caches"].values())
    assert report["official_receipt_unchanged"] is True


def test_sigkill_before_publication_keeps_old_caches_without_retrying_committed_business(tmp_path):
    report = _run(tmp_path, "before_publish")
    assert report["writer_returncode"] == -signal.SIGKILL
    assert report["interruption_checkpoint"] == "before_publish"
    assert report["cache_states"] == {"positions": "OLD", "executions": "OLD"}
    assert report["receipt"] is None
    assert report["returned_receipt"] is None
    assert report["injected_failures"] == []


def test_sigkill_after_positions_leaves_a_visible_partial_auxiliary_group(tmp_path):
    report = _run(tmp_path, "after_positions")
    assert report["writer_returncode"] == -signal.SIGKILL
    assert report["interruption_checkpoint"] == "after_positions"
    assert report["cache_states"] == {"positions": "NEW", "executions": "OLD"}
    assert report["receipt"] is None
    assert report["receipt_matches_run"] is False


def test_sigkill_after_executions_does_not_invent_a_missing_publication_receipt(tmp_path):
    report = _run(tmp_path, "after_executions")
    assert report["writer_returncode"] == -signal.SIGKILL
    assert report["interruption_checkpoint"] == "after_executions"
    assert report["cache_states"] == {"positions": "NEW", "executions": "NEW"}
    assert report["receipt"] is None
    assert report["receipt_matches_run"] is False


def test_sigkill_after_receipt_preserves_the_matching_attestation_without_republication(tmp_path):
    report = _run(tmp_path, "after_receipt")
    assert report["writer_returncode"] == -signal.SIGKILL
    assert report["interruption_checkpoint"] == "after_receipt"
    assert report["cache_states"] == {"positions": "NEW", "executions": "NEW"}
    assert report["receipt_matches_run"] is True
    assert all(row["status"] == "PUBLISHED" for row in report["receipt"]["caches"].values())
    assert report["returned_receipt"] is None


def test_uninterrupted_publication_has_both_new_caches_and_a_matching_receipt(tmp_path):
    report = _run(tmp_path, "success")
    assert report["writer_returncode"] == 0
    assert report["interruption_checkpoint"] is None
    assert report["injected_failures"] == []
    assert report["cache_states"] == {"positions": "NEW", "executions": "NEW"}
    assert report["receipt_matches_run"] is True
    assert report["returned_receipt"] == report["receipt"]
    assert all(row["status"] == "PUBLISHED" for row in report["receipt"]["caches"].values())


@pytest.mark.parametrize("mode", ["capture", "recover"])
def test_worker_rejects_an_arbitrary_root_before_creating_data(tmp_path, mode):
    root = tmp_path / "arbitrary"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--worker", str(root), str(tmp_path / "config.json"), mode,
         "--phase", "positions_error"],
        cwd=REPO, env={**os.environ, "HERMES_DATA_DIR": str(root), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 1
    assert "worker requires the explicitly created publication rehearsal root" in result.stderr
    assert not root.exists()
