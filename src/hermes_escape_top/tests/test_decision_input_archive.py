from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.decision_identity import stable_hash
from hermes_escape_top.core.data.decision_revision import build_scheduled_decision_evidence
from hermes_escape_top.core.data.market import MarketData
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.core.reporting.decision_inputs import (
    archive_decision_inputs, restore_decision_inputs,
)


def _inputs(tmp_path):
    config = load_config()
    for name in ("history_dir", "legacy_history_dir", "archive_dir"):
        config["paths"][name] = str(tmp_path / name)
    store = LocalStore(config)
    store.ensure_dirs()
    for symbol in ("QQQ", "BTC-USD"):
        store.history_path(symbol).write_text(
            "date,open,high,low,close,volume\n"
            "2026-05-28,100,105,98,101,1000\n"
            "2026-05-29,101,106,99,103,1200\n"
            "2026-05-30,103,107,101,104,900\n",
        )
    package = tmp_path / "package"
    package.mkdir()
    (package / "pipeline.py").write_text("SCORE = 1\n")
    (package / "governance").mkdir()
    (package / "governance/approved_live_config.json").write_text('{}\n')
    (store.archive_dir / "data_manifest_latest.json").write_text('{"manifest_id":"test"}\n')
    market = MarketData(config, store)
    payload = {
        "as_of": "2026-05-29", "run_type": "scheduled",
        "snapshots": {symbol: market.snapshot(symbol, "2026-05-29").to_dict()
                      for symbol in ("QQQ", "BTC-USD")},
        "soft_data": {"records": {}}, "scores": {"MSTR": {"final_score": 20}},
    }
    payload["input_hash"] = stable_hash(payload["snapshots"])
    histories = {symbol: store.load_history(symbol) for symbol in payload["snapshots"]}
    payload["decision_evidence"] = build_scheduled_decision_evidence(
        payload, config, archive_dir=store.archive_dir, package_root=package,
        histories=histories, certified_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    return payload, config, store, package


def test_binding_saves_all_consumed_symbols_even_without_backfill_batches(tmp_path):
    payload, config, store, package = _inputs(tmp_path)
    before = copy.deepcopy(payload)
    result = archive_decision_inputs(
        payload, config, store=store, package_root=package, destination=tmp_path / "binding",
    )
    path = Path(result["manifest_path"])
    assert path.is_file()
    manifest = json.loads(path.read_bytes())
    assert manifest["decision_id"] == payload["decision_evidence"]["decision_id"]
    assert set(manifest["histories"]) == {"QQQ", "BTC-USD"}
    for symbol, entry in manifest["histories"].items():
        original = store.history_path(symbol).read_bytes()
        assert entry["sha256"] == hashlib.sha256(original).hexdigest()
        assert (path.parent / entry["path"]).read_bytes() == original
    assert payload == before


def test_material_history_change_cannot_be_bound_using_current_csv(tmp_path):
    payload, config, store, package = _inputs(tmp_path)
    path = store.history_path("QQQ")
    path.write_text(path.read_text().replace("101,106,99,103,1200", "101,106,99,102,1200"))
    destination = tmp_path / "binding"
    with pytest.raises(ValueError, match="cannot prove certified"):
        archive_decision_inputs(payload, config, store=store, package_root=package,
                                destination=destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".decision-inputs-*"))


def test_restoration_uses_bound_versions_not_changed_current_files(tmp_path):
    payload, config, store, package = _inputs(tmp_path)
    result = archive_decision_inputs(payload, config, store=store, package_root=package,
                                     destination=tmp_path / "binding")
    original = store.history_path("QQQ").read_bytes()
    store.history_path("QQQ").write_text("corrupt current file\n")
    restored = restore_decision_inputs(
        Path(result["manifest_path"]), expected_manifest_sha256=result["manifest_sha256"],
        decision_id=result["decision_id"], destination=tmp_path / "restored", package_root=package,
    )
    assert (restored / "history/QQQ.csv").is_file()
    assert (restored / "history/QQQ.csv").read_bytes() == original
    assert store.history_path("QQQ").read_text() == "corrupt current file\n"


def test_archive_destination_cannot_pollute_canonical_history(tmp_path):
    payload, config, store, package = _inputs(tmp_path)
    destination = store.history_dir / "binding"
    with pytest.raises(ValueError, match="overlaps a source root"):
        archive_decision_inputs(payload, config, store=store, package_root=package,
                                destination=destination)
    assert not destination.exists()


