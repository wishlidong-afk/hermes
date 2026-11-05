"""Restore authenticated v2 before images only into a new offline directory."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pandas as pd

from ..data.decision_identity import scoring_logic_hash, stable_hash
from ..data.decision_revision import _release_hash
from ..data.sqlite_snapshot import sqlite_state_hash
from ..data.store import LocalStore, safe_symbol
from ..data.transaction_evidence import SCHEMA_V2, checked_path, validate_input_evidence, validate_inventory
from .decision_inputs import _check_evidence, _check_state_json, _destination, _json_bytes, _write


def restore_committed_before_images(
    *, store: LocalStore, run_id: str, expected_journal_sha256: str,
    decision_id: str, input_hash: str, destination: Path,
) -> Path:
    """Verify an external COMMITTED anchor before restoring seven before images.

    The caller must provide the journal SHA from outside the bundle. No source
    state, active pointer or transaction is modified. This is not a replay or
    proof that production consumed the exported files.
    """
    if not isinstance(run_id, str) or len(run_id) != 32 or UUID(hex=run_id).hex != run_id:
        raise ValueError("invalid restore run identity")
    archive = store.archive_dir.resolve()
    data = archive.parent
    journal = checked_path(archive, f".score_run_transactions/runs/{run_id}/manifest.json")
    raw = journal.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_journal_sha256:
        raise ValueError("restore journal digest mismatch")
    record = json.loads(raw)
    if (record.get("schema_version") != SCHEMA_V2 or record.get("status") != "COMMITTED"
            or record.get("run_id") != run_id):
        raise ValueError("restore requires a matching COMMITTED v2 transaction")
    business, evidence = validate_inventory(record)
    binding = record.get("input_binding") or {}
    if binding.get("decision_id") != decision_id or binding.get("input_hash") != input_hash:
        raise ValueError("restore decision binding mismatch")
    validate_input_evidence(record, data)
    prefix = f"archive/decision_inputs/{record['capture_id']}/"
    descriptor = prefix + "pre_state.json"
    if descriptor not in evidence:
        raise ValueError("registered before-image descriptor missing")
    state = json.loads(checked_path(data, descriptor).read_bytes())
    expected_binding = {"run_id": run_id, "capture_id": record["capture_id"],
                        "as_of": record["metadata"]["as_of"]}
    if (set(state) != {"schema_version", "capture_mode", "binding", "artifacts"}
            or state.get("schema_version") != "hermes-score-before-images-v1"
            or state.get("capture_mode") != "V2_PREPARED_BEFORE_IMAGES"
            or state.get("binding") != expected_binding or set(state["artifacts"]) != business):
        raise ValueError("restore before-image descriptor binding mismatch")
    rows = {row["path"]: row for row in record["artifacts"] if row["role"] == "BUSINESS"}
    verified: dict[str, bytes] = {}
    for relative in sorted(business):
        row = rows[relative]
        kind = "SQLITE_BACKUP" if relative.endswith(".sqlite") else "BYTES"
        mode = row.get("before_mode")
        if (row.get("snapshot_format") != kind
                or (row["existed"] and (type(mode) is not int or not 0 <= mode <= 0o777))
                or (not row["existed"] and (mode is not None or row.get("before_sha256") is not None))):
            raise ValueError("restore backup metadata mismatch")
        entry: dict[str, Any] = {"availability": "ABSENT", "path": None, "sha256": None,
                                 "snapshot_format": kind, "before_mode": mode}
        if row["existed"]:
            exported = prefix + "pre_state/" + relative
            entry.update(availability="PRESENT", path=exported, sha256=row.get("before_sha256"))
            if exported not in evidence:
                raise ValueError("unregistered restore before image")
            source = checked_path(data, exported)
            content = source.read_bytes()
            if hashlib.sha256(content).hexdigest() != row.get("before_sha256"):
                raise ValueError("restore before-image digest mismatch")
            if kind == "SQLITE_BACKUP":
                with closing(sqlite3.connect(f"{source.as_uri()}?mode=ro&immutable=1", uri=True)) as db:
                    sqlite_state_hash(db)
            else:
                _check_state_json(content, "JSONL_BYTES" if relative.endswith(".jsonl") else "JSON_BYTES")
            verified[relative] = content
        if state["artifacts"][relative] != entry:
            raise ValueError("restore before-image metadata mismatch")
    registered = {path for path in evidence if path.startswith(prefix + "pre_state/")}
    if registered != {prefix + "pre_state/" + relative for relative in verified}:
        raise ValueError("restore before-image inventory mismatch")
    destination = _destination(destination, [data, store.history_dir, store.legacy_history_dir])
    stage = Path(tempfile.mkdtemp(prefix=".transaction-restore-", dir=destination.parent))
    try:
        for relative, content in verified.items():
            _write(stage, relative, content)
            (stage / relative).chmod(0o600)
        _write(stage, "source_transaction.json", raw)
        _write(stage, "restoration.json", _json_bytes({
            "schema_version": "hermes-offline-before-state-restore-v1",
            "evidence_role": "OFFLINE_BEFORE_STATE_NOT_FULL_REPLAY",
            "source_journal_sha256": expected_journal_sha256,
            "binding": {**expected_binding, "decision_id": decision_id, "input_hash": input_hash},
            "artifacts": state["artifacts"],
        }))
        os.rename(stage, destination)
        return destination
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def restore_committed_runtime_inputs(
    *, store: LocalStore, run_id: str, expected_journal_sha256: str,
    decision_id: str, input_hash: str, destination: Path, external_legacy_layout: bool = False,
) -> Path:
    """Restore a real ON capture and seven before images, never execute it.

    The external journal digest remains authoritative. Inputs retain original
    provenance and bytes; the destination is private, new and offline. This
    operation neither proves replay equivalence nor activates production capture.
    With external_legacy_layout, destination is a private container: the returned
    runtime/ root keeps the default ../data/history inside that container without
    rewriting frozen config. Other history layouts are not supported in this mode.
    """
    data = store.archive_dir.resolve().parent
    if not isinstance(run_id, str) or len(run_id) != 32 or UUID(hex=run_id).hex != run_id:
        raise ValueError("invalid restore run identity")
    journal = checked_path(data, f"archive/.score_run_transactions/runs/{run_id}/manifest.json")
    raw = journal.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_journal_sha256:
        raise ValueError("restore journal digest mismatch")
    record = json.loads(raw)
    validate_input_evidence(record, data)
    bundle = checked_path(data, f"archive/decision_inputs/{record['capture_id']}")
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    config = json.loads((bundle / "config.json").read_bytes())
    if external_legacy_layout and (
            config["paths"].get("history_dir") != "data/history"
            or config["paths"].get("legacy_history_dir") != "../data/history"):
        raise ValueError("external legacy restore requires the default history paths")
    sources = manifest["source_inventory"]
    prefix = bundle.relative_to(data).as_posix() + "/"
    original_roots = [Path(entry["source"]).parent for row in manifest["histories"].values()
                      for entry in (row["primary"], row["legacy"])]
    original_roots.extend(Path(row["source"]).parent.parent for row in sources.values()
                          if row.get("path") == prefix + "certification/market_manifest.json")
    original_roots.extend(Path(row["source"]).parent for row in sources.values()
                          if row.get("path") == prefix + "source/package/pipeline.py")
    destination = _destination(destination, [data, store.history_dir, store.legacy_history_dir, *original_roots])
    stage = Path(tempfile.mkdtemp(prefix=".runtime-input-restore-", dir=destination.parent))
    runtime = stage / "runtime" if external_legacy_layout else stage
    try:
        restore_committed_before_images(
            store=store, run_id=run_id, expected_journal_sha256=expected_journal_sha256,
            decision_id=decision_id, input_hash=input_hash, destination=runtime / "data",
        )
        payload, parameters, histories = (
            json.loads((bundle / name).read_bytes())
            for name in ("payload.json", "parameters.json", "histories.json")
        )
        snapshots = json.loads((bundle / "snapshots.json").read_bytes())
        soft = json.loads((bundle / "soft.json").read_bytes())
        broker = json.loads((bundle / "broker.json").read_bytes())
        certificate = _check_evidence(payload, config)
        _verify_runtime_sources(manifest, bundle, data, certificate, payload)
        if (json.loads((bundle / "configuration.raw.json").read_bytes()) != config
                or payload.get("as_of") != record["metadata"]["as_of"]
                or payload.get("input_hash") != input_hash or certificate["decision_id"] != decision_id
                or (payload.get("persistence") or {}).get("run_id") != run_id
                or payload["persistence"].get("capture_id") != record["capture_id"]
                or snapshots != payload.get("snapshots") or soft.get("value") != payload.get("soft_data")
                or set(soft.get("record_order", [])) != set(soft["value"]["records"])
                or len(soft["record_order"]) != len(soft["value"]["records"])
                or parameters.get("capture_inputs") is not True
                or any(parameters.get(key) != value for key, value in record["metadata"].items())
                or parameters.get("market_admission_status") != payload.get("market_admission_status")):
            raise ValueError("restore runtime input binding mismatch")
        orders = soft.get("record_field_order")
        if "record_field_order" in soft:
            records = soft["value"]["records"]
            if (not isinstance(orders, dict) or set(orders) != set(records)
                    or any(not isinstance(orders[key], list)
                           or any(not isinstance(name, str) for name in orders[key])
                           or set(orders[key]) != set(row.get("fields", {}))
                           or len(orders[key]) != len(row.get("fields", {}))
                           for key, row in records.items())):
                raise ValueError("restore soft field order binding mismatch")
        if (broker.get("schema_version") != "hermes-broker-input-tape-v1"
                or set(broker.get("reads", {})) != {"positions", "executions"}
                or any(row.get("status") not in {"RETURNED", "ERROR", "NOT_READ"}
                       for row in broker["reads"].values())
                or broker.get("outcomes") != {"positions": payload["ibkr"], "executions": payload["execution_sync"]}):
            raise ValueError("restore broker tape binding mismatch")
        _verify_broker_reads(broker["reads"])
        universe = set(certificate["semantic_identity"]["history_hashes"])
        if (set(histories) != universe or set(manifest.get("histories", {})) != universe
                or set(snapshots) != universe | {"SOFT"}
                or scoring_logic_hash(bundle / "source/package") != manifest.get("scoring_logic_hash")
                or manifest["scoring_logic_hash"] != certificate["semantic_identity"]["scoring_logic_hash"]):
            raise ValueError("restore runtime source or universe mismatch")
        materialized = {}
        for symbol in sorted(universe):
            row = manifest["histories"][symbol]
            expected_selected = ("primary" if row["primary"]["availability"] == "PRESENT"
                                 else "legacy" if row["legacy"]["availability"] == "PRESENT" else "missing")
            if row.get("selected") != expected_selected or expected_selected == "missing":
                raise ValueError("restore runtime history selection mismatch")
            frame = pd.DataFrame(histories[symbol]["data"], columns=histories[symbol]["columns"],
                                 index=pd.to_datetime(histories[symbol]["index"]))
            visible_hash = stable_hash(frame.reindex(sorted(frame.columns), axis=1).to_dict(orient="split"))
            if (visible_hash != row.get("visible_hash")
                    or visible_hash != certificate["semantic_identity"]["history_hashes"][symbol]):
                raise ValueError("restore consumed history hash mismatch")
            folders = (("primary", "runtime/data/history"), ("legacy", "data/history")) if external_legacy_layout else (
                ("primary", "data/history"), ("legacy", "data/history_legacy"))
            for role, folder in folders:
                entry = row[role]
                if sources.get(entry.get("source")) != entry:
                    raise ValueError("restore history source binding mismatch")
                relative = f"market/{role}/{safe_symbol(symbol)}.csv"
                if entry["availability"] == "ABSENT":
                    if entry.get("path") is not None or entry.get("sha256") is not None or (bundle / relative).exists():
                        raise ValueError("restore absent history binding mismatch")
                    continue
                expected_path = (bundle / relative).relative_to(data).as_posix()
                if (entry["availability"] != "PRESENT" or entry.get("path") != expected_path
                        or hashlib.sha256((bundle / relative).read_bytes()).hexdigest() != entry.get("sha256")):
                    raise ValueError("restore runtime history bytes mismatch")
                materialized[f"{folder}/{safe_symbol(symbol)}.csv"] = (bundle / relative).read_bytes()
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                _write(runtime, "inputs/" + path.relative_to(bundle).as_posix(), path.read_bytes())
        for relative, content in materialized.items():
            _write(stage, relative, content)
            (stage / relative).chmod(0o600)
        frozen = LocalStore({**config, "paths": {**config["paths"],
                            "history_dir": str(runtime / "data/history"),
                            "legacy_history_dir": str(stage / ("data/history" if external_legacy_layout
                                                              else "data/history_legacy"))}})
        for symbol in sorted(universe):
            frame = frozen.load_history(symbol)
            visible = frame.loc[frame.index <= pd.Timestamp(payload["as_of"])]
            digest = stable_hash(visible.reindex(sorted(visible.columns), axis=1).to_dict(orient="split"))
            if digest != manifest["histories"][symbol]["visible_hash"]:
                raise ValueError("restore raw history consumption mismatch")
        for path in sorted((bundle / "source/package").rglob("*.py")):
            _write(runtime, "package/" + path.relative_to(bundle / "source/package").as_posix(), path.read_bytes())
        for name, target in (("VERSION", "package/VERSION"),
                             ("approved_live_config.json", "package/governance/approved_live_config.json"),
                             ("market_manifest.json", "data/archive/data_manifest_latest.json")):
            source = bundle / "certification" / name
            if source.is_file():
                _write(runtime, target, source.read_bytes())
        for path in sorted((bundle / "soft_sources").glob("*.csv")):
            _write(runtime, "data/soft_history/" + path.name, path.read_bytes())
        _write(runtime, "config.json", (bundle / "configuration.raw.json").read_bytes())
        _write(runtime, "restoration.json", _json_bytes({
            "schema_version": "hermes-offline-runtime-input-restore-v1",
            "evidence_role": "OFFLINE_RUNTIME_INPUTS_NOT_FULL_REPLAY",
            "source_journal_sha256": expected_journal_sha256,
            "binding": manifest["binding"], "original_source_inventory": manifest["source_inventory"],
            **({"history_layout": {"mode": "DEFAULT_EXTERNAL_LEGACY", "runtime": "runtime",
                                   "primary": "runtime/data/history", "legacy": "data/history"}}
               if external_legacy_layout else {}),
        }))
        for path in stage.rglob("*"):
            if path.is_dir():
                path.chmod(0o700)
        os.rename(stage, destination)
        return destination / "runtime" if external_legacy_layout else destination
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def _verify_runtime_sources(manifest, bundle, data, certificate, payload) -> None:
    prefix = bundle.relative_to(data).as_posix() + "/"
    sources = manifest.get("source_inventory")
    if not isinstance(sources, dict):
        raise ValueError("restore runtime source inventory missing")
    for name, row in sources.items():
        if not Path(name).is_absolute() or row.get("source") != name:
            raise ValueError("restore runtime source binding mismatch")
        if row.get("availability") == "ABSENT":
            if row.get("path") is not None or row.get("sha256") is not None:
                raise ValueError("restore runtime absent source binding mismatch")
        elif (row.get("availability") != "PRESENT" or not isinstance(row.get("path"), str)
              or not row["path"].startswith(prefix)
              or hashlib.sha256(checked_path(data, row["path"]).read_bytes()).hexdigest() != row.get("sha256")):
            raise ValueError("restore runtime source binding mismatch")
    by_path = {row["path"]: name for name, row in sources.items() if row["availability"] == "PRESENT"}
    package_source = Path(by_path[prefix + "source/package/pipeline.py"]).parent
    required_reads = {by_path[prefix + "certification/market_manifest.json"],
                      by_path[prefix + "certification/approved_live_config.json"], str(package_source / "VERSION")}
    version = bundle / "certification/VERSION"
    if version.exists():
        fields = version.read_text().split()
        if not fields:
            raise ValueError("restore certification VERSION missing")
        release = fields[0]
    else:
        required_reads.update(name for path, name in by_path.items() if path.startswith(prefix + "source/package/"))
        release = _release_hash(bundle / "source/package")
    certification = json.loads((bundle / "certification.json").read_bytes())
    reads = certification.get("reads", [])
    certified_at = datetime.fromisoformat(certificate["certified_at"])
    run_at = datetime.fromisoformat(payload["run_ts"])
    if (len(reads) != len(required_reads) or {row.get("source") for row in reads} != required_reads
            or any(row != sources.get(row.get("source")) for row in reads)
            or certification.get("certified_at") != certificate["certified_at"]
            or certified_at.tzinfo is None or run_at.tzinfo is None or certified_at != run_at
            or certificate["policy_hash"] != hashlib.sha256((bundle / "certification/approved_live_config.json").read_bytes()).hexdigest()
            or certificate["canonical_market_evidence_hash"] != json.loads((bundle / "certification/market_manifest.json").read_bytes())["manifest_id"]
            or certificate["scorer_release_hash"] != release):
        raise ValueError("restore certification material binding mismatch")


def _verify_broker_reads(reads) -> None:
    from ...ibkr.executions import ExecutionSnapshot
    from ...ibkr.positions import PositionSnapshot

    for name, snapshot_type in (("positions", PositionSnapshot), ("executions", ExecutionSnapshot)):
        row = reads[name]
        if row["status"] == "RETURNED":
            try:
                valid = (isinstance(row.get("snapshot"), dict) and row.get("reason") is None
                         and row.get("error") is None
                         and snapshot_type.from_dict(row["snapshot"]).to_dict() == row["snapshot"])
            except (KeyError, TypeError, ValueError):
                valid = False
        elif row["status"] == "ERROR":
            valid = row.get("snapshot") is None and row.get("reason") is None and isinstance(row.get("error"), str)
        else:
            valid = (row.get("snapshot") is None and row.get("error") is None
                     and isinstance(row.get("reason"), str) and bool(row["reason"]))
        if not valid:
            raise ValueError("restore broker response binding mismatch")
