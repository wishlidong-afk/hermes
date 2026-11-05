from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_escape_top.core.safe_io import pipeline_lock
from test_runtime_retention import _module
from test_score_transaction_v2 import _context, _finalize, _paths


def test_completed_v2_anchor_survives_zero_count_and_capacity_limits(tmp_path: Path):
    module = _module()
    archive, business, evidence = _paths(tmp_path)
    with pipeline_lock(path=archive / ".pipeline.lock") as lease:
        with _context(archive, business, evidence, lease) as transaction:
            for path in business:
                path.write_bytes(b"business fixture")
            _finalize(transaction, evidence, lease)
    run = archive / ".score_run_transactions/runs" / transaction.run_id
    before = {path: path.read_bytes() for path in [run / "manifest.json", *evidence]}
    assert not (archive / ".score_run_transactions/active.json").exists()

    plan = module.build_prune_plan(
        live_root=tmp_path / "live", backup_root=tmp_path / "backups",
        archive_dir=archive, keep_transactions=0, max_transaction_bytes=0,
    )
    assert str(run) in plan["summary"]["score_transaction"]["protected"]
    assert not any(row["path"] == str(run) for row in plan["delete"])
    summary = plan["summary"]["score_transaction"]
    assert summary["protection_reasons"][str(run)] == "decision_input_evidence_anchor"
    assert summary["capacity_exceeded"] is True
    assert summary["retained_bytes"] == sum(path.stat().st_size for path in run.rglob("*") if path.is_file())
    result = module.apply_prune_plan(plan)
    assert result["deleted_count"] == 0
    assert all(path.read_bytes() == value for path, value in before.items())


@pytest.mark.parametrize("schema", [None, "hermes-score-run-transaction-v1"])
@pytest.mark.parametrize("marker", ["capture_id", "input_binding", "evidence_role"])
def test_legacy_label_does_not_allow_evidence_anchor_deletion(tmp_path: Path, schema, marker: str):
    module = _module()
    archive, _business, _evidence = _paths(tmp_path)
    run_id = "d" * 32
    run = archive / ".score_run_transactions/runs" / run_id
    run.mkdir(parents=True)
    payload = {"run_id": run_id, "status": "COMMITTED"}
    if schema is not None:
        payload["schema_version"] = schema
    if marker == "evidence_role":
        payload["artifacts"] = [{"role": "DECISION_INPUT_EVIDENCE"}]
    else:
        payload[marker] = None
    manifest = run / "manifest.json"
    manifest.write_text(json.dumps(payload))
    before = manifest.read_bytes()

    plan = module.build_prune_plan(
        live_root=tmp_path / "live", backup_root=tmp_path / "backups",
        archive_dir=archive, keep_transactions=0, max_transaction_bytes=0,
    )
    assert str(run) in plan["summary"]["score_transaction"]["protected"]
    assert plan["summary"]["score_transaction"]["protection_reasons"][str(run)] == "evidence_markers_on_legacy_record"
    result = module.apply_prune_plan(plan)
    assert result["deleted_count"] == 0
    assert manifest.read_bytes() == before


def test_saved_plan_rechecks_v2_anchor_before_deleting(tmp_path: Path):
    module = _module()
    archive, _business, _evidence = _paths(tmp_path)
    run_id = "b" * 32
    run = archive / ".score_run_transactions/runs" / run_id
    run.mkdir(parents=True)
    manifest = run / "manifest.json"
    payload = {"schema_version": "hermes-score-run-transaction-v1", "run_id": run_id, "status": "COMMITTED"}
    manifest.write_text(json.dumps(payload))
    plan = module.build_prune_plan(
        live_root=tmp_path / "live", backup_root=tmp_path / "backups",
        archive_dir=archive, keep_transactions=0,
    )
    assert any(row["path"] == str(run) for row in plan["delete"])
    payload["schema_version"] = "hermes-score-run-transaction-v2"
    manifest.write_text(json.dumps(payload))
    before = manifest.read_bytes()

    result = module.apply_prune_plan(plan)
    assert result["deleted_count"] == 0
    assert "decision_input_evidence_anchor" in result["skipped"][0]["reason"]
    assert manifest.read_bytes() == before


