"""Real default-off producer capture, with isolated data and no network."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from hermes_escape_top import pipeline
from hermes_escape_top.config import load_config, resolve_path
from hermes_escape_top.core.data.manifest import write_manifest
from hermes_escape_top.core.data.run_transaction import load_score_run_transaction
from hermes_escape_top.core.data.transaction_evidence import validate_input_evidence
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.core.data.market import MarketData
from hermes_escape_top.core.reporting.transaction_restore import restore_committed_before_images
from test_a2_production_capture import capture_root as capture_root
from test_a2_production_capture import _business_state


def test_real_producer_commits_bound_inputs_and_complete_payload(capture_root):
    write_manifest(resolve_path(load_config(), "history_dir"), capture_root / "data_manifest_latest.json")
    payload = pipeline.score_pipeline(
        "2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True,
    )
    record = load_score_run_transaction(capture_root, payload["persistence"]["run_id"])
    assert record["status"] == "COMMITTED"
    validate_input_evidence(record, capture_root.parent)
    bundle = capture_root / "decision_inputs" / payload["persistence"]["capture_id"]
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    assert manifest["capture_mode"] == "IN_RUN_CAPTURE"
    assert manifest["binding"] == {
        "run_id": record["run_id"], "capture_id": record["capture_id"], "as_of": payload["as_of"],
        "decision_id": payload["decision_evidence"]["decision_id"], "input_hash": payload["input_hash"],
    }
    assert json.loads((bundle / "payload.json").read_bytes()) == payload
    soft = json.loads((bundle / "soft.json").read_bytes())
    assert soft["value"] == payload["soft_data"]
    assert soft["record_order"] == list(payload["soft_data"]["records"])
    assert soft["record_field_order"] == {
        key: list(row.get("fields", {})) for key, row in payload["soft_data"]["records"].items()
    }
    assert record["input_binding"]["manifest_sha256"] == hashlib.sha256((bundle / "manifest.json").read_bytes()).hexdigest()


def test_capture_rejects_payload_snapshot_rewrite_and_restores_business_state(capture_root, monkeypatch):
    pipeline.score_pipeline("2026-05-28", include_ibkr=False)
    before = _business_state(capture_root)
    write_manifest(resolve_path(load_config(), "history_dir"), capture_root / "data_manifest_latest.json")
    original = pipeline.build_action_context
    observed = {}

    def rewrite_snapshot(payload, snapshots):
        result = original(payload, snapshots)
        payload["snapshots"]["MSTR"]["fields"]["close"]["value"] += 1.0
        observed["run_id"] = payload["persistence"]["run_id"]
        return result

    monkeypatch.setattr(pipeline, "build_action_context", rewrite_snapshot)
    with pytest.raises(ValueError, match="capture consumed inputs changed after freezing"):
        pipeline.score_pipeline("2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True)
    assert _business_state(capture_root) == before
    record = load_score_run_transaction(capture_root, observed["run_id"])
    assert record["status"] == "ROLLED_BACK"
    assert not (capture_root / ".score_run_transactions/active.json").exists()
    assert not any(path.is_file() for path in (capture_root / "decision_inputs").rglob("*"))


def test_capture_rejects_soft_field_order_change_after_freezing(capture_root, monkeypatch):
    pipeline.score_pipeline("2026-05-28", include_ibkr=False)
    before = _business_state(capture_root)
    write_manifest(resolve_path(load_config(), "history_dir"), capture_root / "data_manifest_latest.json")
    original = pipeline.build_action_context

    def reverse_fields(payload, snapshots):
        result = original(payload, snapshots)
        fields = payload["soft_data"]["records"]["dollar"]["fields"]
        assert len(fields) > 1
        payload["soft_data"]["records"]["dollar"]["fields"] = dict(reversed(list(fields.items())))
        return result

    monkeypatch.setattr(pipeline, "build_action_context", reverse_fields)
    with pytest.raises(ValueError, match="capture soft order changed after freezing"):
        pipeline.score_pipeline("2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True)
    assert _business_state(capture_root) == before
    assert not (capture_root / ".score_run_transactions/active.json").exists()


def test_capture_preserves_full_primary_legacy_and_as_of_projection(capture_root):
    config = load_config()
    primary = resolve_path(config, "history_dir") / "MSTR.csv"
    legacy = resolve_path(config, "legacy_history_dir") / "MSTR.csv"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(primary, legacy)
    legacy.write_bytes(legacy.read_bytes() + b"\n")
    write_manifest(primary.parent, capture_root / "data_manifest_latest.json")
    payload = pipeline.score_pipeline("2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True)
    bundle = capture_root / "decision_inputs" / payload["persistence"]["capture_id"]
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    row = manifest["histories"]["MSTR"]
    assert row["selected"] == "primary"
    for role, source in (("primary", primary), ("legacy", legacy)):
        archived = capture_root.parent / row[role]["path"]
        assert archived.read_bytes() == source.read_bytes()
    visible = payload["decision_evidence"]["semantic_identity"]["history_hashes"]["MSTR"]
    assert row["visible_hash"] == visible
    histories = json.loads((bundle / "histories.json").read_bytes())
    assert all(pd.Timestamp(day) <= pd.Timestamp("2026-05-29") for day in histories["MSTR"]["index"])
    raw = pd.read_csv(primary)
    assert pd.to_datetime(raw.iloc[:, 0]).max() > pd.Timestamp("2026-05-29")


@pytest.mark.parametrize("damage", ["missing", "bad_date", "duplicate", "symlink", "bad_numeric"])
def test_capture_rejects_unprovable_required_history(capture_root, damage):
    path = resolve_path(load_config(), "history_dir") / "MSTR.csv"
    write_manifest(path.parent, capture_root / "data_manifest_latest.json")
    if damage == "missing":
        path.unlink()
    elif damage == "bad_date":
        path.write_bytes(b"Date,Close\nnot-a-date,5\n")
    elif damage == "duplicate":
        path.write_bytes(b"Date,Close\n2026-05-29,5\n2026-05-29,6\n")
    elif damage == "bad_numeric":
        frame = pd.read_csv(path).astype(object)
        close = next(column for column in frame.columns if column.lower() == "close")
        frame.loc[0, close] = "not-a-number"
        path.write_text(frame.to_csv(index=False))
    else:
        target = path.with_suffix(".original")
        path.rename(target)
        path.symlink_to(target)
    with pytest.raises(ValueError, match="capture.*history"):
        pipeline.score_pipeline("2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True)
    assert not (capture_root / "audit_log.jsonl").exists()


def test_capture_records_legacy_selection_and_explicit_optional_absence(capture_root, tmp_path):
    config = load_config()
    primary = resolve_path(config, "history_dir") / "MSTR.csv"
    legacy = resolve_path(config, "legacy_history_dir") / "MSTR.csv"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    primary.rename(legacy)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    write_manifest(primary.parent, capture_root / "data_manifest_latest.json")
    payload = pipeline.score_pipeline("2026-05-29", config_path=config_path, include_ibkr=False,
                                      run_type="scheduled", capture_inputs=True)
    bundle = capture_root / "decision_inputs" / payload["persistence"]["capture_id"]
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    assert manifest["histories"]["MSTR"]["selected"] == "legacy"
    assert manifest["histories"]["MSTR"]["primary"]["availability"] == "ABSENT"
    assert manifest["histories"]["MSTR"]["primary"]["path"] is None
    assert not (bundle / "market/primary/MSTR.csv").exists()


def test_capture_keeps_actual_certification_config_source_and_environment(capture_root):
    config = load_config()
    source_manifest = capture_root / "data_manifest_latest.json"
    write_manifest(resolve_path(config, "history_dir"), source_manifest)
    admission = {"operation_id": "test-operation", "completed_through": "2026-05-29", "status": "OK"}
    payload = pipeline.score_pipeline("2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True,
                                      market_admission_status=admission)
    bundle = capture_root / "decision_inputs" / payload["persistence"]["capture_id"]
    cert = json.loads((bundle / "certification.json").read_bytes())
    reads = {row["source"]: row for row in cert["reads"]}
    entry = reads[str(source_manifest)]
    assert (capture_root.parent / entry["path"]).read_bytes() == source_manifest.read_bytes()
    assert cert["certified_at"] == payload["decision_evidence"]["certified_at"]
    params = json.loads((bundle / "parameters.json").read_bytes())
    assert params["market_admission_status"] == admission
    environment = json.loads((bundle / "environment.json").read_bytes())
    assert environment["packages"] and environment["interpreter"]["version"]
    assert environment["archive_scope"] == "PROJECT_SOURCE_AND_ENVIRONMENT_VERSIONS_NOT_INTERPRETER_OR_WHEELS"
    assert (bundle / "source/package/pipeline.py").read_bytes() == Path(pipeline.__file__).read_bytes()
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    assert manifest["scoring_logic_hash"] == payload["decision_evidence"]["semantic_identity"]["scoring_logic_hash"]


def test_capture_rejects_soft_csv_cache_not_matching_frozen_file(capture_root, monkeypatch):
    from hermes_escape_top.core.data import risk_signals
    path = resolve_path(load_config(), "soft_history_dir") / "dollar.csv"
    original = pd.read_csv(path, parse_dates=["date", "publish_date"])
    corrupted = original.copy()
    corrupted["value"] = 999999.0
    key = (str(path), path.stat().st_mtime, ("date", "publish_date"))
    monkeypatch.setitem(risk_signals._CSV_CACHE, key, corrupted)
    write_manifest(resolve_path(load_config(), "history_dir"), capture_root / "data_manifest_latest.json")
    with pytest.raises(ValueError, match="capture soft cache mismatch"):
        pipeline.score_pipeline("2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True)
    assert not (capture_root / "audit_log.jsonl").exists()


def test_capture_refuses_certification_that_did_not_observe_its_reads(capture_root, monkeypatch):
    write_manifest(resolve_path(load_config(), "history_dir"), capture_root / "data_manifest_latest.json")
    certify = pipeline.build_scheduled_decision_evidence

    def skip_observation(*args, **kwargs):
        kwargs.pop("input_observer")
        return certify(*args, **kwargs)

    monkeypatch.setattr(pipeline, "build_scheduled_decision_evidence", skip_observation)
    with pytest.raises(ValueError, match="capture certification reads incomplete"):
        pipeline.score_pipeline("2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True)
    assert not (capture_root / "audit_log.jsonl").exists()


def test_capture_preserves_r6_shared_config_link_provenance(capture_root, tmp_path):
    config_path = tmp_path / "shared_config.json"
    config_path.write_text(json.dumps(load_config()))
    release_config = tmp_path / "release_config.json"
    release_config.symlink_to(config_path)
    write_manifest(resolve_path(load_config(), "history_dir"), capture_root / "data_manifest_latest.json")
    payload = pipeline.score_pipeline("2026-05-29", config_path=release_config, include_ibkr=False,
                                      run_type="scheduled", capture_inputs=True)
    bundle = capture_root / "decision_inputs" / payload["persistence"]["capture_id"]
    config_source = json.loads((bundle / "parameters.json").read_bytes())["config_source"]
    assert config_source == {"requested_path": str(release_config), "resolved_path": str(config_path.resolve())}
    assert (bundle / "configuration.raw.json").read_bytes() == config_path.read_bytes()


def test_capture_rejects_config_byte_drift_even_when_parsed_values_match(capture_root, tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(load_config()))
    write_manifest(resolve_path(load_config(), "history_dir"), capture_root / "data_manifest_latest.json")
    resolve = pipeline.resolve_decision_as_of

    def reformat_after_loading(as_of, config):
        result = resolve(as_of, config)
        config_path.write_text(json.dumps(config, indent=3) + "\n")
        return result

    monkeypatch.setattr(pipeline, "resolve_decision_as_of", reformat_after_loading)
    with pytest.raises(ValueError, match="capture configuration bytes changed after loading"):
        pipeline.score_pipeline("2026-05-29", config_path=config_path, include_ibkr=False,
                                run_type="scheduled", capture_inputs=True)
    assert not (capture_root / "audit_log.jsonl").exists()


def test_capture_refuses_mutated_admission_argument(capture_root, monkeypatch):
    write_manifest(resolve_path(load_config(), "history_dir"), capture_root / "data_manifest_latest.json")
    admission = {"operation_id": "test", "completed_through": "2026-05-29", "rows": []}

    def mutate(checkpoint):
        if checkpoint == "signal_journal":
            admission["rows"].append({"changed_after_consumption": True})

    monkeypatch.setattr(pipeline, "_persistence_checkpoint", mutate)
    with pytest.raises(ValueError, match="capture admission argument changed"):
        pipeline.score_pipeline("2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True,
                                market_admission_status=admission)
    assert not (capture_root / "audit_log.jsonl").exists()


def test_capture_cannot_write_python_archive_inside_scanned_source_tree(tmp_path, monkeypatch):
    package = tmp_path / "source_package"
    package.mkdir()
    (package / "pipeline.py").write_bytes(Path(pipeline.__file__).read_bytes())
    monkeypatch.setattr(pipeline, "__file__", str(package / "pipeline.py"))
    monkeypatch.setenv("HERMES_DATA_DIR", str(package))
    with pytest.raises(ValueError, match="capture data root must be outside source package"):
        pipeline.score_pipeline("2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True)
    assert not (resolve_path(load_config(), "archive_dir") / ".score_run_transactions").exists()


def test_capture_checks_exact_written_source_bytes_not_only_parsed_values(capture_root, monkeypatch):
    write_manifest(resolve_path(load_config(), "history_dir"), capture_root / "data_manifest_latest.json")
    original = pipeline.RuntimeCapture._write

    def corrupt(self, name, content):
        original(self, name, content)
        if name == "market/primary/MSTR.csv":
            path = self.root / name
            path.chmod(0o600)
            path.write_bytes(content + b"\n")
            path.chmod(0o400)

    monkeypatch.setattr(pipeline.RuntimeCapture, "_write", corrupt)
    with pytest.raises(ValueError, match="capture archived source bytes mismatch"):
        pipeline.score_pipeline("2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True)
    assert not (capture_root / "audit_log.jsonl").exists()


def test_certification_observer_does_not_accept_manifest_encoding_rejected_by_off(tmp_path):
    from hermes_escape_top.core.data.decision_revision import _market_manifest_id
    (tmp_path / "data_manifest_latest.json").write_bytes(b'\xef\xbb\xbf{"manifest_id": "x"}')
    for observer in (None, lambda *_args: None):
        with pytest.raises(ValueError, match="canonical market manifest unavailable"):
            _market_manifest_id(tmp_path, observer)


def test_committed_producer_before_images_work_with_existing_restore(capture_root, tmp_path):
    pipeline.score_pipeline("2026-05-28", include_ibkr=False)
    before = _business_state(capture_root)
    write_manifest(resolve_path(load_config(), "history_dir"), capture_root / "data_manifest_latest.json")
    payload = pipeline.score_pipeline("2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True)
    run_id = payload["persistence"]["run_id"]
    journal = capture_root / ".score_run_transactions/runs" / run_id / "manifest.json"
    restored = restore_committed_before_images(
        store=LocalStore(load_config()), run_id=run_id,
        expected_journal_sha256=hashlib.sha256(journal.read_bytes()).hexdigest(),
        decision_id=payload["decision_evidence"]["decision_id"], input_hash=payload["input_hash"],
        destination=tmp_path / "restored",
    )
    assert _business_state(restored / "archive") == before
    bundle = capture_root / "decision_inputs" / payload["persistence"]["capture_id"]
    assert bundle.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o400 for path in bundle.rglob("*") if path.is_file())


@pytest.mark.parametrize("name", ["market/primary/MSTR.csv", "payload.json", "manifest.json"])
def test_capture_io_failure_restores_seven_artifacts_and_registered_evidence(capture_root, monkeypatch, name):
    pipeline.score_pipeline("2026-05-28", include_ibkr=False)
    before = _business_state(capture_root)
    write_manifest(resolve_path(load_config(), "history_dir"), capture_root / "data_manifest_latest.json")
    original = pipeline.RuntimeCapture._write

    def fail(self, relative, content):
        original(self, relative, content)
        if relative == name:
            raise OSError("injected capture I/O failure")

    monkeypatch.setattr(pipeline.RuntimeCapture, "_write", fail)
    with pytest.raises(OSError, match="injected capture I/O failure"):
        pipeline.score_pipeline("2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True)
    assert _business_state(capture_root) == before
    assert not any(path.is_file() for path in (capture_root / "decision_inputs").rglob("*"))


def test_capture_rejects_actual_certification_material_changed_before_read(capture_root, monkeypatch):
    path = capture_root / "data_manifest_latest.json"
    write_manifest(resolve_path(load_config(), "history_dir"), path)
    original = pipeline.build_scheduled_decision_evidence

    def change_then_certify(*args, **kwargs):
        data = json.loads(path.read_bytes())
        data["manifest_id"] = "changed-after-freeze"
        path.write_text(json.dumps(data))
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "build_scheduled_decision_evidence", change_then_certify)
    with pytest.raises(ValueError, match="canonical market manifest unavailable|capture certification read mismatch"):
        pipeline.score_pipeline("2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True)
    assert not (capture_root / "audit_log.jsonl").exists()


@pytest.mark.parametrize("kind", ["market", "soft_return", "config_link"])
def test_capture_rejects_late_input_mutation_and_rolls_back(capture_root, monkeypatch, tmp_path, kind):
    write_manifest(resolve_path(load_config(), "history_dir"), capture_root / "data_manifest_latest.json")
    original = pipeline.build_soft_data
    observed = {}

    def remember(*args, **kwargs):
        observed["soft"] = original(*args, **kwargs)
        return observed["soft"]

    monkeypatch.setattr(pipeline, "build_soft_data", remember)
    config = load_config()
    original_config = tmp_path / "original_config.json"
    original_config.write_text(json.dumps(config))
    config_link = tmp_path / "linked_config.json"
    config_link.symlink_to(original_config)

    def change(checkpoint):
        if checkpoint != "signal_journal":
            return
        if kind == "market":
            path = resolve_path(config, "history_dir") / "MSTR.csv"
            path.write_bytes(path.read_bytes() + b"\n")
        elif kind == "soft_return":
            observed["soft"]["records"]["aaii"]["reason"] = "changed after consumption"
        else:
            replacement = tmp_path / "other_config.json"
            replacement.write_bytes(original_config.read_bytes())
            config_link.unlink()
            config_link.symlink_to(replacement)

    monkeypatch.setattr(pipeline, "_persistence_checkpoint", change)
    with pytest.raises(ValueError, match="capture .*changed"):
        pipeline.score_pipeline("2026-05-29", config_path=config_link, include_ibkr=False,
                                run_type="scheduled", capture_inputs=True)
    assert not (capture_root / "audit_log.jsonl").exists()


def test_capture_rejects_indicator_cache_not_matching_actual_file(capture_root, monkeypatch, tmp_path):
    from hermes_escape_top.core.data import market as market_module
    config = load_config()
    config["features"]["use_indicator_cache"] = True
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    store = LocalStore(config)
    market = MarketData(config, store)
    market.snapshot("MSTR", "2026-05-29")
    key = market_module._indicator_cache_key(store, "MSTR", store.load_history("MSTR"),
                                            config["atr"]["multiplier"], config["atr"]["chandelier_period"])
    corrupted = market_module._INDICATOR_FRAME_CACHE[key].copy()
    corrupted.loc[pd.Timestamp("2026-05-29"), "Volume"] += 100000000
    monkeypatch.setitem(market_module._INDICATOR_FRAME_CACHE, key, corrupted)
    with pytest.raises(ValueError, match="capture snapshot/cache mismatch"):
        pipeline.score_pipeline("2026-05-29", config_path=config_path, include_ibkr=False,
                                run_type="scheduled", capture_inputs=True)
    assert not (capture_root / "audit_log.jsonl").exists()


def test_capture_rejects_close_cache_not_matching_actual_file(capture_root, monkeypatch):
    from hermes_escape_top.core.data import risk_signals
    store = LocalStore(load_config())
    path = store.history_path("BOXX")
    cached = store.load_history("BOXX")["Close"].dropna().copy()
    cached.iloc[0] += 10
    monkeypatch.setitem(risk_signals._CLOSE_CACHE, ("BOXX", str(path), path.stat().st_mtime), cached)
    with pytest.raises(ValueError, match="capture soft cache mismatch"):
        pipeline.score_pipeline("2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True)
    assert not (capture_root / "audit_log.jsonl").exists()


def test_capture_rejects_memory_history_not_matching_file(capture_root, monkeypatch):
    class ChangedMarket(MarketData):
        def load_history(self, symbol):
            frame = super().load_history(symbol)
            if symbol == "MSTR":
                frame = frame.copy()
                frame.loc[pd.Timestamp("2026-05-29"), "Close"] += 1.0
            return frame

    monkeypatch.setattr(pipeline, "MarketData", ChangedMarket)
    with pytest.raises(ValueError, match="capture history consumption mismatch"):
        pipeline.score_pipeline("2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True)
    assert not (capture_root / "audit_log.jsonl").exists()


@pytest.mark.parametrize("corruption", ["extra", "identity", "digest"])
def test_real_binding_rejects_corrupt_or_unregistered_capture(capture_root, monkeypatch, corruption):
    from hermes_escape_top.core.reporting import runtime_capture
    write_manifest(resolve_path(load_config(), "history_dir"), capture_root / "data_manifest_latest.json")
    original = runtime_capture.bind_score_run_inputs

    def corrupt(transaction, **kwargs):
        manifest_path = kwargs["manifest_path"]
        if corruption == "extra":
            (manifest_path.parent / "extra.json").write_text("{}")
        else:
            manifest_path.chmod(0o600)
            manifest = json.loads(manifest_path.read_bytes())
            manifest["binding"]["input_hash"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest))
            if corruption == "identity":
                kwargs["expected_manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        return original(transaction, **kwargs)

    monkeypatch.setattr(runtime_capture, "bind_score_run_inputs", corrupt)
    with pytest.raises(ValueError, match="unregistered transaction evidence file|manifest binding mismatch|manifest digest mismatch"):
        pipeline.score_pipeline("2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True)
    assert not (capture_root / "audit_log.jsonl").exists()


def test_capture_observes_real_version_file_instead_of_source_fallback(capture_root, monkeypatch, tmp_path):
    source = Path(pipeline.__file__).parent
    package = tmp_path / "release/hermes_escape_top"
    for path in source.rglob("*.py"):
        relative = path.relative_to(source)
        if "tests" not in relative.parts:
            target = package / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
    policy = package / "governance/approved_live_config.json"
    policy.parent.mkdir(exist_ok=True)
    policy.write_bytes((source / "governance/approved_live_config.json").read_bytes())
    (package / "VERSION").write_text("synthetic-release-3c2\n")
    monkeypatch.setattr(pipeline, "__file__", str(package / "pipeline.py"))
    write_manifest(resolve_path(load_config(), "history_dir"), capture_root / "data_manifest_latest.json")
    payload = pipeline.score_pipeline("2026-05-29", include_ibkr=False, run_type="scheduled", capture_inputs=True)
    assert payload["decision_evidence"]["scorer_release_hash"] == "synthetic-release-3c2"
    bundle = capture_root / "decision_inputs" / payload["persistence"]["capture_id"]
    cert = json.loads((bundle / "certification.json").read_bytes())
    assert len(cert["reads"]) == 3
    version = next(row for row in cert["reads"] if row["source"].endswith("/VERSION"))
    assert (capture_root.parent / version["path"]).read_text() == "synthetic-release-3c2\n"
