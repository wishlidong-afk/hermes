from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import pandas as pd

from hermes_escape_top.core.data.decision_revision import (
    DecisionRevisionConflict,
    build_scheduled_decision_evidence,
)
from hermes_escape_top.core.data.market_admission import MarketAdmissionSession
from hermes_escape_top.core.data.manifest import freeze_manifest
from hermes_escape_top.core.data.decision_identity import stable_hash

SHANGHAI = ZoneInfo("Asia/Shanghai")
SATURDAY = datetime(2026, 8, 29, 7, 10, tzinfo=SHANGHAI)
SUNDAY = datetime(2026, 8, 30, 7, 10, tzinfo=SHANGHAI)
MONDAY = datetime(2026, 8, 31, 7, 10, tzinfo=SHANGHAI)


def _package(root: Path, release: str = "release-a") -> Path:
    package = root / "package"
    (package / "governance").mkdir(parents=True)
    (package / "VERSION").write_text(f"{release} 20260829_071000\n", encoding="utf-8")
    (package / "pipeline.py").write_text("SCORE = 1\n", encoding="utf-8")
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
    snapshots = {"BTC-USD": {"as_of": "2026-08-28", "fields": {"close": snapshot_hash}}}
    return {
        "as_of": "2026-08-28",
        "run_type": "scheduled",
        "input_hash": stable_hash(snapshots),
        "snapshots": snapshots,
        "market_admission_status": {
            "operation_id": "admission-a",
            "completed_through": "2026-08-28",
        },
    }


def _append_audit(archive: Path, payload: dict, payload_hash: str = "audit-a") -> None:
    record = {"payload_hash": stable_hash(payload), "payload": payload}
    with (archive / "audit_log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _build(
    archive: Path,
    package: Path,
    *,
    certified_at: datetime,
    payload: dict | None = None,
    config: dict | None = None,
    histories: dict | None = None,
) -> dict:
    return build_scheduled_decision_evidence(
        payload or _payload(),
        config or {"version": "test-v1", "features": {"alpha": False, "data_dollar": True}},
        archive_dir=archive,
        package_root=package,
        histories=histories if histories is not None else {
            "BTC-USD": pd.DataFrame({"close": [100.0]}, index=pd.to_datetime(["2026-08-28"]))
        },
        certified_at=certified_at,
    )


def test_first_weekend_certification_is_revision_one_and_provisional(tmp_path) -> None:
    package = _package(tmp_path)
    archive = _archive(tmp_path)

    evidence = _build(archive, package, certified_at=SATURDAY)

    assert evidence["schema_version"] == "hermes-decision-certification-v1"
    assert evidence["identity_schema_version"] == "hermes-decision-identity-v2"
    assert evidence["decision_revision"] == 1
    assert evidence["bar_finality"] == "PROVISIONAL"
    assert evidence["supersedes_decision_id"] is None
    assert evidence["revision_reason"] == "INITIAL_CERTIFICATION"
    assert evidence["snapshot_hash"] == _payload()["input_hash"]
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


@pytest.mark.parametrize("variant", ["control", "operation_id", "future_btc"])
def test_repeated_weekend_observations_do_not_spend_revision_budget(tmp_path, variant) -> None:
    package = _package(tmp_path)
    archive = _archive(tmp_path)
    history = tmp_path / "history"
    history.mkdir()
    btc = history / "BTC-USD.csv"
    btc.write_text("date,close\n2026-08-28,100\n", encoding="utf-8")
    results = []
    for index, certified_at in enumerate((SATURDAY, SUNDAY, MONDAY)):
        payload = _payload()
        if variant == "operation_id":
            session = MarketAdmissionSession(enabled=True, witness_bars={})
            payload["market_admission_status"]["operation_id"] = session.operation_id
        if variant == "future_btc" and index:
            with btc.open("a", encoding="utf-8") as handle:
                handle.write(f"2026-08-{28 + index},101\n")
        (archive / "data_manifest_latest.json").write_text(
            json.dumps(freeze_manifest(history).to_dict()), encoding="utf-8"
        )
        visible_history = pd.read_csv(btc, parse_dates=["date"]).set_index("date")
        evidence = _build(archive, package, certified_at=certified_at, payload=payload,
                          histories={"BTC-USD": visible_history})
        payload["decision_evidence"] = evidence
        _append_audit(archive, payload)
        results.append(evidence)

    assert [row["decision_revision"] for row in results] == [1, 2, 2]
    assert len({row["decision_hash"] for row in results}) == 1
    assert results[1]["decision_id"] == results[2]["decision_id"]
    if variant == "operation_id":
        assert len({row["market_admission_operation_id"] for row in results}) == 3
    if variant == "future_btc":
        assert len({row["canonical_market_evidence_hash"] for row in results}) == 3


