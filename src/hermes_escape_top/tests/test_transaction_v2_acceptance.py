from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from hermes_escape_top.core.data.run_transaction import load_score_run_transaction
from hermes_escape_top.core.safe_io import pipeline_lock
from test_morning_acceptance import _load_module
from test_score_transaction_v2 import AS_OF, _context, _finalize, _paths

ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = ROOT / "src/hermes_escape_top/core/data/transaction_evidence.py"


def _committed(tmp_path):
    archive, business, evidence = _paths(tmp_path)
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with _context(archive, business, evidence, lease) as transaction:
            for path in business:
                path.write_bytes(b"business fixture")
            _finalize(transaction, evidence, lease)
    audit = {"as_of": AS_OF, "input_hash": "b" * 64,
             "decision_evidence": {"decision_id": "decision-fixture"},
             "persistence": {"protocol": "recoverable-journal-v2", "run_id": transaction.run_id}}
    return archive, evidence, audit, transaction


def test_acceptance_reads_v2_external_anchor_and_keeps_seven_business_files_exact(tmp_path):
    archive, _evidence, audit, _transaction = _committed(tmp_path)
    before = {path: path.read_bytes() for path in archive.rglob("*") if path.is_file()}
    result = _load_module()._collect_transaction(archive, audit, require_soft_snapshot=True, validator_path=VALIDATOR)
    assert result["status"] == "PASS", result
    assert "artifacts=7" in result["detail"]
    assert "evidence=2" in result["detail"]
    assert {path: path.read_bytes() for path in archive.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("case", ["unknown_role", "duplicate", "wrong_path", "unknown_schema", "wrong_decision",
                                 "wrong_hash", "missing_validator", "manifest_sha", "bad_file", "extra_file",
                                 "missing_file", "symlink", "not_committed", "residual_active",
                                 "journal_root_link", "runs_link", "manifest_link"])
def test_v2_acceptance_fails_closed_for_unbound_or_malformed_evidence(tmp_path, case):
    archive, evidence, audit, transaction = _committed(tmp_path)
    record = load_score_run_transaction(archive, transaction.run_id)
    validator = VALIDATOR
    if case == "unknown_role":
        record["artifacts"][-1]["role"] = "UNKNOWN"
    elif case == "duplicate":
        record["artifacts"].append(copy.deepcopy(record["artifacts"][-1]))
    elif case == "wrong_path":
        record["artifacts"][0]["path"] = "wrong/hermes_state.sqlite"
    elif case == "unknown_schema":
        record["schema_version"] = "hermes-score-run-transaction-v999"
    elif case == "wrong_decision":
        audit["decision_evidence"]["decision_id"] = "another-decision"
    elif case == "wrong_hash":
        audit["input_hash"] = "c" * 64
    elif case == "missing_validator":
        validator = tmp_path / "missing.py"
    elif case == "manifest_sha":
        record["input_binding"]["manifest_sha256"] = "0" * 64
    elif case == "bad_file":
        evidence[-1].chmod(0o600)
        evidence[-1].write_bytes(b"tampered")
    elif case == "extra_file":
        (evidence[0].parent / "unregistered.txt").write_text("unexpected")
    elif case == "missing_file":
        evidence[-1].unlink()
    elif case == "symlink":
        target = tmp_path / "matching-bytes"
        target.write_bytes(evidence[-1].read_bytes())
        evidence[-1].unlink()
        evidence[-1].symlink_to(target)
    elif case == "not_committed":
        record["status"] = "PENDING"
    elif case in {"journal_root_link", "runs_link", "manifest_link"}:
        journal = archive / ".score_run_transactions"
        target = {"journal_root_link": journal, "runs_link": journal / "runs",
                  "manifest_link": journal / f"runs/{transaction.run_id}/manifest.json"}[case]
        outside = tmp_path / "outside-journal"
        target.rename(outside)
        target.symlink_to(outside, target_is_directory=outside.is_dir())
    else:
        (archive / ".score_run_transactions/active.json").write_text("{}")
    (archive / f".score_run_transactions/runs/{transaction.run_id}/manifest.json").write_text(json.dumps(record))
    result = _load_module()._collect_transaction(archive, audit, require_soft_snapshot=True, validator_path=validator)
    assert result["status"] == "FAIL", result


def test_v2_evidence_validator_runs_under_system_python_without_site_packages(tmp_path):
    archive, _evidence, _audit, transaction = _committed(tmp_path)
    manifest = archive / f".score_run_transactions/runs/{transaction.run_id}/manifest.json"
    program = """
import importlib.util, json, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("validator", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.validate_input_evidence(json.loads(Path(sys.argv[2]).read_text()), Path(sys.argv[3]))
print("STDLIB_VALIDATOR_OK")
"""
    result = subprocess.run(["/usr/bin/python3", "-S", "-c", program, str(VALIDATOR), str(manifest), str(archive.parent)],
                            capture_output=True, text=True, check=True, timeout=10)
    assert result.stdout.strip() == "STDLIB_VALIDATOR_OK"
