from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from hermes_escape_top import pipeline
from hermes_escape_top.config import load_config, resolve_path
from hermes_escape_top.core.safe_io import assert_pipeline_lease, pipeline_lock

BUSINESS_ARTIFACTS = (
    "audit_log.jsonl",
    "flow_reference.sqlite",
    "hermes_state.sqlite",
    "mirror_reference.sqlite",
    "reentry_state.sqlite",
    "signal_journal.jsonl",
    "soft_adapter_snapshot_2026-05-29.json",
)


def test_public_score_pipeline_mints_active_lease():
    observed = {}

    def fake_locked(as_of, **kwargs):
        lease = kwargs.pop("_lease")
        assert_pipeline_lease(lease)
        observed["as_of"] = as_of
        observed["kwargs"] = kwargs
        return {"as_of": as_of, "ok": True}

    with mock.patch.object(pipeline, "_score_pipeline_locked", side_effect=fake_locked):
        payload = pipeline.score_pipeline("2026-05-29", include_ibkr=False)

    assert payload == {"as_of": "2026-05-29", "ok": True}
    assert observed["kwargs"]["include_ibkr"] is False


def test_locked_score_rejects_missing_lease_before_computation():
    with pytest.raises(RuntimeError, match="invalid pipeline lease"):
        pipeline._score_pipeline_locked("2026-05-29", _lease=None)


def test_locked_score_rejects_lease_for_wrong_data_dir(tmp_path):
    expected = resolve_path(load_config(), "archive_dir") / ".pipeline.lock"
    wrong = tmp_path / ".pipeline.lock"
    assert wrong.resolve() != expected.resolve()

    with pipeline_lock(blocking=False, path=wrong) as lease:
        with pytest.raises(RuntimeError, match="path mismatch"):
            pipeline._score_pipeline_locked("2026-05-29", _lease=lease)


def test_private_locked_score_has_only_approved_production_callers():
    package = Path(pipeline.__file__).resolve().parent
    approved = {
        package / "pipeline.py",
        package / "ibkr" / "live_check.py",
        package / "scripts" / "run_daily_package.py",
        package / "web" / "refresh.py",
    }
    callers = set()
    for path in package.rglob("*.py"):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node.func) == "_score_pipeline_locked":
                callers.add(path)
    assert callers == approved


def test_each_cross_store_fault_restores_all_business_artifacts():
    config = load_config()
    archive = resolve_path(config, "archive_dir")
    pipeline.score_pipeline("2026-05-29", include_ibkr=False)
    before = _artifact_hashes(archive)

    for fault_name in pipeline.PERSISTENCE_CHECKPOINTS:
        def inject(checkpoint, expected=fault_name):
            if checkpoint == expected:
                raise RuntimeError(f"fault after {checkpoint}")

        with mock.patch.object(pipeline, "_persistence_checkpoint", side_effect=inject):
            with pytest.raises(RuntimeError, match=f"fault after {fault_name}"):
                pipeline.score_pipeline("2026-05-29", include_ibkr=False)
        assert _artifact_hashes(archive) == before, fault_name


def test_score_transaction_manifest_includes_dated_soft_snapshot():
    config = load_config()
    archive = resolve_path(config, "archive_dir")

    payload = pipeline.score_pipeline("2026-05-29", include_ibkr=False)

    run_id = payload["persistence"]["run_id"]
    manifest = (
        archive / f".score_run_transactions/runs/{run_id}/manifest.json"
    ).read_text(encoding="utf-8")
    assert "archive/soft_adapter_snapshot_2026-05-29.json" in manifest


def test_scheduled_live_score_persists_decision_evidence_in_state_and_audit():
    config = load_config()
    archive = resolve_path(config, "archive_dir")
    evidence = {
        "schema_version": "hermes-decision-certification-v1",
        "decision_id": "decision-2026-05-29-r1-test",
        "decision_hash": "decision-hash",
        "decision_revision": 1,
        "bar_finality": "FINAL",
    }

    with mock.patch.object(
        pipeline,
        "build_scheduled_decision_evidence",
        return_value=evidence,
    ) as build:
        payload = pipeline.score_pipeline(
            "2026-05-29",
            include_ibkr=False,
            run_type="scheduled",
        )

    assert payload["decision_evidence"] == evidence
    build.assert_called_once()
    audit_record = json.loads(
        (archive / "audit_log.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert audit_record["payload"]["decision_evidence"] == evidence

    with sqlite3.connect(archive / "hermes_state.sqlite") as conn:
        stored = json.loads(
            conn.execute("SELECT payload_json FROM score_runs ORDER BY id DESC LIMIT 1").fetchone()[0]
        )
    assert stored["decision_evidence"] == evidence


def test_decision_certification_failure_rolls_back_every_business_artifact():
    config = load_config()
    archive = resolve_path(config, "archive_dir")
    pipeline.score_pipeline("2026-05-29", include_ibkr=False)
    before = _artifact_hashes(archive)

    with mock.patch.object(
        pipeline,
        "build_scheduled_decision_evidence",
        side_effect=RuntimeError("revision budget exhausted"),
    ):
        with pytest.raises(RuntimeError, match="revision budget exhausted"):
            pipeline.score_pipeline(
                "2026-05-29",
                include_ibkr=False,
                run_type="scheduled",
            )

    assert _artifact_hashes(archive) == before


def test_manual_preview_never_enters_decision_certification_path():
    with mock.patch.object(
        pipeline,
        "build_scheduled_decision_evidence",
        side_effect=AssertionError("manual preview entered official certification"),
    ) as build:
        payload = pipeline.score_pipeline(
            "2026-05-29",
            include_ibkr=False,
            run_type="manual_rerun",
        )

    build.assert_not_called()
    assert "decision_evidence" not in payload


def test_fault_restores_prior_soft_snapshot_bytes():
    config = load_config()
    archive = resolve_path(config, "archive_dir")
    snapshot = archive / "soft_adapter_snapshot_2026-05-29.json"
    previous = b'{"certified":"prior-run"}\n'
    snapshot.write_bytes(previous)

    def inject(checkpoint):
        if checkpoint == "reentry_state":
            raise RuntimeError("fault after reentry_state")

    with mock.patch.object(pipeline, "_persistence_checkpoint", side_effect=inject):
        with pytest.raises(RuntimeError, match="fault after reentry_state"):
            pipeline.score_pipeline("2026-05-29", include_ibkr=False)

    assert snapshot.read_bytes() == previous


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _artifact_hashes(archive: Path):
    return {
        name: hashlib.sha256((archive / name).read_bytes()).hexdigest()
        if (archive / name).exists()
        else None
        for name in BUSINESS_ARTIFACTS
    }