@pytest.mark.parametrize("column", ["close", "volume"])
def test_visible_history_changes_are_material_even_with_same_last_snapshot(tmp_path, column):
    archive, package = _archive(tmp_path), _package(tmp_path)
    history = pd.DataFrame({"close": [99.0, 100.0], "volume": [10, 20]},
                           index=pd.to_datetime(["2026-08-27", "2026-08-28"]))
    before = _build(archive, package, certified_at=SUNDAY, histories={"BTC-USD": history})
    history.loc[pd.Timestamp("2026-08-27"), column] += 1
    after = _build(archive, package, certified_at=SUNDAY, histories={"BTC-USD": history})
    assert before["snapshot_hash"] == after["snapshot_hash"]
    assert before["semantic_hash"] != after["semantic_hash"]


def test_research_and_fetch_metadata_remain_observations(tmp_path):
    archive, package = _archive(tmp_path), _package(tmp_path)
    payload = _payload()
    payload["soft_data"] = {"records": {
        "dollar": {"value": 40, "publish_date": "2026-08-28", "fetched_at": "first"},
        "btc_funding_basis": {"value": 1, "fields": {"funding_test": 1}},
    }}
    payload["snapshots"]["SOFT"] = {"fields": {"funding_test": {"value": 1}}}
    payload["input_hash"] = stable_hash(payload["snapshots"])
    first = _build(archive, package, certified_at=SUNDAY, payload=payload)
    payload["soft_data"]["records"]["dollar"]["fetched_at"] = "later"
    payload["soft_data"]["records"]["btc_funding_basis"]["value"] = 9
    payload["snapshots"]["SOFT"]["fields"]["funding_test"]["value"] = 9
    payload["input_hash"] = stable_hash(payload["snapshots"])
    second = _build(archive, package, certified_at=SUNDAY, payload=payload)
    assert first["semantic_hash"] == second["semantic_hash"]
    assert first["snapshot_hash"] != second["snapshot_hash"]
    assert first["soft_input_evidence_hash"] != second["soft_input_evidence_hash"]
    payload["soft_data"]["records"]["dollar"]["publish_date"] = "2026-08-29"
    third = _build(archive, package, certified_at=SUNDAY, payload=payload)
    assert second["semantic_hash"] != third["semantic_hash"]


def test_config_notes_and_web_release_do_not_change_semantics(tmp_path):
    archive, package = _archive(tmp_path), _package(tmp_path)
    cfg = {"features": {}, "_note": "before", "web": {"title": "before"}}
    first = _build(archive, package, certified_at=SUNDAY, config=cfg)
    cfg.update(_note="after", web={"title": "after"})
    (package / "web").mkdir()
    (package / "web" / "render.py").write_text("TITLE = 'after'\n")
    (package / "VERSION").write_text("release-b stamp\n")
    second = _build(archive, package, certified_at=SUNDAY, config=cfg)
    assert first["semantic_hash"] == second["semantic_hash"]
    assert first["config_hash"] != second["config_hash"]
    assert first["scorer_release_hash"] != second["scorer_release_hash"]
    (package / "pipeline.py").write_text("SCORE = 2\n")
    third = _build(archive, package, certified_at=SUNDAY, config=cfg)
    assert second["semantic_hash"] != third["semantic_hash"]


@pytest.mark.parametrize("damage", ["schema", "hash", "revision", "audit", "finality"])
def test_prior_chain_is_not_reset_when_invalid(tmp_path, damage):
    archive, package = _archive(tmp_path), _package(tmp_path)
    payload = _payload()
    evidence = _build(archive, package, certified_at=SUNDAY)
    if damage == "schema":
        evidence["schema_version"] = "unknown"
    elif damage == "hash":
        evidence["semantic_hash"] = "wrong"
    elif damage == "revision":
        evidence["decision_revision"] = 3
    payload["decision_evidence"] = evidence
    _append_audit(archive, payload)
    if damage == "audit":
        with (archive / "audit_log.jsonl").open("a") as handle:
            handle.write('{"payload":')
    before = (archive / "audit_log.jsonl").read_bytes()
    with pytest.raises(DecisionRevisionConflict):
        _build(archive, package, certified_at=SATURDAY if damage == "finality" else MONDAY)
    assert (archive / "audit_log.jsonl").read_bytes() == before


