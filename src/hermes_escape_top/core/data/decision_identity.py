"""Decision inputs, separate from the provenance of each certification attempt."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from .source_relevance import soft_record_is_decision_bearing


def stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def decision_outputs(payload: Mapping[str, Any]) -> dict[str, Any]:
    # These are already-computed decisions, not wall-clock/state database receipts.
    return {key: payload.get(key) for key in (
        "scores", "regime", "sizing", "routing", "reentry",
        "portfolio_target_weights", "confidence_spine",
    )}


def semantic_identity(
    payload: Mapping[str, Any], config: Mapping[str, Any],
    histories: Mapping[str, pd.DataFrame | None], package_root: Path,
) -> dict[str, Any]:
    as_of = str(payload["as_of"])[:10]
    snapshots = payload.get("snapshots")
    if not isinstance(snapshots, Mapping) or not snapshots:
        raise ValueError("decision identity requires scored snapshots")
    if stable_hash(snapshots) != payload.get("input_hash"):
        raise ValueError("decision input_hash does not match scored snapshots")
    if set(histories) != set(snapshots) - {"SOFT"}:
        raise ValueError("decision histories must cover the actual snapshot universe")
    soft = payload.get("soft_data") or {}
    records = soft.get("records") or {}
    active = {
        name: record for name, record in records.items()
        if soft_record_is_decision_bearing(config, name)
    }
    excluded_fields = set()
    for name, record in records.items():
        if name not in active:
            excluded_fields.add(name)
            excluded_fields.update((record.get("fields") or {}).keys())
    scoped_snapshots = dict(snapshots)
    if "SOFT" in snapshots:
        soft_snapshot = dict(snapshots["SOFT"])
        soft_snapshot["fields"] = {
            name: field for name, field in soft_snapshot.get("fields", {}).items()
            if name not in excluded_fields
        }
        scoped_snapshots["SOFT"] = soft_snapshot
    valuation = active.get("valuation")
    stable_source = _valuation_source_alias(valuation, config, package_root)
    if stable_source is not None and isinstance(valuation, Mapping):
        active["valuation"] = {**valuation, "source": stable_source}
        if "SOFT" in scoped_snapshots:
            fields = scoped_snapshots["SOFT"]["fields"]
            for name in ("valuation", "FNGU_valuation_pctl", "MSTR_valuation_pctl", "SOXL_valuation_pctl"):
                field = fields.get(name)
                if (name == "valuation" or name in valuation.get("fields", {})) and isinstance(field, Mapping):
                    if field.get("source") == valuation["source"]:
                        fields[name] = {**field, "source": stable_source}
    history_hashes: dict[str, str | None] = {}
    for symbol, frame in sorted(histories.items()):
        if frame is None:
            history_hashes[symbol] = None
            continue
        visible = frame.loc[frame.index <= pd.Timestamp(as_of)]
        # Column order is not an input; row order, missing values and precision are.
        visible = visible.reindex(sorted(visible.columns), axis=1)
        history_hashes[symbol] = stable_hash(visible.to_dict(orient="split"))
    return {
        "as_of": as_of,
        "scored_snapshot_hash": stable_hash(scoped_snapshots),
        "history_hashes": history_hashes,
        "soft_input_hash": stable_hash(_soft_inputs(active)),
        "effective_config_hash": stable_hash(_effective_config(config)),
        "scoring_logic_hash": scoring_logic_hash(package_root),
        "decision_outputs_hash": stable_hash(decision_outputs(payload)),
    }


def _valuation_source_alias(
    record: Any, config: Mapping[str, Any], package_root: Path,
) -> str | None:
    # Only the two default R6 links are aliases. Keep the raw record and
    # input_hash intact; this verifies location, not historical file contents.
    if not isinstance(record, Mapping) or (config.get("valuation") or {}).get("snapshot_path"):
        return None
    package = Path(package_root).resolve()
    release = package.parent
    if package.name != "hermes_escape_top" or release.parent.name != "releases":
        return None
    live = release.parent.parent
    roots = {
        release / "data": live / "data",
        package / "data": live / "shared/hermes_escape_top/data",
    }
    for alias, shared in roots.items():
        if record.get("source") != str(alias / "valuation_snapshot.json"):
            continue
        try:
            target = alias / "valuation_snapshot.json"
            if (not alias.is_symlink() or alias.resolve(strict=True) != shared
                    or target.resolve(strict=True) != shared / target.name
                    or not target.is_file()):
                raise ValueError("valuation source alias is not verified")
            with target.open("rb"):
                pass
        except (OSError, RuntimeError) as exc:
            raise ValueError("valuation source alias is not verified") from exc
        return str(shared / target.name)
    return None


def _soft_inputs(records: Mapping[str, Any]) -> dict[str, Any]:
    # Exclude only known acquisition timestamps. Publication/availability/source
    # and unknown fields remain material; this is not a generic timestamp scrub.
    return {
        name: {key: value for key, value in record.items()
               if key not in {"fetched_at", "downloaded_at", "checked_at"}}
        for name, record in records.items()
    }


def _effective_config(config: Mapping[str, Any]) -> dict[str, Any]:
    # Path resolution and UI metadata are attested separately. Runtime/IBKR
    # settings remain conservative because they can affect state-driven decisions.
    return {key: value for key, value in config.items()
            if not key.startswith("_") and key not in {"web", "paths"}}


def scoring_logic_hash(package_root: Path) -> str:
    excluded = {"tests", "web", "scripts", "research", "reporting", "__pycache__"}
    certification_files = {"core/data/decision_identity.py", "core/data/decision_revision.py"}
    sources = {}
    for path in sorted(package_root.rglob("*.py")):
        relative = path.relative_to(package_root)
        if set(relative.parts) & excluded or relative.as_posix() in certification_files:
            continue
        sources[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not sources:
        raise ValueError("decision identity requires scoring source files")
    return stable_hash(sources)
