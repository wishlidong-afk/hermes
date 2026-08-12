#!/usr/bin/env python3
"""Compare score payloads and persisted artifacts across two source trees.

Each source runs against a fresh clone of the same history/soft-history seed.
Volatile timestamps and temporary data-root prefixes are normalized; schemas,
rows, JSON fields, row order within JSONL, and all other values stay strict.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


VOLATILE_KEYS = {
    "checked_at",
    "completed_at",
    "created_at",
    "generated_at",
    "run_ts",
    "started_at",
    "updated_at",
    "written_at",
}
INTENTIONAL_METADATA_KEYS = {"persistence"}
SEED_SUBDIRS = ("history", "soft_history")
SOURCE_FINGERPRINT_ROOTS = ("src/hermes_escape_top",)
SOURCE_FINGERPRINT_EXCLUDES = (
    "src/hermes_escape_top/data",
    "src/hermes_escape_top/tests/__pycache__",
)
STATIC_BUSINESS_ARTIFACTS = {
    "audit_log.jsonl",
    "flow_reference.sqlite",
    "hermes_state.sqlite",
    "mirror_reference.sqlite",
    "reentry_state.sqlite",
    "signal_journal.jsonl",
}


def _business_artifact_names(as_of: str) -> set[str]:
    return {
        *STATIC_BUSINESS_ARTIFACTS,
        f"soft_adapter_snapshot_{str(as_of)[:10]}.json",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-source", type=Path, required=True)
    parser.add_argument("--candidate-source", type=Path, required=True)
    parser.add_argument("--seed-data", type=Path, required=True)
    parser.add_argument("--as-of", action="append", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--contract",
        choices=("strict", "decision-quality-v1"),
        default="strict",
    )
    parser.add_argument("--baseline-label")
    parser.add_argument("--candidate-label")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report: dict[str, Any] = {
        "schema_version": "hermes-pipeline-persistence-equivalence-v2",
        "contract": args.contract,
        "baseline_source": str(args.baseline_source.resolve()),
        "candidate_source": str(args.candidate_source.resolve()),
        "baseline_source_evidence": {
            "label": args.baseline_label,
            **_tree_fingerprint(
                args.baseline_source,
                relative_roots=SOURCE_FINGERPRINT_ROOTS,
                excluded_prefixes=SOURCE_FINGERPRINT_EXCLUDES,
            ),
        },
        "candidate_source_evidence": {
            "label": args.candidate_label,
            **_tree_fingerprint(
                args.candidate_source,
                relative_roots=SOURCE_FINGERPRINT_ROOTS,
                excluded_prefixes=SOURCE_FINGERPRINT_EXCLUDES,
            ),
        },
        "seed_evidence": _tree_fingerprint(
            args.seed_data,
            relative_roots=(*SEED_SUBDIRS, "sentiment.xls"),
        ),
        "python_evidence": _python_evidence(args.python),
        "comparator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope_notes": [
            "Covers score_pipeline persistence: four SQLite files, two JSONL ledgers, and the dated soft-adapter snapshot.",
            "Timestamps, temporary data-root prefixes, and the audit row's timestamp-derived payload_hash are normalized.",
            "The recoverable transaction envelope is omitted because its random run_id is operational metadata; every business field and persisted row remains strict.",
            "Source and seed manifests bind every compared run to relative paths, byte sizes, and SHA-256 values.",
        ],
        "dates": {},
    }
    all_equal = True
    with tempfile.TemporaryDirectory(prefix="hermes-persistence-equivalence-") as tmp:
        temp_root = Path(tmp)
        for as_of in args.as_of:
            baseline = _run_and_snapshot(
                args.baseline_source,
                args.seed_data,
                temp_root / f"baseline-{as_of}",
                as_of,
                args.python,
            )
            candidate = _run_and_snapshot(
                args.candidate_source,
                args.seed_data,
                temp_root / f"candidate-{as_of}",
                as_of,
                args.python,
            )
            strict_differences = _differences(baseline, candidate)
            differences = _contract_differences(
                baseline,
                candidate,
                contract=args.contract,
            )
            equal = not differences
            all_equal = all_equal and equal
            report["dates"][as_of] = {
                "equal": equal,
                "differences": differences,
                "strict_differences": strict_differences,
                "baseline": _summary(baseline),
                "candidate": _summary(candidate),
            }
    report["all_equal"] = all_equal
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"all_equal": all_equal, "output": str(args.output)}, ensure_ascii=False))
    return 0 if all_equal else 1


def _tree_fingerprint(
    root: Path,
    *,
    relative_roots: tuple[str, ...],
    excluded_prefixes: tuple[str, ...] = (),
) -> dict[str, Any]:
    root = root.resolve()
    entries: list[dict[str, Any]] = []
    for relative_root in relative_roots:
        selected = root / relative_root
        if not selected.exists() and not selected.is_symlink():
            continue
        paths = [selected] if selected.is_file() or selected.is_symlink() else selected.rglob("*")
        for path in sorted(paths, key=lambda item: item.as_posix()):
            if not path.is_file() and not path.is_symlink():
                continue
            relative = path.relative_to(root).as_posix()
            if relative.endswith(".pyc") or "__pycache__" in Path(relative).parts:
                continue
            if any(
                relative == prefix or relative.startswith(prefix.rstrip("/") + "/")
                for prefix in excluded_prefixes
            ):
                continue
            if path.is_symlink():
                content = os.readlink(path).encode("utf-8")
                kind = "symlink"
            else:
                content = path.read_bytes()
                kind = "file"
            entries.append(
                {
                    "path": relative,
                    "kind": kind,
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
    manifest_payload = json.dumps(
        entries,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "relative_roots": list(relative_roots),
        "excluded_prefixes": list(excluded_prefixes),
        "file_count": len(entries),
        "total_bytes": sum(int(entry["size"]) for entry in entries),
        "manifest_sha256": hashlib.sha256(manifest_payload).hexdigest(),
        "files": entries,
    }


def _python_evidence(python: str) -> dict[str, Any]:
    child = """