def _legacy_evidence(archive, package, *, revision, monkeypatch):
    from hermes_escape_top.core.data import decision_revision as module
    payload = _payload()
    current = _build(archive, package, certified_at=SATURDAY if revision == 1 else SUNDAY)
    monkeypatch.setitem(module.V1_EQUIVALENT_RELEASES, "release-a",
                        current["semantic_identity"]["scoring_logic_hash"])
    identity = {key: current[key] for key in module.V1_IDENTITY_FIELDS}
    evidence = {**identity, "schema_version": module.LEGACY_SCHEMA_VERSION,
                "decision_hash": stable_hash(identity), "decision_revision": revision,
                "bar_finality": "PROVISIONAL" if revision == 1 else "FINAL",
                "revision_reason": "INITIAL_CERTIFICATION" if revision == 1 else "BAR_FINALITY_ADVANCED",
                "supersedes_decision_id": None if revision == 1 else "old-r1",
                "previous_decision_hash": None if revision == 1 else "old-hash"}
    evidence["decision_id"] = module._decision_id(payload["as_of"], evidence["decision_hash"],
                                                 revision, evidence["bar_finality"])
    payload["decision_evidence"] = evidence
    _append_audit(archive, payload)
    return payload, evidence


@pytest.mark.parametrize("revision", [1, 2])
def test_verified_v1_chain_migration_keeps_budget_and_consumer_binding(tmp_path, monkeypatch, revision):
    from hermes_escape_top.web.server import _latest_score_payload, _report_matches_decision
    from test_refresh_as_of_gating import _apply, _write_overlay

    archive, package = _archive(tmp_path), _package(tmp_path)
    payload, old = _legacy_evidence(archive, package, revision=revision, monkeypatch=monkeypatch)
    original = (archive / "audit_log.jsonl").read_bytes()
    payload["market_admission_status"]["operation_id"] = "new-real-run"
    current = _build(archive, package, certified_at=SUNDAY, payload=payload)
    assert current["decision_revision"] == 2
    assert current["identity_migration"]["legacy_evidence"] == old
    if revision == 2:
        assert current["decision_id"] == old["decision_id"]
        assert current["decision_hash"] == old["decision_hash"]
    else:
        assert current["supersedes_decision_id"] == old["decision_id"]
    assert (archive / "audit_log.jsonl").read_bytes() == original
    payload["decision_evidence"] = current
    _append_audit(archive, payload)
    repeat = _build(archive, package, certified_at=MONDAY, payload=payload)
    assert repeat["decision_id"] == current["decision_id"]
    assert repeat["decision_hash"] == current["decision_hash"]
    assert repeat["identity_migration"] == current["identity_migration"]
    selected = _latest_score_payload("2026-08-28", [
        {**payload, "decision_evidence": old, "run_ts": SATURDAY.isoformat()},
        {**payload, "decision_evidence": repeat, "run_ts": MONDAY.isoformat()},
    ])
    assert selected["decision_evidence"]["identity_schema_version"] == "hermes-decision-identity-v2"
    assert _report_matches_decision(
        {"decision_hash": repeat["decision_hash"]},
        payload_hash=payload["input_hash"], decision_hash=repeat["decision_hash"],
    )
    _write_overlay(archive, as_of="2026-08-28", base_input_hash=payload["input_hash"],
                   base_decision_hash=old["decision_hash"])
    selected["ibkr"] = {"source": "kept"}
    overlaid = _apply(archive, selected)
    assert overlaid["ibkr"]["source"] == ("tws" if revision == 2 else "kept")


