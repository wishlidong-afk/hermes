#!/usr/bin/env python3
"""Fail when config, flag registry, context snapshot, or baseline metadata drift."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional


SNAPSHOT_START = "<!-- HERMES_GOVERNANCE_SNAPSHOT_START -->"
SNAPSHOT_END = "<!-- HERMES_GOVERNANCE_SNAPSHOT_END -->"
FLAG_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*([^|]+)\|", re.MULTILINE)


def parse_registry_defaults(markdown: str) -> dict[str, bool]:
    defaults = {}
    active_registry = markdown.split("## Dead flags", 1)[0]
    for flag, cell in FLAG_ROW.findall(active_registry):
        upper = cell.upper()
        if "OFF" in upper:
            defaults[flag] = False
        elif "ON" in upper:
            defaults[flag] = True
    return defaults


def governance_snapshot(config: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    features = config.get("features") or {}
    return {
        "schema_version": "hermes-governance-snapshot-v1",
        "config_version": config.get("version"),
        "module_caps": config.get("module_caps"),
        "status_thresholds": config.get("status_thresholds"),
        "enabled_features": sorted(key for key, value in features.items() if value is True),
        "disabled_features": sorted(key for key, value in features.items() if value is False),
        "routing_defcon1": (config.get("routing") or {}).get("defcon1"),
        "reentry_tranches": (config.get("reentry") or {}).get("tranches"),
        "ibkr_readonly": (config.get("ibkr") or {}).get("readonly"),
        "baseline": {
            "git_commit": baseline.get("git_commit"),
            "equity_timing": baseline.get("equity_timing"),
            "effective_end": baseline.get("effective_end"),
            "evidence_status": baseline.get("evidence_status"),
        },
    }


def render_snapshot_block(snapshot: dict[str, Any]) -> str:
    body = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True)
    return f"{SNAPSHOT_START}\n```json\n{body}\n```\n{SNAPSHOT_END}"


def extract_context_snapshot(markdown: str) -> Optional[dict[str, Any]]:
    if SNAPSHOT_START not in markdown or SNAPSHOT_END not in markdown:
        return None
    body = markdown.split(SNAPSHOT_START, 1)[1].split(SNAPSHOT_END, 1)[0].strip()
    if body.startswith("```json"):
        body = body[len("```json"):].strip()
    if body.endswith("```"):
        body = body[:-3].strip()
    try:
        value = json.loads(body)
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def check_repository(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    _ensure_src(root)
    from hermes_escape_top.config import validate_config

    config_path = root / "src" / "hermes_escape_top" / "config" / "config.json"
    registry_path = root / "docs" / "FLAG_REGISTRY.md"
    context_path = root / "context.md"
    baseline_path = root / "building" / "reports" / "flag_sweep" / "baseline.json"
    baseline_doc_path = root / "docs" / "BASELINE_CURRENT.md"
    gate_doc_path = root / "building" / "reports" / "flag_sweep" / "GATE_BASELINE_CURRENT.md"
    errors: list[str] = []
    checks = {}

    config = json.loads(config_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    try:
        validate_config(config)
        checks["config_invariants"] = "OK"
    except Exception as exc:
        checks["config_invariants"] = "ERROR"
        errors.append(f"config invariants: {exc}")

    registry_defaults = parse_registry_defaults(registry_path.read_text(encoding="utf-8"))
    config_features = config.get("features") or {}
    missing_flags = sorted(set(config_features) - set(registry_defaults))
    extra_flags = sorted(set(registry_defaults) - set(config_features))
    mismatched_flags = sorted(
        key for key in set(config_features) & set(registry_defaults)
        if bool(config_features[key]) != bool(registry_defaults[key])
    )
    if missing_flags or extra_flags or mismatched_flags:
        checks["flag_registry"] = "ERROR"
        if missing_flags:
            errors.append("FLAG_REGISTRY missing: " + ", ".join(missing_flags))
        if extra_flags:
            errors.append("FLAG_REGISTRY unknown: " + ", ".join(extra_flags))
        if mismatched_flags:
            errors.append("FLAG_REGISTRY default mismatch: " + ", ".join(mismatched_flags))
    else:
        checks["flag_registry"] = "OK"

    context_text = context_path.read_text(encoding="utf-8")
    expected_snapshot = governance_snapshot(config, baseline)
    actual_snapshot = extract_context_snapshot(context_text)
    context_errors = []
    if actual_snapshot != expected_snapshot:
        context_errors.append("machine governance snapshot differs from config/baseline")
    if "FRED observations use PIT-safe `date+1` publish dates" not in context_text:
        context_errors.append("FRED date+1 PIT statement missing")
    if "已改用 API `realtime_start` 作为 PIT" in context_text:
        context_errors.append("stale realtime_start PIT claim remains")
    if context_errors:
        checks["context_snapshot"] = "ERROR"
        errors.extend(f"context: {message}" for message in context_errors)
    else:
        checks["context_snapshot"] = "OK"

    baseline_errors = _baseline_errors(baseline, baseline_doc_path, gate_doc_path)
    baseline_errors.extend(_baseline_source_errors(root))
    if baseline_errors:
        checks["baseline_metadata"] = "ERROR"
        errors.extend(f"baseline: {message}" for message in baseline_errors)
    else:
        checks["baseline_metadata"] = "OK"

    factor_capacity_errors = _factor_capacity_errors(root, config)
    if factor_capacity_errors:
        checks["factor_capacity"] = "ERROR"
        errors.extend(f"factor capacity: {message}" for message in factor_capacity_errors)
    else:
        checks["factor_capacity"] = "OK"

    from hermes_escape_top.governance.live_config_policy import (
        LiveConfigPolicyError,
        load_policy,
        validate_repository_policy,
    )

    policy_path = root / "src/hermes_escape_top/governance/approved_live_config.json"
    try:
        validate_repository_policy(config, load_policy(policy_path))
        checks["live_config_policy"] = "OK"
    except (LiveConfigPolicyError, OSError, ValueError) as exc:
        checks["live_config_policy"] = "ERROR"
        errors.append(f"live config policy: {exc}")

    return {
        "schema_version": "hermes-governance-check-v1",
        "ok": not errors,
        "checks": checks,
        "errors": errors,
        "snapshot": expected_snapshot,
    }


def _baseline_errors(baseline: dict[str, Any], baseline_doc_path: Path, gate_doc_path: Path) -> list[str]:
    errors = []
    commit = str(baseline.get("git_commit") or "")
    timing = str(baseline.get("equity_timing") or "")
    metrics = baseline.get("metrics") or {}
    evidence_status = str(baseline.get("evidence_status") or "")
    if evidence_status not in {"CURRENT_EXECUTION_EVIDENCE", "STALE"}:
        errors.append(f"unsupported evidence_status: {evidence_status or 'missing'}")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        errors.append("git_commit is not a full SHA")
    if timing != "next_open":
        errors.append(f"equity_timing must be next_open, got {timing}")
    expected_text = (
        commit,
        "next_open",
        f"{float(metrics.get('cagr', 0.0)):.2%}",
        f"{float(metrics.get('max_drawdown', 0.0)):.2%}",
        f"{float(metrics.get('sharpe', 0.0)):.3f}",
    )
    for path in (baseline_doc_path, gate_doc_path):
        if not path.exists():
            errors.append(f"missing {path.name}")
            continue
        text = path.read_text(encoding="utf-8")
        required_label = "Status: **STALE**" if evidence_status == "STALE" else "CURRENT EXECUTION EVIDENCE"
        if required_label not in text:
            errors.append(f"{path.name} missing {required_label}")
        for expected in expected_text:
            if expected not in text:
                errors.append(f"{path.name} missing {expected}")
    return errors


def _baseline_source_errors(root: Path) -> list[str]:
    artifact_dir = Path(root) / "building" / "reports" / "current_baseline"
    timing_path = artifact_dir / "execution_timing" / "EXECUTION_TIMING_SENSITIVITY.json"
    if not timing_path.exists():
        return [f"missing execution timing source metadata: {timing_path}"]
    try:
        timing = json.loads(timing_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"execution timing source metadata unreadable: {exc}"]
    expected_sha = str((timing.get("source") or {}).get("sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        return ["execution timing source sha256 is missing or invalid"]

    raw_path = artifact_dir / "CURRENT_BASELINE_FULL.json"
    archive_path = artifact_dir / "CURRENT_BASELINE_FULL.json.gz"
    candidates: list[tuple[str, bytes]] = []
    if raw_path.exists():
        try:
            candidates.append((raw_path.name, raw_path.read_bytes()))
        except OSError as exc:
            return [f"full provenance source unreadable: {exc}"]
    if archive_path.exists():
        try:
            candidates.append((archive_path.name, gzip.decompress(archive_path.read_bytes())))
        except (OSError, EOFError) as exc:
            return [f"compressed full provenance source unreadable: {exc}"]
    if not candidates:
        return [f"missing full provenance source: {raw_path.name} or {archive_path.name}"]

    errors = []
    for name, payload in candidates:
        actual_sha = hashlib.sha256(payload).hexdigest()
        if actual_sha != expected_sha:
            errors.append(f"{name} sha256 mismatch: {actual_sha} != {expected_sha}")
    return errors


def _factor_capacity_errors(root: Path, config: dict[str, Any]) -> list[str]:
    from hermes_escape_top.core.scoring.capacity import factor_capacity_inventory

    path = Path(root) / "building/reports/factor_capacity/FACTOR_CAPACITY_INVENTORY.json"
    if not path.exists():
        return [f"missing generated inventory: {path}"]
    try:
        actual = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"generated inventory unreadable: {exc}"]
    expected = factor_capacity_inventory(config)
    if actual != expected:
        return ["generated inventory differs from current scoring definitions/config"]
    return []


def _ensure_src(root: Path) -> None:
    src = str(root / "src")
    if src not in sys.path:
        sys.path.insert(0, src)


def _write_context_snapshot(root: Path, snapshot: dict[str, Any]) -> None:
    path = root / "context.md"
    text = path.read_text(encoding="utf-8")
    block = render_snapshot_block(snapshot)
    if SNAPSHOT_START in text and SNAPSHOT_END in text:
        prefix = text.split(SNAPSHOT_START, 1)[0].rstrip()
        suffix = text.split(SNAPSHOT_END, 1)[1].lstrip()
        updated = f"{prefix}\n\n{block}\n\n{suffix}"
    else:
        lines = text.splitlines()
        insert_at = 1 if lines else 0
        lines[insert_at:insert_at] = ["", block, ""]
        updated = "\n".join(lines)
    path.write_text(updated.rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--write-context-snapshot", action="store_true")
    args = parser.parse_args()
    report = check_repository(args.root)
    if args.write_context_snapshot:
        _write_context_snapshot(args.root, report["snapshot"])
        report = check_repository(args.root)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