def test_unknown_protocol_is_preserved_instead_of_treated_as_legacy(tmp_path: Path):
    module = _module()
    archive, _business, _evidence = _paths(tmp_path)
    run_id = "c" * 32
    run = archive / ".score_run_transactions/runs" / run_id
    run.mkdir(parents=True)
    manifest = run / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": "hermes-score-run-transaction-v99",
                                    "run_id": run_id, "status": "COMMITTED"}))
    plan = module.build_prune_plan(
        live_root=tmp_path / "live", backup_root=tmp_path / "backups",
        archive_dir=archive, keep_transactions=0, max_transaction_bytes=0,
    )
    assert str(run) in plan["summary"]["score_transaction"]["protected"]
    assert plan["summary"]["score_transaction"]["protection_reasons"][str(run)] == "unknown_transaction_protocol"
    assert not any(row["path"] == str(run) for row in plan["delete"])


@pytest.mark.parametrize("case", ["linked", "dangling", "corrupt", "non_object"])
def test_untrusted_manifest_cannot_authorize_saved_plan_deletion(tmp_path: Path, case: str):
    module = _module()
    archive, _business, _evidence = _paths(tmp_path)
    run_id = "e" * 32
    run = archive / ".score_run_transactions/runs" / run_id
    run.mkdir(parents=True)
    manifest = run / "manifest.json"
    payload = {"schema_version": "hermes-score-run-transaction-v1", "run_id": run_id, "status": "COMMITTED"}
    manifest.write_text(json.dumps(payload))
    plan = module.build_prune_plan(
        live_root=tmp_path / "live", backup_root=tmp_path / "backups",
        archive_dir=archive, keep_transactions=0,
    )
    assert any(row["path"] == str(run) for row in plan["delete"])
    outside = tmp_path / "outside-manifest.json"
    if case in {"linked", "dangling"}:
        if case == "linked":
            outside.write_bytes(manifest.read_bytes())
        manifest.unlink()
        manifest.symlink_to(outside)
    else:
        manifest.write_text("{" if case == "corrupt" else "[]")

    rebuilt = module.build_prune_plan(
        live_root=tmp_path / "live", backup_root=tmp_path / "backups",
        archive_dir=archive, keep_transactions=0,
    )
    assert not any(row["path"] == str(run) for row in rebuilt["delete"])
    result = module.apply_prune_plan(plan)
    assert result["deleted_count"] == 0
    assert result["skipped"] and run.exists()
    if case in {"linked", "dangling"}:
        assert manifest.is_symlink()
        assert "symlink" in result["skipped"][0]["reason"]


@pytest.mark.parametrize("schema", [None, "hermes-score-run-transaction-v1"])
@pytest.mark.parametrize("status", ["COMMITTED", "ROLLED_BACK", "RECOVERED_ROLLBACK"])
def test_plain_legacy_terminal_transactions_remain_prunable(tmp_path: Path, schema, status: str):
    module = _module()
    archive, _business, _evidence = _paths(tmp_path)
    run_id = "f" * 32
    run = archive / ".score_run_transactions/runs" / run_id
    run.mkdir(parents=True)
    payload = {"run_id": run_id, "status": status}
    if schema is not None:
        payload["schema_version"] = schema
    (run / "manifest.json").write_text(json.dumps(payload))
    plan = module.build_prune_plan(
        live_root=tmp_path / "live", backup_root=tmp_path / "backups",
        archive_dir=archive, keep_transactions=0,
    )
    assert any(row["path"] == str(run) for row in plan["delete"])
    result = module.apply_prune_plan(plan)
    assert result["deleted_count"] == 1 and not result["skipped"]
    assert not run.exists()


@pytest.mark.parametrize("status", ["ROLLED_BACK", "RECOVERED_ROLLBACK"])
def test_v2_rollback_records_are_preserved_until_evidence_gc_policy_exists(tmp_path: Path, status: str):
    module = _module()
    archive, _business, _evidence = _paths(tmp_path)
    run_id = "0" * 32
    run = archive / ".score_run_transactions/runs" / run_id
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({"schema_version": "hermes-score-run-transaction-v2",
                                                  "run_id": run_id, "status": status}))
    plan = module.build_prune_plan(
        live_root=tmp_path / "live", backup_root=tmp_path / "backups",
        archive_dir=archive, keep_transactions=0, max_transaction_bytes=0,
    )
    assert str(run) in plan["summary"]["score_transaction"]["protected"]
    assert not any(row["path"] == str(run) for row in plan["delete"])