import importlib.metadata as metadata
import json
import platform
import sys

def package_version(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None

print(json.dumps({
    "executable": sys.executable,
    "python": platform.python_version(),
    "numpy": package_version("numpy"),
    "pandas": package_version("pandas"),
    "scipy": package_version("scipy"),
}, sort_keys=True))
"""
    result = subprocess.run(
        [python, "-c", child],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"python evidence failed: {result.stderr[-2000:]}")
    evidence = json.loads(result.stdout)
    executable = Path(str(evidence["executable"])).resolve()
    evidence["executable_resolved"] = str(executable)
    evidence["executable_sha256"] = (
        hashlib.sha256(executable.read_bytes()).hexdigest()
        if executable.is_file()
        else None
    )
    return evidence


def _run_and_snapshot(
    source: Path,
    seed_data: Path,
    data_root: Path,
    as_of: str,
    python: str,
) -> dict[str, Any]:
    _seed_data(seed_data, data_root)
    payload_path = data_root / "payload.json"
    child = """
import json
import sys
from pathlib import Path
from hermes_escape_top.pipeline import score_pipeline

payload = score_pipeline(sys.argv[1], include_ibkr=False, shadow=False)
Path(sys.argv[2]).write_text(
    json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
    encoding="utf-8",
)
"""
    env = os.environ.copy()
    env["HERMES_DATA_DIR"] = str(data_root)
    env["PYTHONPATH"] = str(source.resolve() / "src")
    result = subprocess.run(
        [python, "-c", child, as_of, str(payload_path)],
        cwd=source,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"score run failed for {source} at {as_of}:\n"
            f"stdout:\n{result.stdout[-4000:]}\n"
            f"stderr:\n{result.stderr[-4000:]}"
        )
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    archive = data_root / "data" / "archive"
    artifacts = {}
    for name in sorted(_business_artifact_names(as_of)):
        path = archive / name
        if not path.exists():
            artifacts[name] = {"missing": True}
        elif path.suffix == ".sqlite":
            artifacts[name] = _snapshot_sqlite(path, data_root)
        elif path.suffix == ".jsonl":
            artifacts[name] = _snapshot_jsonl(path, data_root)
        else:
            artifacts[name] = _normalize(
                json.loads(path.read_text(encoding="utf-8")),
                data_root,
            )
    return {
        "payload": _normalize(payload, data_root),
        "artifacts": artifacts,
    }


def _seed_data(seed_data: Path, data_root: Path) -> None:
    target = data_root / "data"
    target.mkdir(parents=True)
    for subdir in SEED_SUBDIRS:
        source = seed_data / subdir
        if source.exists():
            _clone(source, target / subdir)
    for name in ("sentiment.xls",):
        source = seed_data / name
        if source.exists():
            _clone(source, target / name)
    (target / "archive").mkdir()


def _clone(source: Path, target: Path) -> None:
    result = subprocess.run(["cp", "-Rc", str(source), str(target)], capture_output=True)
    if result.returncode == 0:
        return
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)


def _snapshot_sqlite(path: Path, data_root: Path) -> dict[str, Any]:
    tables = {}
    with sqlite3.connect(path) as conn:
        names = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        for name in names:
            quoted = name.replace('"', '""')
            columns = [
                {
                    "name": row[1],
                    "type": row[2],
                    "notnull": row[3],
                    "default": row[4],
                    "pk": row[5],
                }
                for row in conn.execute(f'PRAGMA table_info("{quoted}")')
            ]
            raw_rows = conn.execute(f'SELECT * FROM "{quoted}" ORDER BY rowid').fetchall()
            rows = []
            for raw in raw_rows:
                row = {}
                for column, value in zip(columns, raw):
                    row[column["name"]] = _normalize_sql_value(
                        column["name"], value, data_root
                    )
                rows.append(row)
            tables[name] = {"columns": columns, "rows": rows}
    return tables


def _snapshot_jsonl(path: Path, data_root: Path) -> dict[str, Any]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if path.name == "audit_log.jsonl" and "payload_hash" in row:
                # The audit hash includes payload.run_ts, which is intentionally
                # volatile. Keep every nested payload field strict after the
                # timestamp normalization, and normalize only this derived hash.
                row = dict(row)
                row["payload_hash"] = "$TIMESTAMP_DERIVED_HASH"
            rows.append(_normalize(row, data_root))
    return {"rows": rows}


def _normalize_sql_value(column: str, value: Any, data_root: Path) -> Any:
    if column in VOLATILE_KEYS:
        return "$TIME"
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return _normalize(json.loads(value), data_root)
            except json.JSONDecodeError:
                pass
    return _normalize(value, data_root)


def _normalize(value: Any, data_root: Path) -> Any:
    if isinstance(value, dict):
        return {
            key: "$TIME" if key in VOLATILE_KEYS else _normalize(item, data_root)
            for key, item in sorted(value.items())
            if key not in INTENTIONAL_METADATA_KEYS
        }
    if isinstance(value, list):
        return [_normalize(item, data_root) for item in value]
    if isinstance(value, str):
        return value.replace(str(data_root.resolve()), "$DATA_ROOT")
    return value


def _differences(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    differences = []
    if baseline["payload"] != candidate["payload"]:
        differences.append("payload")
    baseline_artifacts = baseline["artifacts"]
    candidate_artifacts = candidate["artifacts"]
    for name in sorted(set(baseline_artifacts) | set(candidate_artifacts)):
        if baseline_artifacts.get(name) != candidate_artifacts.get(name):
            differences.append(f"artifact:{name}")
    return differences


def _contract_differences(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    contract: str,
) -> list[str]:
    if contract == "strict":
        return _differences(baseline, candidate)
    if contract != "decision-quality-v1":
        raise ValueError(f"unsupported comparison contract: {contract}")
    return _differences(
        _strip_decision_quality_reporting(baseline),
        _strip_decision_quality_reporting(candidate),
    )


def _strip_decision_quality_reporting(snapshot: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(snapshot)
    _strip_payload_reporting(normalized.get("payload"))
    artifacts = normalized.get("artifacts") or {}

    audit = artifacts.get("audit_log.jsonl") or {}
    for row in audit.get("rows") or []:
        if isinstance(row, dict):
            _strip_payload_reporting(row.get("payload"))

    state = artifacts.get("hermes_state.sqlite") or {}
    for row in ((state.get("data_sources") or {}).get("rows") or []):
        payload = row.get("payload_json") if isinstance(row, dict) else None
        if isinstance(payload, dict):
            payload.pop("decision_bearing", None)
            payload.pop("decision_role", None)
    for row in ((state.get("decisions") or {}).get("rows") or []):
        payload = row.get("payload_json") if isinstance(row, dict) else None
        if isinstance(payload, dict):
            _strip_intent_confidence(payload.get("intent"))
            _strip_layer_confidence(payload.get("layer"))
    for row in ((state.get("score_runs") or {}).get("rows") or []):
        if not isinstance(row, dict):
            continue
        row.pop("data_quality_score", None)
        _strip_payload_reporting(row.get("payload_json"))
    return normalized


def _strip_payload_reporting(payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    for key in ("data_quality", "all_source_data_quality", "data_quality_breakdown"):
        payload.pop(key, None)
    for layer in (payload.get("decision_layers") or {}).values():
        _strip_layer_confidence(layer)
    for intent in (payload.get("action_intents") or {}).values():
        _strip_intent_confidence(intent)
    today_ops = payload.get("today_ops")
    if isinstance(today_ops, dict):
        today_ops.pop("data_quality", None)
        today_ops.pop("data_quality_score", None)


def _strip_layer_confidence(layer: Any) -> None:
    if not isinstance(layer, dict):
        return
    layer.pop("strategy_confidence", None)
    layer.pop("action_confidence", None)


def _strip_intent_confidence(intent: Any) -> None:
    if not isinstance(intent, dict):
        return
    intent.pop("confidence_score", None)
    intent.pop("strategy_confidence_score", None)


def _summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = snapshot["payload"]
    artifacts = snapshot["artifacts"]
    return {
        "input_hash": payload.get("input_hash"),
        "status": {
            symbol: row.get("status")
            for symbol, row in sorted((payload.get("scores") or {}).items())
        },
        "payload_sha256": _hash(payload),
        "artifacts": {
            name: {
                "sha256": _hash(value),
                "tables": {
                    table: len(content.get("rows", []))
                    for table, content in sorted(value.items())
                    if isinstance(content, dict) and "rows" in content
                },
                "jsonl_rows": len(value.get("rows", [])) if isinstance(value, dict) else 0,
                "missing": bool(value.get("missing")) if isinstance(value, dict) else False,
            }
            for name, value in sorted(artifacts.items())
        },
    }


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
