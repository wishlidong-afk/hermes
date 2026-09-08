"""R6 source aliases are observations, not changes to the scored valuation."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from hermes_escape_top import pipeline
from hermes_escape_top.core.data import adapters, decision_revision
from hermes_escape_top.core.data.decision_identity import stable_hash
from test_decision_revision import SUNDAY, _append_audit, _archive, _build, _package, _payload


def _releases(root: Path, location: str = "release") -> tuple[Path, Path, Path]:
    live = root / "live"
    data = live / ("data" if location == "release" else "shared/hermes_escape_top/data")
    data.mkdir(parents=True)
    target = data / "valuation_snapshot.json"
    target.write_text(json.dumps({"items": {
        "FNGS": {"forward_pe_percentile": 75.0},
        "SOXX": {"forward_pe_percentile": 80.0},
        "MSTR": {"premium_percentile": 60.0},
    }}))
    packages = []
    for release in ("aaaaaaa_20260829_071000", "bbbbbbb_20260830_071000"):
        folder = live / "releases" / release
        package = _package(folder, release=release[:7])
        package = package.rename(folder / "hermes_escape_top")
        alias_root = folder if location == "release" else package
        (alias_root / "data").symlink_to(data, target_is_directory=True)
        packages.append(package)
    return packages[0], packages[1], target


def _valuation_payload(package: Path, monkeypatch, *, config=None) -> dict:
    monkeypatch.setattr(adapters, "__file__", str(package / "core/data/adapters.py"))
    store = SimpleNamespace(archive_dir=package / "absent/archive")
    payload = _payload()
    payload["soft_data"] = {"records": {
        "valuation": adapters._valuation_record(payload["as_of"], config or {}, store),
    }}
    _snapshot(payload)
    return payload


def _snapshot(payload: dict) -> None:
    payload["snapshots"]["SOFT"] = pipeline._soft_snapshot(
        payload["soft_data"], payload["as_of"],
    ).to_dict()
    payload["input_hash"] = stable_hash(payload["snapshots"])


@pytest.mark.parametrize("location", ["release", "package"])
def test_shared_valuation_release_alias_does_not_change_decision_identity(tmp_path, monkeypatch, location):
    first_package, second_package, target = _releases(tmp_path, location)
    archive = _archive(tmp_path)
    first = _valuation_payload(first_package, monkeypatch)
    second = _valuation_payload(second_package, monkeypatch)
    originals = copy.deepcopy([first, second])

    assert first["input_hash"] != second["input_hash"]
    assert Path(first["soft_data"]["records"]["valuation"]["source"]).resolve() == target
    assert Path(second["soft_data"]["records"]["valuation"]["source"]).resolve() == target
    before = _build(archive, first_package, payload=first, certified_at=SUNDAY)
    after = _build(archive, second_package, payload=second, certified_at=SUNDAY)

    assert before["semantic_identity"] == after["semantic_identity"]
    assert before["decision_id"] == after["decision_id"]
    assert before["snapshot_hash"] != after["snapshot_hash"]
    assert before["soft_input_evidence_hash"] != after["soft_input_evidence_hash"]
    assert [first, second] == originals


@pytest.mark.parametrize("location", ["release", "package"])
@pytest.mark.parametrize("damage", ["missing", "unlinked", "outside", "file_link", "directory", "unreadable"])
def test_unverified_r6_alias_fails_closed(tmp_path, monkeypatch, location, damage):
    package, _, target = _releases(tmp_path, location)
    archive = _archive(tmp_path)
    payload = _valuation_payload(package, monkeypatch)
    alias = Path(payload["soft_data"]["records"]["valuation"]["source"]).parent
    if damage == "missing":
        target.unlink()
    elif damage in {"unlinked", "outside"}:
        alias.unlink()
        if damage == "unlinked":
            alias.mkdir()
            (alias / target.name).write_bytes(target.read_bytes())
        else:
            outside = tmp_path / "different-data"
            outside.mkdir()
            (outside / target.name).write_bytes(target.read_bytes())
            alias.symlink_to(outside, target_is_directory=True)
    elif damage == "file_link":
        different = target.with_name("different.json")
        different.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(different)
    elif damage == "directory":
        target.unlink()
        target.mkdir()
    else:
        original_open = Path.open

        def unreadable(path, *args, **kwargs):
            if path == alias / target.name:
                raise PermissionError("test unreadable valuation")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", unreadable)
    with pytest.raises(ValueError, match="valuation source alias is not verified"):
        _build(archive, package, payload=payload, certified_at=SUNDAY)


@pytest.mark.parametrize("change", ["value", "availability", "reason", "unknown", "source", "field_source"])
def test_valuation_material_fields_are_not_scrubbed(tmp_path, monkeypatch, change):
    package, _, _ = _releases(tmp_path)
    archive = _archive(tmp_path)
    payload = _valuation_payload(package, monkeypatch)
    before = _build(archive, package, payload=payload, certified_at=SUNDAY)
    record = payload["soft_data"]["records"]["valuation"]
    if change == "value":
        record["fields"]["SOXL_valuation_pctl"] += 1
    elif change == "availability":
        record["data_available"] = False
    elif change == "reason":
        record["reason"] = "changed source rationale"
    elif change == "unknown":
        record["origin_details"] = {"source": "another publisher"}
    elif change == "source":
        record["source"] = "another-publisher/valuation_snapshot.json"
    else:
        record["field_provenance"] = {"SOXL_valuation_pctl": {"source": "explicit-field-origin"}}
    _snapshot(payload)
    after = _build(archive, package, payload=payload, certified_at=SUNDAY)
    assert after["semantic_hash"] != before["semantic_hash"]


def test_custom_and_unknown_origins_keep_path_identity(tmp_path, monkeypatch):
    package, _, target = _releases(tmp_path)
    archive = _archive(tmp_path)
    custom = tmp_path / "custom.json"
    custom.symlink_to(target)
    configs = [{"valuation": {"snapshot_path": str(path)}} for path in (custom, target)]
    payloads = [_valuation_payload(package, monkeypatch, config=cfg) for cfg in configs]
    evidence = [_build(archive, package, payload=payload, config=cfg, certified_at=SUNDAY)
                for payload, cfg in zip(payloads, configs)]
    assert evidence[0]["semantic_hash"] != evidence[1]["semantic_hash"]
    # The valuation-only alias rule must not normalize unknown sources/fields.
    payload = _valuation_payload(package, monkeypatch)
    payload["soft_data"]["records"]["unknown"] = {"source": str(custom), "value": 10}
    _snapshot(payload)
    first = _build(archive, package, payload=payload, certified_at=SUNDAY)
    payload["soft_data"]["records"]["unknown"]["source"] = str(target)
    _snapshot(payload)
    second = _build(archive, package, payload=payload, certified_at=SUNDAY)
    assert first["semantic_hash"] != second["semantic_hash"]


def test_same_bytes_in_different_shared_files_are_different_origins(tmp_path, monkeypatch):
    first, _, _ = _releases(tmp_path / "one")
    second, _, _ = _releases(tmp_path / "two")
    archive = _archive(tmp_path)
    evidence = [_build(archive, package, payload=_valuation_payload(package, monkeypatch),
                       certified_at=SUNDAY) for package in (first, second)]
    assert evidence[0]["semantic_hash"] != evidence[1]["semantic_hash"]


def _write_old_v1(archive, package, payload, monkeypatch):
    current = _build(archive, package, payload=payload, certified_at=SUNDAY)
    identity = {key: current[key] for key in decision_revision.V1_IDENTITY_FIELDS}
    digest = stable_hash(identity)
    legacy = {**current, "decision_hash": digest,
              "decision_id": decision_revision._decision_id(payload["as_of"], digest, 2, "FINAL"),
              "decision_revision": 2}
    for name in ("semantic_hash", "semantic_identity", "identity_schema_version"):
        del legacy[name]
    _append_audit(archive, {**payload, "decision_evidence": legacy})
    monkeypatch.setitem(decision_revision.V1_EQUIVALENT_RELEASES, current["scorer_release_hash"],
                        current["semantic_identity"]["scoring_logic_hash"])


@pytest.mark.parametrize("change", ["release_alias", "manifest"])
def test_v1_migration_is_not_relaxed_by_source_projection(tmp_path, monkeypatch, change):
    first, second, _ = _releases(tmp_path)
    archive = _archive(tmp_path)
    payload = _valuation_payload(first, monkeypatch)
    _write_old_v1(archive, first, payload, monkeypatch)
    original = (archive / "audit_log.jsonl").read_bytes()
    if change == "release_alias":
        payload = _valuation_payload(second, monkeypatch)
        expected = "unchanged snapshot_hash not evidenced"
    else:
        second = first
        (archive / "data_manifest_latest.json").write_text('{"manifest_id":"new-manifest"}')
        expected = "unchanged canonical_market_evidence_hash not evidenced"
    with pytest.raises(decision_revision.DecisionRevisionConflict, match=expected):
        _build(archive, second, payload=payload, certified_at=SUNDAY)
    assert (archive / "audit_log.jsonl").read_bytes() == original


def test_new_decision_date_keeps_old_chain_and_repeats_across_releases(tmp_path, monkeypatch):
    first, second, _ = _releases(tmp_path)
    archive = _archive(tmp_path)
    _write_old_v1(archive, first, _valuation_payload(first, monkeypatch), monkeypatch)
    original = (archive / "audit_log.jsonl").read_bytes()
    identities = []
    for package in (first, second, first):
        payload = _valuation_payload(package, monkeypatch)
        # Synthetic next decision date, not evidence of a natural live run.
        payload["as_of"] = "2026-08-31"
        payload["snapshots"]["BTC-USD"]["as_of"] = payload["as_of"]
        payload["soft_data"]["records"]["valuation"]["as_of"] = payload["as_of"]
        _snapshot(payload)
        evidence = _build(archive, package, payload=payload, certified_at=SUNDAY.replace(month=9, day=1),
                          histories={"BTC-USD": pd.DataFrame({"close": [100.0]},
                                     index=pd.to_datetime(["2026-08-31"]))})
        _append_audit(archive, {**payload, "decision_evidence": evidence})
        identities.append(evidence)
    assert [row["decision_revision"] for row in identities] == [1, 1, 1]
    assert len({row["decision_id"] for row in identities}) == 1
    assert all("identity_migration" not in row for row in identities)
    assert (archive / "audit_log.jsonl").read_bytes().startswith(original)
