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
MAX_REQUIRED_MODELED_OPEN_SHARE = 0.15


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

    execution_open_errors = _execution_open_quality_errors(root)
    if execution_open_errors:
        checks["execution_open_quality"] = "ERROR"
        errors.extend(f"execution open quality: {message}" for message in execution_open_errors)
    else:
        checks["execution_open_quality"] = "OK"

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
    source_metadata = timing.get("source") or {}
    errors: list[str] = []
    expected_source_path = (
        "building/reports/current_baseline/CURRENT_BASELINE_FULL.json.gz"
    )
    if source_metadata.get("path") != expected_source_path:
        errors.append(
            "execution timing source path must reference retained gzip artifact"
        )
    if source_metadata.get("sha256_scope") != "decompressed_json_payload":
        errors.append("execution timing source sha256 scope is missing or invalid")

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
        return errors + [
            f"missing full provenance source: {raw_path.name} or {archive_path.name}"
        ]

    source_payload: bytes | None = None
    integrity_errors: list[str] = []
    for name, payload in candidates:
        actual_sha = hashlib.sha256(payload).hexdigest()
        if actual_sha != expected_sha:
            integrity_errors.append(
                f"{name} sha256 mismatch: {actual_sha} != {expected_sha}"
            )
        elif source_payload is None:
            source_payload = payload
    if integrity_errors:
        return errors + integrity_errors
    if source_payload is None:
        return ["full provenance source has no matching payload"]
    try:
        source = json.loads(source_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"full provenance source is not valid JSON: {exc}"]
    if not isinstance(source, dict):
        return ["full provenance source must be a JSON object"]
    errors.extend(_baseline_config_authorization_errors(root, source))
    return errors


def _execution_open_quality_errors(root: Path) -> list[str]:
    timing_path = (
        Path(root)
        / "building"
        / "reports"
        / "current_baseline"
        / "execution_timing"
        / "EXECUTION_TIMING_SENSITIVITY.json"
    )
    if not timing_path.exists():
        return [f"missing execution timing evidence: {timing_path}"]
    try:
        timing = json.loads(timing_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"execution timing evidence unreadable: {exc}"]
    quality = timing.get("open_quality")
    if not isinstance(quality, dict):
        return ["open_quality evidence is missing or invalid"]

    fields = (
        "required_missing_rows",
        "required_modeled_rows",
        "required_total_rows",
    )
    values: dict[str, int] = {}
    for field in fields:
        value = quality.get(field)
        if type(value) is not int or value < 0:
            return [f"open_quality.{field} is missing or invalid"]
        values[field] = value
    if values["required_total_rows"] <= 0:
        return ["open_quality.required_total_rows is missing or invalid"]
    if values["required_missing_rows"] > 0:
        return [
            "required_missing_rows must be 0, "
            f"got {values['required_missing_rows']}"
        ]
    modeled_share = values["required_modeled_rows"] / values["required_total_rows"]
    if modeled_share > MAX_REQUIRED_MODELED_OPEN_SHARE:
        return [
            f"required modeled share {modeled_share:.4%} exceeds "
            f"{MAX_REQUIRED_MODELED_OPEN_SHARE:.2%} policy ceiling"
        ]
    return []


def _baseline_config_authorization_errors(
    root: Path,
    source: dict[str, Any],
) -> list[str]:
    authorization = source.get("config_authorization")
    if not isinstance(authorization, dict) or authorization.get("schema_version") != (
        "current-baseline-config-authorization-v1"
    ):
        return ["config authorization is missing or invalid"]

    artifact_dir = Path(root) / "building" / "reports" / "current_baseline"
    config_path = artifact_dir / "CURRENT_BASELINE_CONFIG.json"
    policy_path = (
        Path(root)
        / "src"
        / "hermes_escape_top"
        / "governance"
        / "approved_live_config.json"
    )
    try:
        normalized_config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"normalized baseline config unreadable: {exc}"]
    try:
        policy_bytes = policy_path.read_bytes()
        policy = json.loads(policy_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"approved live config policy unreadable: {exc}"]
    if not isinstance(normalized_config, dict) or not isinstance(policy, dict):
        return ["normalized baseline config and policy must be JSON objects"]

    errors: list[str] = []
    policy_sha = hashlib.sha256(policy_bytes).hexdigest()
    if authorization.get("policy_sha256") != policy_sha:
        errors.append("config authorization policy sha256 mismatch")
    if authorization.get("policy_schema_version") != policy.get("schema_version"):
        errors.append("config authorization policy schema mismatch")

    expected_live = str(policy.get("live_config_semantic_sha256") or "")
    expected_repo = str(policy.get("repo_config_semantic_sha256") or "")
    if authorization.get("raw_live_config_semantic_sha256") != expected_live:
        errors.append("config authorization live semantic sha256 differs from policy")
    if authorization.get("repo_config_semantic_sha256") != expected_repo:
        errors.append("config authorization repo semantic sha256 differs from policy")
    if authorization.get("policy_approved_live_semantic_sha256") != expected_live:
        errors.append("config authorization recorded approved live sha256 differs from policy")
    if authorization.get("policy_approved_repo_semantic_sha256") != expected_repo:
        errors.append("config authorization recorded approved repo sha256 differs from policy")
    if authorization.get("approved_feature_diff") != policy.get("approved_feature_diff"):
        errors.append("config authorization feature diff differs from policy")

    normalized_sha = _semantic_sha256(normalized_config)
    if authorization.get("normalized_config_semantic_sha256") != normalized_sha:
        errors.append("normalized config semantic sha256 mismatch")
    raw_file_sha = str(authorization.get("raw_live_config_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", raw_file_sha):
        errors.append("raw live config file sha256 is missing or invalid")

    normalization = authorization.get("normalization")
    if not isinstance(normalization, dict):
        errors.append("config authorization normalization map is missing or invalid")
        return errors
    raw_candidate = json.loads(json.dumps(normalized_config))
    features = raw_candidate.get("features")
    if not isinstance(features, dict):
        errors.append("normalized baseline config features must be an object")
        return errors
    for key, row in normalization.items():
        if not isinstance(key, str) or not isinstance(row, dict):
            errors.append("config authorization normalization rows must be objects")
            continue
        if set(row) != {"raw", "normalized", "reason"}:
            errors.append(f"config authorization normalization row invalid: {key}")
            continue
        normalized_value = row["normalized"]
        observed_value = features.get(key, "<missing>")
        if observed_value != normalized_value:
            errors.append(f"normalized config value differs from authorization: {key}")
            continue
        raw_value = row["raw"]
        if raw_value == "<missing>":
            features.pop(key, None)
        else:
            features[key] = raw_value
    if _semantic_sha256(raw_candidate) != str(
        authorization.get("raw_live_config_semantic_sha256") or ""
    ):
        errors.append("normalized config cannot reconstruct approved raw live config")
    return errors


def _semantic_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