@pytest.mark.parametrize("case", ["missing_file", "corrupt_file", "wrong_id", "wrong_anchor"])
def test_restoration_rejects_bad_evidence_without_output(tmp_path, case):
    payload, config, store, package = _inputs(tmp_path)
    result = archive_decision_inputs(payload, config, store=store, package_root=package,
                                     destination=tmp_path / "binding")
    path = tmp_path / "binding/history/QQQ.csv"
    if case == "missing_file":
        path.unlink()
    elif case == "corrupt_file":
        path.chmod(0o600)
        path.write_text("changed\n")
    destination = tmp_path / "restored"
    with pytest.raises((ValueError, FileNotFoundError)):
        restore_decision_inputs(
            Path(result["manifest_path"]),
            expected_manifest_sha256="0" * 64 if case == "wrong_anchor" else result["manifest_sha256"],
            decision_id="wrong" if case == "wrong_id" else result["decision_id"],
            destination=destination, package_root=package,
        )
    assert not destination.exists()
    assert not list(tmp_path.glob(".decision-inputs-*"))


def test_future_tail_change_is_observation_not_a_historical_version_claim(tmp_path):
    payload, config, store, package = _inputs(tmp_path)
    source = store.history_path("BTC-USD")
    original = source.read_bytes()
    source.write_text(source.read_text().replace("103,107,101,104,900", "103,107,101,106,900"))
    result = archive_decision_inputs(payload, config, store=store, package_root=package,
                                     destination=tmp_path / "binding")
    manifest = json.loads(Path(result["manifest_path"]).read_bytes())
    assert manifest["capture_mode"] == "RETROSPECTIVE_AS_OF_MATCH"
    assert manifest["histories"]["BTC-USD"]["sha256"] != hashlib.sha256(original).hexdigest()
    assert manifest["semantic_hash"] == payload["decision_evidence"]["semantic_hash"]
    assert manifest["source_locations_at_capture"]["BTC-USD"]["availability"] == "primary"


def test_actual_pipeline_input_archive_restores_three_symbol_scores(tmp_path, monkeypatch):
    from conftest import PACKAGE_DATA, TEST_DATA, _tracked_package_files
    from hermes_escape_top import pipeline
    from hermes_escape_top.core.data.base import SymbolSnapshot
    from hermes_escape_top.core.features.regime import Regime
    from hermes_escape_top.core.scoring.scorer import score_symbol

    data = tmp_path / "isolated/data"
    for source in _tracked_package_files():
        if source.name != "audit_log.jsonl":
            target = data / source.relative_to(PACKAGE_DATA)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    shutil.copytree(TEST_DATA, data, dirs_exist_ok=True)
    monkeypatch.setenv("HERMES_DATA_DIR", str(data.parent))
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("network forbidden"))
    config = load_config()
    store = LocalStore(config)
    payload = pipeline.score_pipeline("2026-05-29", include_ibkr=False, run_type="scheduled")
    before = {path.name: path.read_bytes() for path in store.archive_dir.iterdir() if path.is_file()}
    package = Path(pipeline.__file__).parent
    result = archive_decision_inputs(payload, config, store=store, package_root=package,
                                     destination=tmp_path / "binding")
    restored = restore_decision_inputs(
        Path(result["manifest_path"]), expected_manifest_sha256=result["manifest_sha256"],
        decision_id=result["decision_id"], destination=tmp_path / "restored", package_root=package,
    )
    recorded = json.loads((restored / "payload.json").read_bytes())
    assert recorded == payload
    frozen_store = LocalStore({**config, "paths": {**config["paths"],
                              "history_dir": str(restored / "history"),
                              "legacy_history_dir": str(restored / "missing_legacy")}})
    import pandas as pd

    snapshots = {symbol: SymbolSnapshot.from_dict(row) for symbol, row in recorded["snapshots"].items()}
    histories = {symbol: frozen_store.load_history(symbol) for symbol in snapshots if symbol != "SOFT"}
    histories = {symbol: frame.loc[frame.index <= pd.Timestamp(recorded["as_of"])]
                 for symbol, frame in histories.items()}
    for symbol in ("MSTR", "FNGU", "SOXL"):
        replayed = score_symbol(symbol, snapshots, config, regime=Regime(recorded["regime"]["current"]),
                                histories=histories).result.to_dict()
        assert replayed == recorded["scores"][symbol]
    assert {path.name: path.read_bytes() for path in store.archive_dir.iterdir()
            if path.is_file()} == before


