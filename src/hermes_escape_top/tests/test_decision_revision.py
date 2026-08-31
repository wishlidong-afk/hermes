from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from hermes_escape_top.core.data.decision_revision import (
    DecisionRevisionConflict,
    build_scheduled_decision_evidence,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
SATURDAY = datetime(2026, 8, 29, 7, 10, tzinfo=SHANGHAI)
SUNDAY = datetime(2026, 8, 30, 7, 10, tzinfo=SHANGHAI)
MONDAY = datetime(2026, 8, 31, 7, 10, tzinfo=SHANGHAI)


def _package(root: Path, release: str = "release-a") -> Path:
    package = root / "package"
    (package / "governance").mkdir(parents=True)
    (package / "VERSION").write_text(f"{release} 20260829_071000\n", encoding="utf-8")
    (package / "governance" / "approved_live_config.json").write_text(
        '{"schema_version":"test-policy-v1"}\n',
        encoding="utf-8",
    )
    return package


def _archive(root: Path, manifest_id: str = "market-a") -> Path:
    archive = root / "archive"
    archive.mkdir(parents=True)
    (archive / "data_manifest_latest.json").write_text(
        json.dumps({"schema_version": "escape-top-data-manifest-v1", "manifest_id": manifest_id}) + "\n",
        encoding="utf-8",
    )
    return archive


def _payload(snapshot_hash: str = "snapshot-a") -> dict:
    return {
        "as_of": "2026-08-28",
        "run_type": "scheduled",
        "input_hash": snapshot_hash,
        "market_admission_status": {
            "operation_id": "admission-a",
            "completed_through": "2026-08-28",
        },
    }


def _append_audit(archive: Path, payload: dict, payload_hash: str = "audit-a") -> None:
    record = {"payload_hash": payload_hash, "payload": payload}
    with (archive / "audit_log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _build(
    archive: Path,
    package: Path,
    *,
    certified_at: datetime,
    payload: dict | None = None,
    config: dict | None = None,
) -> dict:
    return build_scheduled_decision_evidence(
        payload or _payload(),
        config or {"version": "test-v1", "features": {"alpha": False}},
        archive_dir=archive,
        package_root=package,
        certified_at=certified_at,
    )


def test_first_weekend_certification_is_revision_one_and_provisional(tmp_path) -> None:
    package = _package(tmp_path)
    archive = _archive(tmp_path)

    evidence = _build(archive, package, certified_at=SATURDAY)

    assert evidence["schema_version"] == "hermes-decision-certification-v1"
    assert evidence["decision_revision"] == 1
    assert evidence["bar_finality"] == "PROVISIONAL"
    assert evidence["supersedes_decision_id"] is None
    assert evidence["revision_reason"] == "INITIAL_CERTIFICATION"
    assert evidence["snapshot_hash"] == "snapshot-a"
    assert evidence["canonical_market_evidence_hash"] == "market-a"
    assert evidence["scorer_release_hash"] == "release-a"
    assert len(evidence["decision_hash"]) == 64
    assert evidence["decision_id"].startswith("decision-2026-08-28-r1-")


def test_changed_sunday_evidence_supersedes_provisional_revision(tmp_path) -> None:
    package = _package(tmp_path)
    archive = _archive(tmp_path)
    first = _build(archive, package, certified_at=SATURDAY)
    prior = _payload()
    prior["decision_evidence"] = first
    _append_audit(archive, prior)
    (archive / "data_manifest_latest.json").write_text(
        json.dumps({"schema_version": "escape-top-data-manifest-v1", "manifest_id": "market-b"}) + "\n",
        encoding="utf-8",
    )

    second = _build(
        archive,
        package,
        certified_at=SUNDAY,
        payload=_payload("snapshot-b"),
    )

    assert second["decision_revision"] == 2
    assert second["bar_finality"] == "FINAL"
    assert second["supersedes_decision_id"] == first["decision_id"]
    assert second["revision_reason"] == "CANONICAL_EVIDENCE_CHANGED_AND_FINALIZED"
    assert second["decision_id"] != first["decision_id"]


def test_identical_final_repeat_keeps_revision_and_decision_id(tmp_path) -> None:
    package = _package(tmp_path)
    archive = _archive(tmp_path)
    first = _build(archive, package, certified_at=SATURDAY)
    prior = _payload()
    prior["decision_evidence"] = first
    _append_audit(archive, prior)
    final = _build(archive, package, certified_at=SUNDAY)
    prior_final = _payload()
    prior_final["decision_evidence"] = final
    _append_audit(archive, prior_final, payload_hash="audit-b")

    repeat = _build(archive, package, certified_at=MONDAY)

    assert final["decision_revision"] == 2
    assert final["revision_reason"] == "BAR_FINALITY_ADVANCED"
    assert repeat["decision_revision"] == 2
    assert repeat["decision_id"] == final["decision_id"]
    assert repeat["supersedes_decision_id"] == first["decision_id"]
    assert repeat["previous_decision_hash"] == first["decision_hash"]
    assert repeat["revision_reason"] == "BAR_FINALITY_ADVANCED"


def test_third_material_revision_fails_closed(tmp_path) -> None:
    package = _package(tmp_path)
    archive = _archive(tmp_path)
    first = _build(archive, package, certified_at=SATURDAY)
    prior = _payload()
    prior["decision_evidence"] = first
    _append_audit(archive, prior)
    second = _build(archive, package, certified_at=SUNDAY, payload=_payload("snapshot-b"))
    prior_second = _payload("snapshot-b")
    prior_second["decision_evidence"] = second
    _append_audit(archive, prior_second, payload_hash="audit-b")

    with pytest.raises(DecisionRevisionConflict, match="revision budget exhausted"):
        _build(archive, package, certified_at=MONDAY, payload=_payload("snapshot-c"))


def test_legacy_scheduled_row_is_preserved_as_superseded_reference(tmp_path) -> None:
    package = _package(tmp_path)
    archive = _archive(tmp_path)
    _append_audit(archive, _payload("legacy-snapshot"), payload_hash="legacy-audit-hash")

    evidence = _build(archive, package, certified_at=SUNDAY)

    assert evidence["decision_revision"] == 2
    assert evidence["supersedes_decision_id"].startswith("legacy-2026-08-28-")
    assert evidence["revision_reason"] == "LEGACY_CERTIFICATION_SUPERSEDED"


def test_decision_hash_changes_when_config_changes_with_same_snapshots(tmp_path) -> None:
    package = _package(tmp_path)
    archive = _archive(tmp_path)

    first = _build(
        archive,
        package,
        certified_at=SATURDAY,
        config={"version": "test-v1", "features": {"alpha": False}},
    )
    second = _build(
        archive,
        package,
        certified_at=SATURDAY,
        config={"version": "test-v1", "features": {"alpha": True}},
    )

    assert first["snapshot_hash"] == second["snapshot_hash"]
    assert first["config_hash"] != second["config_hash"]
    assert first["decision_hash"] != second["decision_hash"]


def test_decision_hash_changes_when_soft_provenance_changes_with_same_snapshot(tmp_path) -> None:
    package = _package(tmp_path)
    archive = _archive(tmp_path)
    first_payload = _payload()
    first_payload["soft_data"] = {
        "records": {
            "dollar": {
                "as_of": "2026-08-28",
                "value": 42.0,
                "source": "official-source-a",
                "reason": "certified observation",
            }
        }
    }
    second_payload = json.loads(json.dumps(first_payload))
    second_payload["soft_data"]["records"]["dollar"]["source"] = "official-source-b"

    first = _build(archive, package, certified_at=SATURDAY, payload=first_payload)
    second = _build(archive, package, certified_at=SATURDAY, payload=second_payload)

    assert first["snapshot_hash"] == second["snapshot_hash"]
    assert first["soft_input_evidence_hash"] != second["soft_input_evidence_hash"]
    assert first["decision_hash"] != second["decision_hash"]
