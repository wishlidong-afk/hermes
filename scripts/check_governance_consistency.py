#!/usr/bin/env python3
"""Fail when config, flag registry, context snapshot, or baseline metadata drift."""
from __future__ import annotations

import argparse
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
    dollar_slo, _ = dollar_slo_alignment(config)
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
        "dollar_slo_max_age_days": dollar_slo,
        "baseline": {
            "git_commit": baseline.get("git_commit"),
            "equity_timing": baseline.get("equity_timing"),
            "effective_end": baseline.get("effective_end"),
        },
    }


def dollar_slo_alignment(config: dict[str, Any]) -> tuple[dict[str, int], list[str]]:
    from hermes_escape_top.core.data.external_sources.profiles import profile_for
    from hermes_escape_top.core.data.risk_signals import _all_risk_sources

    profile = profile_for("dollar")
    risk_source = next(
        (source for source in _all_risk_sources() if getattr(source, "name", "") == "dollar"),
        None,
    )
    values = {
        "config": int(((config.get("soft_data_slo") or {}).get("max_age_days") or {}).get("dollar", -1)),
        "external_profile": int(profile.max_age_days) if profile is not None else -1,
        "risk_source": int(risk_source.max_age_days) if risk_source is not None else -1,
    }
    if set(values.values()) == {14}:
        return values, []
    detail = ", ".join(f"{key}={value}" for key, value in values.items())
    return values, [f"dollar max-age mismatch: {detail}"]


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

    _, dollar_slo_errors = dollar_slo_alignment(config)
    if dollar_slo_errors:
        checks["dollar_slo_alignment"] = "ERROR"
        errors.extend(dollar_slo_errors)
    else:
        checks["dollar_slo_alignment"] = "OK"

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
    if baseline_errors:
        checks["baseline_metadata"] = "ERROR"
        errors.extend(f"baseline: {message}" for message in baseline_errors)
    else:
        checks["baseline_metadata"] = "OK"

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
        for expected in expected_text:
            if expected not in text:
                errors.append(f"{path.name} missing {expected}")
    return errors


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