@pytest.mark.parametrize("case", ["as_of", "soft", "config", "code", "missing_history"])
def test_binding_rejects_material_input_mismatches(tmp_path, case):
    payload, config, store, package = _inputs(tmp_path)
    if case == "as_of":
        payload["as_of"] = "2026-05-28"
    elif case == "soft":
        payload["soft_data"]["records"]["new-source"] = {"source": "unknown", "value": 5}
    elif case == "config":
        config["initial_capital"] = 123456
    elif case == "code":
        (package / "pipeline.py").write_text("SCORE = 2\n")
    else:
        store.history_path("QQQ").unlink()
    with pytest.raises(ValueError):
        archive_decision_inputs(payload, config, store=store, package_root=package,
                                destination=tmp_path / "binding")
    assert not (tmp_path / "binding").exists()
    assert not list(tmp_path.glob(".decision-inputs-*"))


def test_legacy_history_is_captured_without_copying_into_canonical(tmp_path):
    payload, config, store, package = _inputs(tmp_path)
    original = store.history_path("QQQ").read_bytes()
    legacy = store.history_path("QQQ", legacy=True)
    legacy.parent.mkdir()
    store.history_path("QQQ").rename(legacy)
    result = archive_decision_inputs(payload, config, store=store, package_root=package,
                                     destination=tmp_path / "binding")
    manifest = json.loads(Path(result["manifest_path"]).read_bytes())
    assert manifest["source_locations_at_capture"]["QQQ"]["availability"] == "legacy"
    assert (tmp_path / "binding/history/QQQ.csv").read_bytes() == original
    assert not store.history_path("QQQ").exists()


