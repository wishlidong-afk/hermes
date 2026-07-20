#!/usr/bin/env python3
"""Compare score payloads and persisted artifacts across two source trees.

Each source runs against a fresh clone of the same history/soft-history seed.
Volatile timestamps and temporary data-root prefixes are normalized; schemas,
rows, JSON fields, row order within JSONL, and all other values stay strict.
"""
from __future__ import annotations

import argparse
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report: dict[str, Any] = {
        "schema_version": "hermes-pipeline-persistence-equivalence-v1",
        "baseline_source": str(args.baseline_source.resolve()),
        "candidate_source": str(args.candidate_source.resolve()),
        "scope_notes": [
            "Covers score_pipeline persistence: four SQLite files, two JSONL ledgers, and the dated soft-adapter snapshot.",
            "Timestamps, temporary data-root prefixes, and the audit row's timestamp-derived payload_hash are normalized.",
            "The recoverable transaction envelope is omitted because its random run_id is operational metadata; every business field and persisted row remains strict.",
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
            differences = _differences(baseline, candidate)
            equal = not differences
            all_equal = all_equal and equal
            report["dates"][as_of] = {
                "equal": equal,
                "differences": differences,
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
