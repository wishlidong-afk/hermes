#!/usr/bin/env python3
"""Read-only acceptance check for the Hermes scheduled morning run."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


LOCAL_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_DASHBOARD_URL = "http://127.0.0.1:8766/api/health_status"
EXPECTED_ARTIFACTS = frozenset(
    {
        "audit_log.jsonl",
        "flow_reference.sqlite",
        "hermes_state.sqlite",
        "mirror_reference.sqlite",
        "reentry_state.sqlite",
        "signal_journal.jsonl",
    }
)


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        f"# Hermes Morning Acceptance - {report.get('acceptance_date')}",
        "",
        f"- status: `{report.get('status')}`",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- summary: {report.get('summary')}",
        "",
        "| Check | Status | Detail | Evidence |",
        "|---|---|---|---|",
    ]
    for row in report.get("checks") or []:
        lines.append(
            "| {id} | {status} | {detail} | {evidence} |".format(
                id=_markdown_cell(row.get("id")),
                status=_markdown_cell(row.get("status")),
                detail=_markdown_cell(row.get("detail")),
                evidence=_markdown_cell(row.get("evidence")),
            )
        )
    observations = report.get("operational_observations") or {}
    if observations:
        lines.extend(
            [
                "",
                "## Operational Observations",
                "",
                "| Observation | Status | Detail | Evidence |",
                "|---|---|---|---|",
            ]
        )
        for name, row in observations.items():
            lines.append(
                "| {name} | {status} | {detail} | {evidence} |".format(
                    name=_markdown_cell(name),
                    status=_markdown_cell((row or {}).get("status")),
                    detail=_markdown_cell((row or {}).get("detail")),
                    evidence=_markdown_cell((row or {}).get("evidence")),
                )
            )
    lines.extend(
        [
            "",
            "This verifier is read-only for Hermes strategy data. It does not run daily,",
            "refresh market data, or connect to IBKR.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(report: Mapping[str, Any], output_dir: Path) -> Dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    day = str(report.get("acceptance_date") or "unknown")[:10]
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    markdown = render_markdown(report)
    paths = {
        "dated_json": output / f"morning_acceptance_{day}.json",
        "dated_markdown": output / f"morning_acceptance_{day}.md",
        "latest_json": output / "morning_acceptance_latest.json",
        "latest_markdown": output / "morning_acceptance_latest.md",
    }
    _atomic_write_text(paths["dated_json"], payload)
    _atomic_write_text(paths["dated_markdown"], markdown)
    _atomic_write_text(paths["latest_json"], payload)
    _atomic_write_text(paths["latest_markdown"], markdown)
    return paths


def collect_acceptance(
    *,
    home: Optional[Path] = None,
    now: Optional[datetime] = None,
    dashboard_reader: Optional[Callable[[str], Tuple[int, Mapping[str, Any]]]] = None,
    dashboard_url: str = DEFAULT_DASHBOARD_URL,
) -> Dict[str, Any]:
    """Collect one morning acceptance report without mutating live state."""
    root = Path(home or Path.home())
    observed_at = _local_datetime(now or datetime.now(LOCAL_TZ))
    acceptance_date = observed_at.date()
    base = root / ".hermes/skills/investment/escape-top"
    archive = base / "current/hermes_escape_top/data/archive"
    checks = []

    release_check, release = _collect_release(base)
    checks.append(release_check)

    receipt_check, receipt = _collect_receipt(archive, acceptance_date)
    checks.append(receipt_check)

    audit_check, audit = _collect_audit(archive, receipt, acceptance_date)
    checks.append(audit_check)

    transaction_check = _collect_transaction(archive, audit)
    checks.append(transaction_check)

    health_check, health_warnings = _collect_bound_health(
        base, audit, receipt, acceptance_date
    )
    checks.append(health_check)

    reader = dashboard_reader or _read_dashboard
    dashboard_check, dashboard_warnings = _collect_dashboard(
        reader, dashboard_url, audit
    )
    checks.append(dashboard_check)

    watchdog_check = _collect_watchdog(root, acceptance_date)
    checks.append(watchdog_check)

    operational_observations, operational_warnings = _collect_operational_observations(
        root,
        base,
        archive,
        observed_at,
    )

    failures = [row for row in checks if row["status"] == "FAIL"]
    warning_details = _unique(
        health_warnings + dashboard_warnings + operational_warnings
    )
    status = "FAIL" if failures else "PASS"
    if failures:
        summary = "FAIL: " + ", ".join(row["id"] for row in failures)
    elif warning_details:
        summary = "PASS; allowed warnings: " + "; ".join(warning_details)
    else:
        summary = "PASS; no warnings"
    return {
        "schema_version": "hermes-morning-acceptance-v1",
        "generated_at": observed_at.isoformat(timespec="seconds"),
        "acceptance_date": acceptance_date.isoformat(),
        "status": status,
        "summary": summary,
        "release": release,
        "scheduled": {
            "as_of": audit.get("as_of") or receipt.get("as_of"),
            "input_hash": audit.get("input_hash"),
            "run_ts": audit.get("run_ts"),
        },
        "checks": checks,
        "operational_observations": operational_observations,
    }


def _collect_release(base: Path) -> Tuple[Dict[str, str], Dict[str, str]]:
    current = base / "current"
    try:
        if not current.is_symlink():
            raise ValueError(f"current is not a symlink: {current}")
        raw_target = Path(os.readlink(current))
        if raw_target.is_absolute() or len(raw_target.parts) != 2 or raw_target.parts[0] != "releases":
            raise ValueError(f"current target is not a relative R6 release: {raw_target}")
        release_name = raw_target.name
        expected_hash = release_name.split("_", 1)[0]
        version_path = current / "hermes_escape_top/VERSION"
        fields = version_path.read_text(encoding="utf-8").splitlines()[0].split()
        if len(fields) < 2:
            raise ValueError(f"invalid VERSION: {version_path}")
        version_hash, version_stamp = fields[0], fields[1]
        if version_hash != expected_hash:
            raise ValueError(
                f"VERSION hash {version_hash} does not match release {expected_hash}"
            )
        attestation_path = current / "hermes_escape_top/LIVE_CONFIG_ATTESTATION.json"
        attestation = _read_json(attestation_path)
        policy_path = current / "hermes_escape_top/governance/approved_live_config.json"
        policy_bound = policy_path.is_file()
        expected_schema = (
            "hermes-live-config-attestation-v2"
            if policy_bound
            else "hermes-live-config-attestation-v1"
        )
        if attestation.get("schema_version") != expected_schema:
            raise ValueError(
                f"invalid live config attestation for "
                f"{'policy-bound' if policy_bound else 'legacy'} release: {attestation_path}"
            )
        if str(attestation.get("release_id") or "") != release_name:
            raise ValueError(
                f"attestation release {attestation.get('release_id')} does not match {release_name}"
            )
        if str(attestation.get("release_hash") or "") != version_hash:
            raise ValueError(
                f"attestation hash {attestation.get('release_hash')} does not match {version_hash}"
            )
        config_path = current / "hermes_escape_top/config/config.json"
        if policy_bound:
            validator_path = current / "hermes_escape_top/governance/live_config_policy.py"
            validator_spec = importlib.util.spec_from_file_location(
                f"hermes_live_config_policy_{release_name}",
                validator_path,
            )
            if validator_spec is None or validator_spec.loader is None:
                raise ValueError(f"live config policy validator missing: {validator_path}")
            validator = importlib.util.module_from_spec(validator_spec)
            validator_spec.loader.exec_module(validator)
            live_config = _read_json(config_path)
            policy = validator.load_policy(policy_path)
            validator.validate_attestation(
                live_config,
                policy,
                attestation,
                policy_path=policy_path,
            )
        observed_config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()
        attested_config_hash = str(attestation.get("live_config_sha256") or "")
        if observed_config_hash != attested_config_hash:
            raise ValueError(
                "live config sha256 mismatch "
                f"observed={observed_config_hash} attested={attested_config_hash}"
            )
        feature_diff = attestation.get("feature_diff")
        if not isinstance(feature_diff, dict):
            raise ValueError("live config attestation feature_diff is not an object")
        policy_detail = (
            str(attestation.get("policy_sha256") or "")[:12]
            if policy_bound
            else "LEGACY_UNBOUND"
        )
        detail = (
            f"{release_name} VERSION={version_hash} {version_stamp} "
            f"config={observed_config_hash[:12]} feature_diff={len(feature_diff)} "
            f"policy={policy_detail}"
        )
        return _check("release_identity", "PASS", detail, attestation_path), {
            "name": release_name,
            "hash": version_hash,
            "stamp": version_stamp,
            "live_config_sha256": observed_config_hash,
            "feature_diff_count": str(len(feature_diff)),
            "policy_bound": str(policy_bound).lower(),
        }
    except Exception as exc:
        return _check("release_identity", "FAIL", str(exc), current), {}


def _collect_receipt(
    archive: Path, acceptance_date: date
) -> Tuple[Dict[str, str], Dict[str, Any]]:
    path = archive / "run_receipt.json"
    try:
        receipt = _read_json(path)
        finished_at = _parse_timestamp(receipt.get("finished_at") or receipt.get("run_at"))
        failures = []
        if str(receipt.get("status") or "") != "OK":
            failures.append(f"status={receipt.get('status')}")
        if receipt.get("ok") is not True:
            failures.append(f"ok={receipt.get('ok')}")
        if str(receipt.get("run_type") or "") != "scheduled":
            failures.append(f"run_type={receipt.get('run_type')}")
        if finished_at is None or _local_datetime(finished_at).date() != acceptance_date:
            failures.append(f"finished_at={receipt.get('finished_at') or receipt.get('run_at')}")
        if failures:
            raise ValueError("; ".join(failures))
        detail = f"OK as_of={receipt.get('as_of')} finished_at={finished_at.isoformat()}"
        return _check("scheduled_receipt", "PASS", detail, path), receipt
    except Exception as exc:
        return _check("scheduled_receipt", "FAIL", str(exc), path), {}


def _collect_audit(
    archive: Path, receipt: Mapping[str, Any], acceptance_date: date
) -> Tuple[Dict[str, str], Dict[str, Any]]:
    path = archive / "audit_log.jsonl"
    try:
        scheduled = list(_scheduled_rows_for_date(path, acceptance_date))
        if len(scheduled) != 1:
            raise ValueError(f"scheduled runs on {acceptance_date}: {len(scheduled)} (expected 1)")
        payload = scheduled[0]
        failures = []
        if not payload.get("input_hash"):
            failures.append("input_hash missing")
        if receipt.get("as_of") and str(payload.get("as_of")) != str(receipt.get("as_of")):
            failures.append(
                f"as_of={payload.get('as_of')} receipt_as_of={receipt.get('as_of')}"
            )
        if failures:
            raise ValueError("; ".join(failures))
        detail = (
            f"count=1 as_of={payload.get('as_of')} "
            f"input_hash={str(payload.get('input_hash'))[:16]}"
        )
        return _check("scheduled_audit", "PASS", detail, path), payload
    except Exception as exc:
        return _check("scheduled_audit", "FAIL", str(exc), path), {}


def _collect_transaction(archive: Path, audit: Mapping[str, Any]) -> Dict[str, str]:
    root = archive / ".score_run_transactions"
    try:
        persistence = audit.get("persistence")
        if not isinstance(persistence, Mapping):
            raise ValueError("audit persistence evidence missing")
        protocol = str(persistence.get("protocol") or "")
        run_id = str(persistence.get("run_id") or "")
        if protocol != "recoverable-journal-v1" or not run_id:
            raise ValueError(f"protocol={protocol or 'missing'} run_id={run_id or 'missing'}")
        active = root / "active.json"
        if active.exists():
            raise ValueError(f"residual active transaction: {active}")
        manifest_path = root / "runs" / run_id / "manifest.json"
        manifest = _read_json(manifest_path)
        if str(manifest.get("run_id") or "") != run_id:
            raise ValueError(
                f"manifest run_id={manifest.get('run_id')} audit_run_id={run_id}"
            )
        status = str(manifest.get("status") or "")
        if status != "COMMITTED":
            raise ValueError(f"transaction {run_id} status={status or 'missing'}")
        metadata = manifest.get("metadata") or {}
        expected_metadata = {
            "as_of": str(audit.get("as_of") or "")[:10],
            "run_type": "scheduled",
            "shadow": False,
        }
        observed_metadata = {key: metadata.get(key) for key in expected_metadata}
        if observed_metadata != expected_metadata:
            raise ValueError(
                f"metadata mismatch observed={observed_metadata} expected={expected_metadata}"
            )
        artifact_rows = [
            str(row.get("path") or "")
            for row in manifest.get("artifacts") or []
            if isinstance(row, Mapping)
        ]
        expected_paths = {f"archive/{name}" for name in EXPECTED_ARTIFACTS}
        artifacts = set(artifact_rows)
        if artifacts != expected_paths or len(artifact_rows) != len(expected_paths):
            missing = sorted(expected_paths - artifacts)
            extra = sorted(artifacts - expected_paths)
            raise ValueError(f"business artifacts mismatch missing={missing} extra={extra}")
        return _check(
            "persistence_transaction",
            "PASS",
            f"run_id={run_id} status=COMMITTED artifacts=6 active=absent",
            manifest_path,
        )
    except Exception as exc:
        return _check("persistence_transaction", "FAIL", str(exc), root)


def _collect_bound_health(
    base: Path,
    audit: Mapping[str, Any],
    receipt: Mapping[str, Any],
    acceptance_date: date,
) -> Tuple[Dict[str, str], list[str]]:
    as_of = str(audit.get("as_of") or receipt.get("as_of") or "")[:10]
    report_root = base / "current/reports"
    compatibility = report_root / f"system_health_{as_of}.json"
    immutable = sorted(
        (report_root / "system_health_runs").glob(f"system_health_{as_of}_*.json")
    )
    candidate_paths = immutable + ([compatibility] if compatibility.exists() else [])
    path = compatibility
    try:
        reports = []
        for candidate in candidate_paths:
            try:
                reports.append((candidate, _read_json(candidate)))
            except Exception:
                continue
        expected_hash = str(audit.get("input_hash") or "")
        matching = [
            item
            for item in reports
            if str(item[1].get("input_hash") or "") == expected_hash
        ]
        if matching:
            path, report = max(
                matching,
                key=lambda item: str(item[1].get("generated_at") or ""),
            )
        elif reports:
            path, report = reports[-1]
        else:
            raise FileNotFoundError(f"no system health report candidates for {as_of}")
        generated_at = _parse_timestamp(report.get("generated_at"))
        failures = []
        if generated_at is None or _local_datetime(generated_at).date() != acceptance_date:
            failures.append(f"generated_at={report.get('generated_at')}")
        if str(report.get("as_of") or "") != as_of:
            failures.append(f"report_as_of={report.get('as_of')} audit_as_of={as_of}")
        if str(report.get("run_type") or "") != "scheduled":
            failures.append(f"run_type={report.get('run_type')}")
        if str(report.get("input_hash") or "") != str(audit.get("input_hash") or ""):
            failures.append("input_hash does not match scheduled audit")
        report_receipt = report.get("run_receipt") or {}
        if str(report_receipt.get("status") or "") != "OK" or report_receipt.get("ok") is not True:
            failures.append("embedded scheduled receipt is not OK")
        if str(report_receipt.get("run_type") or "") != "scheduled":
            failures.append(
                f"embedded receipt run_type={report_receipt.get('run_type')}"
            )
        expected_finished = str(receipt.get("finished_at") or receipt.get("run_at") or "")
        observed_finished = str(
            report_receipt.get("finished_at") or report_receipt.get("run_at") or ""
        )
        if expected_finished and observed_finished != expected_finished:
            failures.append(
                f"embedded receipt finished_at={observed_finished} expected={expected_finished}"
            )
        health_failures, warnings = _health_policy(report.get("health") or {})
        failures.extend(health_failures)
        if failures:
            raise ValueError("; ".join(failures))
        status = "WARN" if warnings else "PASS"
        detail = "; ".join(warnings) if warnings else "hash-bound health report is OK"
        return _check("bound_health_report", status, detail, path), warnings
    except Exception as exc:
        return _check("bound_health_report", "FAIL", str(exc), path), []


def _collect_dashboard(
    reader: Callable[[str], Tuple[int, Mapping[str, Any]]],
    url: str,
    audit: Mapping[str, Any],
) -> Tuple[Dict[str, str], list[str]]:
    try:
        status_code, payload = reader(url)
        failures = []
        if status_code != 200:
            failures.append(f"HTTP {status_code}")
        if str(payload.get("as_of") or "") != str(audit.get("as_of") or ""):
            failures.append(
                f"as_of={payload.get('as_of')} audit_as_of={audit.get('as_of')}"
            )
        if str(payload.get("receipt_status") or "") != "OK":
            failures.append(f"receipt_status={payload.get('receipt_status')}")
        health_failures, warnings = _health_policy(payload)
        failures.extend(health_failures)
        if failures:
            raise ValueError("; ".join(failures))
        status = "WARN" if warnings else "PASS"
        detail = f"HTTP 200; {'; '.join(warnings) if warnings else 'health OK'}"
        return _check("dashboard_health", status, detail, url), warnings
    except Exception as exc:
        return _check("dashboard_health", "FAIL", str(exc), url), []


def _collect_watchdog(root: Path, acceptance_date: date) -> Dict[str, str]:
    path = root / ".hermes/logs/watchdog.log"
    try:
        rows = []
        with path.open(encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                line = raw.strip()
                if len(line) < 20:
                    continue
                try:
                    timestamp = datetime.fromisoformat(line[:19]).replace(tzinfo=LOCAL_TZ)
                except ValueError:
                    continue
                if timestamp.date() != acceptance_date:
                    continue
                if time(8, 55) <= timestamp.time() <= time(9, 15):
                    rows.append((timestamp, line[20:].strip()))
        if not rows:
            raise ValueError(f"no watchdog entry in 08:55-09:15 on {acceptance_date}")
        alerts = [message for _, message in rows if message.startswith("ALERT")]
        if alerts:
            raise ValueError("; ".join(alerts))
        latest_at, latest = max(rows, key=lambda row: row[0])
        if not latest.startswith("ok "):
            raise ValueError(f"unexpected watchdog status: {latest}")
        return _check(
            "watchdog",
            "PASS",
            f"{latest_at.isoformat(timespec='seconds')} {latest}",
            path,
        )
    except Exception as exc:
        return _check("watchdog", "FAIL", str(exc), path)


def _collect_operational_observations(
    root: Path,
    base: Path,
    archive: Path,
    observed_at: datetime,
) -> Tuple[Dict[str, Dict[str, Any]], list[str]]:
    attestation_path = base / "current/hermes_escape_top/LIVE_CONFIG_ATTESTATION.json"
    try:
        attestation = _read_json(attestation_path)
    except Exception:
        attestation = {}
    retention = _retention_observation(root, attestation, observed_at)
    market_admission = _market_admission_observation(
        archive,
        attestation,
    )
    warnings = []
    if retention["status"] == "WARN":
        warnings.append(f"runtime retention: {retention['detail']}")
    if market_admission["status"] == "WARN":
        warnings.append(f"market admission: {market_admission['detail']}")
    return {
        "runtime_retention": retention,
        "market_admission": market_admission,
    }, warnings


def _retention_observation(
    root: Path,
    attestation: Mapping[str, Any],
    observed_at: datetime,
) -> Dict[str, Any]:
    path = root / ".hermes/logs/retention/runtime_retention_latest.json"
    expected_at = _parse_timestamp(attestation.get("retention_first_expected_at"))
    observed = _local_datetime(observed_at)
    if not path.exists():
        if expected_at is not None and observed < _local_datetime(expected_at):
            return {
                "status": "PENDING",
                "detail": f"first APPLY evidence expected after {_local_datetime(expected_at).isoformat(timespec='minutes')}",
                "evidence": str(path),
            }
        return {
            "status": "WARN",
            "detail": "retention APPLY evidence missing after its first expected window",
            "evidence": str(path),
        }
    try:
        report = _read_json(path)
        generated_at = _parse_timestamp(report.get("generated_at"))
        if generated_at is None:
            raise ValueError("generated_at missing or invalid")
        age = observed - _local_datetime(generated_at)
        report_status = str(report.get("status") or "")
        result_mode = str((report.get("result") or {}).get("mode") or "")
        if report_status != "PASS" or result_mode != "APPLIED":
            return {
                "status": "WARN",
                "detail": f"retention result status={report_status or 'MISSING'} mode={result_mode or 'MISSING'}",
                "evidence": str(path),
            }
        if age > timedelta(days=8):
            return {
                "status": "WARN",
                "detail": f"retention APPLY evidence is older than 8 days: age={age.total_seconds() / 86400:.1f}d",
                "evidence": str(path),
            }
        deleted = int((report.get("result") or {}).get("deleted_count") or 0)
        return {
            "status": "PASS",
            "detail": f"latest APPLY passed age={age.total_seconds() / 86400:.1f}d deleted={deleted}",
            "evidence": str(path),
        }
    except Exception as exc:
        return {
            "status": "WARN",
            "detail": f"retention evidence unreadable: {exc}",
            "evidence": str(path),
        }


def _market_admission_observation(
    archive: Path,
    attestation: Mapping[str, Any],
) -> Dict[str, Any]:
    enabled = set(attestation.get("live_enabled_features") or [])
    diff = attestation.get("feature_diff") or {}
    market_diff = diff.get("use_market_admission_gate") if isinstance(diff, dict) else None
    gate_enabled = (
        "use_market_admission_gate" in enabled
        or bool((market_diff or {}).get("live"))
    )
    paths = sorted(Path(archive).glob("market_admission_????-??-??.json"))
    if not gate_enabled:
        return {
            "status": "NOT_APPLICABLE",
            "detail": "use_market_admission_gate is not enabled in live attestation",
            "evidence": str(archive),
            "consecutive_ok": 0,
            "mature": False,
        }
    rows = []
    for path in paths:
        try:
            rows.append((path, _read_json(path)))
        except Exception as exc:
            rows.append((path, {"status": "ERROR", "error": str(exc)}))
    if not rows:
        return {
            "status": "WARN",
            "detail": "no dated market-admission evidence",
            "evidence": str(archive),
            "consecutive_ok": 0,
            "mature": False,
        }
    consecutive = 0
    completed_dates: set[str] = set()
    previous_run_day: Optional[date] = None
    for path, row in reversed(rows):
        try:
            run_day = date.fromisoformat(path.stem.rsplit("_", 1)[-1])
        except ValueError:
            break
        if previous_run_day is not None and run_day != previous_run_day - timedelta(days=1):
            break
        completed = str(row.get("completed_through") or "")[:10]
        if str(row.get("status") or "") != "OK" or not completed:
            break
        previous_run_day = run_day
        if completed in completed_dates:
            continue
        completed_dates.add(completed)
        consecutive += 1
    latest_path, latest = rows[-1]
    latest_status = str(latest.get("status") or "MISSING")
    if latest_status != "OK":
        status = "WARN"
        detail = f"latest market-admission status={latest_status}"
    elif consecutive < 3:
        status = "OBSERVING"
        detail = f"consecutive OK evidence {consecutive}/3 minimum; 5-day target"
    else:
        status = "PASS"
        detail = f"consecutive OK evidence {consecutive}; 3-day minimum met, 5-day target"
    return {
        "status": status,
        "detail": detail,
        "evidence": str(latest_path),
        "consecutive_ok": consecutive,
        "mature": consecutive >= 3,
        "target_days": 5,
        "latest_completed_through": str(latest.get("completed_through") or "")[:10],
    }


def _health_policy(health: Mapping[str, Any]) -> Tuple[list[str], list[str]]:
    layers = health.get("layers") or {}
    failures = []
    warnings = []

    strategy = layers.get("strategy_data") or {}
    for row in strategy.get("checks") or []:
        level = str(row.get("level") or "")
        detail = str(row.get("detail") or "")
        label = str(row.get("label") or "")
        allowed_dollar = _is_dollar_only_strategy_warning(level, label, detail)
        if allowed_dollar:
            warnings.append("dollar stale (expected policy WARN)")
        elif level in {"DEGRADED", "CRITICAL"}:
            failures.append(f"strategy health: {label} {detail}".strip())
    strategy_level = str(strategy.get("level") or "OK")
    if strategy_level not in {"OK", "DEGRADED"}:
        failures.append(f"strategy layer={strategy_level}")
    if strategy_level == "DEGRADED" and not any("dollar stale" in item for item in warnings):
        failures.append("strategy layer DEGRADED without permitted dollar warning")

    positions = layers.get("position_reconciliation") or {}
    for row in positions.get("checks") or []:
        level = str(row.get("level") or "")
        label = str(row.get("label") or "")
        detail = str(row.get("detail") or "")
        if level == "INFO" and "IBKR" in label.upper():
            warnings.append("IBKR stale/unavailable (nonblocking INFO)")
        elif level in {"DEGRADED", "CRITICAL"}:
            failures.append(f"position health: {label} {detail}".strip())
    if str(positions.get("level") or "OK") not in {"OK", "INFO"}:
        failures.append(f"position layer={positions.get('level')}")

    auxiliary = layers.get("auxiliary_flows") or {}
    auxiliary_level = str(auxiliary.get("level") or "OK")
    if auxiliary_level != "OK":
        failures.append(f"auxiliary flow layer={auxiliary_level}")
    for row in auxiliary.get("checks") or []:
        if str(row.get("level") or "") in {"DEGRADED", "CRITICAL"}:
            failures.append(
                f"auxiliary health: {row.get('label')} {row.get('detail') or ''}".strip()
            )
    return _unique(failures), _unique(warnings)


def _is_dollar_only_strategy_warning(level: str, label: str, detail: str) -> bool:
    if level != "DEGRADED":
        return False
    normalized_label = label.strip().lower()
    normalized_detail = detail.strip().lower()
    if normalized_detail == "dollar":
        return "soft" in normalized_label or "\u8f6f\u6570\u636e\u6e90\u8fc7\u671f" in label
    if normalized_label == "\u5916\u90e8\u6570\u636e\u6e90\u9648\u65e7":
        source_id, separator, _ = normalized_detail.partition(":")
        return bool(separator) and source_id.strip() == "dollar"
    return False


def _scheduled_rows_for_date(path: Path, target: date) -> Iterable[Dict[str, Any]]:
    with path.open(encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            try:
                row = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(row, dict):
                continue
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else row
            if str(payload.get("run_type") or "") != "scheduled":
                continue
            run_ts = _parse_timestamp(payload.get("run_ts"))
            if run_ts is not None and _local_datetime(run_ts).date() == target:
                yield dict(payload)


def _read_dashboard(url: str) -> Tuple[int, Mapping[str, Any]]:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("dashboard health response is not a JSON object")
        return int(response.status), payload


def _read_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        raise


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    return parsed


def _local_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(LOCAL_TZ)


def _check(
    check_id: str, status: str, detail: str, evidence: Any
) -> Dict[str, str]:
    return {
        "id": check_id,
        "status": status,
        "detail": str(detail),
        "evidence": str(evidence),
    }


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))


def _markdown_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--dashboard-url", default=DEFAULT_DASHBOARD_URL)
    parser.add_argument("--now", help="Fixed ISO timestamp for deterministic verification")
    args = parser.parse_args(argv)
    observed_at = _parse_timestamp(args.now) if args.now else datetime.now(LOCAL_TZ)
    if observed_at is None:
        parser.error("--now must be an ISO timestamp")
    report = collect_acceptance(
        home=args.home,
        now=observed_at,
        dashboard_url=args.dashboard_url,
    )
    output_dir = args.output_dir or args.home / ".hermes/logs/acceptance"
    paths = write_reports(report, output_dir)
    print(
        json.dumps(
            {
                "status": report["status"],
                "summary": report["summary"],
                "json": str(paths["dated_json"]),
                "markdown": str(paths["dated_markdown"]),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