@pytest.mark.parametrize("damage", ["manifest", "scorer", "outputs", "payload", "identity"])
def test_v1_insufficient_migration_evidence_fails_closed(tmp_path, monkeypatch, damage):
    archive, package = _archive(tmp_path), _package(tmp_path)
    payload, _ = _legacy_evidence(archive, package, revision=2, monkeypatch=monkeypatch)
    if damage == "manifest":
        (archive / "data_manifest_latest.json").write_text('{"manifest_id":"changed"}')
    elif damage == "scorer":
        (package / "pipeline.py").write_text("SCORE = 2\n")
    elif damage == "outputs":
        payload["scores"] = {"BTC": {"final_score": 20}}
    elif damage == "payload":
        payload = _payload("changed-snapshot")
    else:
        payload["decision_evidence"]["decision_hash"] = "forged"
        _append_audit(archive, payload)
    with pytest.raises(DecisionRevisionConflict, match="v1 migration"):
        _build(archive, package, certified_at=MONDAY, payload=payload)


def test_out_of_order_audit_and_manual_preview_cannot_reset_revision(tmp_path):
    archive, package = _archive(tmp_path), _package(tmp_path)
    first = _build(archive, package, certified_at=SATURDAY)
    initial = {**_payload(), "decision_evidence": first, "run_ts": SATURDAY.isoformat()}
    _append_audit(archive, initial)
    final = _build(archive, package, certified_at=SUNDAY)
    _append_audit(archive, {**_payload(), "decision_evidence": final, "run_ts": SUNDAY.isoformat()})
    _append_audit(archive, initial)
    _append_audit(archive, {**_payload("preview-data"), "run_type": "manual_rerun"})
    repeat = _build(archive, package, certified_at=MONDAY)
    assert repeat["decision_id"] == final["decision_id"]
    assert repeat["decision_revision"] == 2


def test_audit_lookup_does_not_lose_prior_record_outside_64_mib_tail(tmp_path):
    archive, package = _archive(tmp_path), _package(tmp_path)
    prior = _build(archive, package, certified_at=SUNDAY)
    _append_audit(archive, {**_payload(), "decision_evidence": prior})
    filler = json.dumps({"payload": {"run_type": "manual_rerun", "detail": "x" * 1024}}) + "\n"
    with (archive / "audit_log.jsonl").open("a") as handle:
        for _ in range(66000):
            handle.write(filler)
    assert (archive / "audit_log.jsonl").stat().st_size > 64 * 1024 * 1024
    repeat = _build(archive, package, certified_at=MONDAY)
    assert repeat["decision_id"] == prior["decision_id"]


@pytest.mark.parametrize("missing_file", [True, False])
def test_scheduled_state_without_audit_is_not_a_new_chain(tmp_path, missing_file):
    archive, package = _archive(tmp_path), _package(tmp_path)
    with sqlite3.connect(archive / "hermes_state.sqlite") as conn:
        conn.execute("CREATE TABLE score_runs(as_of TEXT, payload_json TEXT)")
        conn.execute("INSERT INTO score_runs VALUES (?, ?)", ("2026-08-28", json.dumps(_payload())))
    if not missing_file:
        _append_audit(archive, {**_payload(), "as_of": "2026-08-27"})
    with pytest.raises(DecisionRevisionConflict, match="audit is unavailable"):
        _build(archive, package, certified_at=MONDAY)


def test_identity_requires_complete_consumed_history_universe(tmp_path):
    archive, package = _archive(tmp_path), _package(tmp_path)
    with pytest.raises(ValueError, match="actual snapshot universe"):
        _build(archive, package, certified_at=SUNDAY, histories={})


def test_same_snapshot_with_different_actual_action_is_material(tmp_path):
    archive, package = _archive(tmp_path), _package(tmp_path)
    payload = {**_payload(), "routing": {"MSTR": {"target": "IAU"}}}
    first = _build(archive, package, certified_at=SUNDAY, payload=payload)
    payload["routing"]["MSTR"]["target"] = "BOXX"
    second = _build(archive, package, certified_at=SUNDAY, payload=payload)
    assert first["semantic_hash"] != second["semantic_hash"]


def test_rollback_writer_recognizes_revision_envelope_instead_of_legacy_reset(tmp_path):
    archive, package = _archive(tmp_path), _package(tmp_path)
    evidence = _build(archive, package, certified_at=SUNDAY)
    # The released v1 allocator treats EVERY unknown envelope as uncertified
    # legacy. Keep its revision guard, and version the new identity separately.
    assert evidence["schema_version"] == "hermes-decision-certification-v1"
    assert evidence["identity_schema_version"] == "hermes-decision-identity-v2"