def test_expected_missing_input_is_preserved_as_missing_not_fabricated(tmp_path):
    payload, config, store, package = _inputs(tmp_path)
    payload["snapshots"]["ABSENT"] = MarketData(config, store).snapshot("ABSENT", payload["as_of"]).to_dict()
    payload["input_hash"] = stable_hash(payload["snapshots"])
    payload["decision_evidence"] = build_scheduled_decision_evidence(
        payload, config, archive_dir=store.archive_dir, package_root=package,
        histories={symbol: None if symbol == "ABSENT" else store.load_history(symbol)
                   for symbol in payload["snapshots"]},
        certified_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    result = archive_decision_inputs(payload, config, store=store, package_root=package,
                                     destination=tmp_path / "binding")
    manifest = json.loads(Path(result["manifest_path"]).read_bytes())
    assert manifest["histories"]["ABSENT"] == {"path": None, "sha256": None}
    restored = restore_decision_inputs(
        Path(result["manifest_path"]), expected_manifest_sha256=result["manifest_sha256"],
        decision_id=result["decision_id"], destination=tmp_path / "restored", package_root=package,
    )
    assert not (restored / "history/ABSENT.csv").exists()


@pytest.mark.parametrize("case", ["existing", "symlink", "canonical", "archive_symlink", "code"])
def test_restoration_boundary_is_fail_closed(tmp_path, case):
    payload, config, store, package = _inputs(tmp_path)
    result = archive_decision_inputs(payload, config, store=store, package_root=package,
                                     destination=tmp_path / "binding")
    destination = tmp_path / "restored"
    if case == "existing":
        destination.mkdir()
    elif case == "symlink":
        destination.symlink_to(tmp_path / "does-not-exist", target_is_directory=True)
    elif case == "canonical":
        destination = store.history_dir / "restored"
    elif case == "archive_symlink":
        path = tmp_path / "binding/history/QQQ.csv"
        path.unlink()
        path.symlink_to(store.history_path("QQQ"))
    else:
        (package / "pipeline.py").write_text("SCORE = 2\n")
    with pytest.raises(ValueError):
        restore_decision_inputs(
            Path(result["manifest_path"]), expected_manifest_sha256=result["manifest_sha256"],
            decision_id=result["decision_id"], destination=destination, package_root=package,
        )
    if case not in {"existing", "symlink"}:
        assert not destination.exists()
    assert not list(tmp_path.glob(".decision-inputs-*"))


def test_data_root_change_does_not_allow_restoring_into_original_canonical(tmp_path, monkeypatch):
    payload, config, store, package = _inputs(tmp_path)
    for name in ("history_dir", "legacy_history_dir", "archive_dir"):
        config["paths"][name] = name
    monkeypatch.setenv("HERMES_DATA_DIR", str(tmp_path))
    payload["decision_evidence"] = build_scheduled_decision_evidence(
        payload, config, archive_dir=store.archive_dir, package_root=package,
        histories={symbol: store.load_history(symbol) for symbol in payload["snapshots"]},
        certified_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    result = archive_decision_inputs(payload, config, store=store, package_root=package,
                                     destination=tmp_path / "binding")
    monkeypatch.setenv("HERMES_DATA_DIR", str(tmp_path / "other-root"))
    destination = tmp_path / "history_dir/restored"
    with pytest.raises(ValueError, match="overlaps a source root"):
        restore_decision_inputs(
            Path(result["manifest_path"]), expected_manifest_sha256=result["manifest_sha256"],
            decision_id=result["decision_id"], destination=destination, package_root=package,
        )
    assert not destination.exists()


@pytest.mark.parametrize("operation", ["capture", "restore"])
def test_publish_failure_leaves_no_partial_bundle_or_source_writes(tmp_path, monkeypatch, operation):
    payload, config, store, package = _inputs(tmp_path)
    result = archive_decision_inputs(payload, config, store=store, package_root=package,
                                     destination=tmp_path / "binding") if operation == "restore" else None
    before = {path: path.read_bytes() for path in store.history_dir.glob("*.csv")}
    destination = tmp_path / "failed"

    def refuse_publish(*_):
        raise OSError("injected publish failure")

    monkeypatch.setattr(os, "rename", refuse_publish)
    with pytest.raises(OSError, match="injected publish failure"):
        if result is None:
            archive_decision_inputs(payload, config, store=store, package_root=package,
                                    destination=destination)
        else:
            restore_decision_inputs(
                Path(result["manifest_path"]), expected_manifest_sha256=result["manifest_sha256"],
                decision_id=result["decision_id"], destination=destination, package_root=package,
            )
    assert not destination.exists()
    assert not list(tmp_path.glob(".decision-inputs-*"))
    assert {path: path.read_bytes() for path in store.history_dir.glob("*.csv")} == before


@pytest.mark.parametrize("case", ["roles", "universe", "unsafe_path"])
def test_reanchored_but_invalid_manifest_still_fails_closed(tmp_path, case):
    payload, config, store, package = _inputs(tmp_path)
    result = archive_decision_inputs(payload, config, store=store, package_root=package,
                                     destination=tmp_path / "binding")
    path = Path(result["manifest_path"])
    manifest = json.loads(path.read_bytes())
    if case == "roles":
        manifest["evidence_role"] = "FULL_PRODUCTION_REPLAY"
    elif case == "universe":
        del manifest["histories"]["QQQ"]
    else:
        manifest["histories"]["QQQ"]["path"] = "../history_dir/QQQ.csv"
    raw = (json.dumps(manifest) + "\n").encode()
    path.chmod(0o600)
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        restore_decision_inputs(
            path, expected_manifest_sha256=hashlib.sha256(raw).hexdigest(),
            decision_id=result["decision_id"], destination=tmp_path / "restored", package_root=package,
        )
    assert not (tmp_path / "restored").exists()
    assert not list(tmp_path.glob(".decision-inputs-*"))


def test_old_decision_can_bind_versions_recovered_from_first_slice(tmp_path):
    from hermes_escape_top.core.data.history_transaction import HistoryPromotionTransaction
    from hermes_escape_top.core.reporting.history_versions import (
        HistoryVersionRecorder, history_versions_root, restore_history_version,
    )

    payload, config, store, package = _inputs(tmp_path)
    original = store.history_path("QQQ").read_bytes()
    changed = original.replace(b"101,106,99,103,1200", b"101,106,99,102,1200")
    transaction = HistoryPromotionTransaction(
        store.history_dir, allowed_roots=[store.history_dir, history_versions_root(store.history_dir)],
    )
    recorder = HistoryVersionRecorder(transaction)
    transaction.stage_bytes(store.history_path("QQQ"), changed)
    recorder.capture("QQQ", store.history_path("QQQ"), changed, source_symbol="QQQ")
    recorder.stage_index()
    transaction.prepare()
    transaction.promote()
    recorder.seal()
    transaction.mark_committed()
    seed = tmp_path / "recovered_seed"
    restore_history_version(store.history_dir, recorder.batch_id, "QQQ", "before", seed / "QQQ.csv")
    shutil.copy2(store.history_path("BTC-USD"), seed / "BTC_USD.csv")
    isolated = LocalStore({**config, "paths": {**config["paths"], "history_dir": str(seed),
                                             "legacy_history_dir": str(seed / "missing")}})
    result = archive_decision_inputs(payload, config, store=isolated, package_root=package,
                                     destination=tmp_path / "binding")
    manifest = json.loads(Path(result["manifest_path"]).read_bytes())
    assert manifest["histories"]["QQQ"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert store.history_path("QQQ").read_bytes() == changed
