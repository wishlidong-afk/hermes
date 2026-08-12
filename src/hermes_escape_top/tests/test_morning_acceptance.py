from __future__ import annotations

import importlib.util
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
EXPECTED_ARTIFACTS = (
    "audit_log.jsonl",
    "flow_reference.sqlite",
    "hermes_state.sqlite",
    "mirror_reference.sqlite",
    "reentry_state.sqlite",
    "signal_journal.jsonl",
    "soft_adapter_snapshot_2026-07-10.json",
)


def _semantic_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_module():
    path = REPO_ROOT / "ops" / "morning_acceptance.py"
    spec = importlib.util.spec_from_file_location("hermes_morning_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")


def _acceptance_fixture(tmp_path: Path) -> tuple[Path, datetime, dict]:
    home = tmp_path / "home"
    base = home / ".hermes/skills/investment/escape-top"
    release_name = "d9ec486_20260712_184620"
    release = base / "releases" / release_name
    package = release / "hermes_escape_top"
    archive = base / "shared/hermes_escape_top/data/archive"
    shared_config = base / "shared/hermes_escape_top/config/config.json"
    reports = base / "reports"
    package.mkdir(parents=True)
    archive.mkdir(parents=True)
    reports.mkdir(parents=True)
    (package / "VERSION").write_text("d9ec486 20260712_184620\n", encoding="utf-8")
    repo_config = {
        "features": {"use_market_admission_gate": False},
        "ibkr": {"readonly": True},
    }
    live_config = {
        "features": {"use_market_admission_gate": True},
        "ibkr": {"readonly": True},
    }
    _write_json(shared_config, live_config)
    policy_path = package / "governance/approved_live_config.json"
    policy_validator = (
        REPO_ROOT / "src/hermes_escape_top/governance/live_config_policy.py"
    )
    validator_target = package / "governance/live_config_policy.py"
    validator_target.parent.mkdir(parents=True, exist_ok=True)
    validator_target.write_bytes(policy_validator.read_bytes())
    _write_json(
        policy_path,
        {
            "schema_version": "hermes-approved-live-config-v1",
            "repo_config_semantic_sha256": _semantic_sha256(repo_config),
            "live_config_semantic_sha256": _semantic_sha256(live_config),
            "approved_feature_diff": {
                "use_market_admission_gate": {"repo": False, "live": True}
            },
            "required_values": {"ibkr.readonly": True},
        },
    )
    (package / "data").symlink_to(base / "shared/hermes_escape_top/data", target_is_directory=True)
    (package / "config").symlink_to(base / "shared/hermes_escape_top/config", target_is_directory=True)
    _write_json(
        package / "LIVE_CONFIG_ATTESTATION.json",
        {
            "schema_version": "hermes-live-config-attestation-v2",
            "generated_at": "2026-07-12T18:46:20+08:00",
            "release_id": release_name,
            "release_hash": "d9ec486",
            "live_config_sha256": hashlib.sha256(shared_config.read_bytes()).hexdigest(),
            "repo_config_sha256": "repo-config-hash",
            "repo_config_semantic_sha256": _semantic_sha256(repo_config),
            "live_config_semantic_sha256": _semantic_sha256(live_config),
            "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
            "feature_diff": {"use_market_admission_gate": {"repo": False, "live": True}},
            "retention_policy_active_since": "2026-07-12T18:46:20+08:00",
            "retention_first_expected_at": "2026-07-19T08:35:00+08:00",
        },
    )
    (release / "reports").symlink_to(reports, target_is_directory=True)
    (base / "current").symlink_to(Path("releases") / release_name, target_is_directory=True)

    now = datetime(2026, 7, 13, 9, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
    receipt = {
        "status": "OK",
        "run_at": "2026-07-13T07:11:05+08:00",
        "started_at": "2026-07-13T07:10:01+08:00",
        "finished_at": "2026-07-13T07:11:05+08:00",
        "as_of": "2026-07-10",
        "run_type": "scheduled",
        "ok": True,
        "failed_step": "",
        "error": "",
    }
    _write_json(archive / "run_receipt.json", receipt)

    payload = {
        "as_of": "2026-07-10",
        "run_type": "scheduled",
        "run_ts": "2026-07-12T23:11:03+00:00",
        "input_hash": "input-hash-1",
        "persistence": {
            "protocol": "recoverable-journal-v1",
            "run_id": "run-1",
        },
    }
    audit_row = {
        "as_of": payload["as_of"],
        "input_hash": payload["input_hash"],
        "payload": payload,
    }
    (archive / "audit_log.jsonl").write_text(
        json.dumps(audit_row, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    _write_json(
        archive / ".score_run_transactions/runs/run-1/manifest.json",
        {
            "run_id": "run-1",
            "status": "COMMITTED",
            "started_at": "2026-07-12T23:10:30+00:00",
            "committed_at": "2026-07-12T23:11:03+00:00",
            "metadata": {
                "as_of": "2026-07-10",
                "run_type": "scheduled",
                "shadow": False,
            },
            "artifacts": [
                {"path": f"archive/{name}", "existed": True}
                for name in EXPECTED_ARTIFACTS
            ],
        },
    )

    health = {
        "level": "DEGRADED",
        "as_of": "2026-07-10",
        "receipt_status": "OK",
        "layers": {
            "strategy_data": {
                "level": "DEGRADED",
                "checks": [
                    {
                        "level": "DEGRADED",
                        "label": "软数据源过期 1",
                        "detail": "dollar",
                        "layer": "strategy_data",
                    }
                ],
            },
            "position_reconciliation": {
                "level": "INFO",
                "checks": [
                    {
                        "level": "INFO",
                        "label": "IBKR 快照陈旧",
                        "detail": "age=99999s max=900s",
                        "layer": "position_reconciliation",
                    }
                ],
            },
            "auxiliary_flows": {"level": "OK", "checks": []},
        },
    }
    _write_json(
        reports / "system_health_2026-07-10.json",
        {
            "schema_version": "hermes-system-health-v1",
            "generated_at": "2026-07-13T07:11:05+08:00",
            "generator_release_hash": "d9ec486",
            "generator_policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
            "as_of": "2026-07-10",
            "input_hash": "input-hash-1",
            "run_type": "scheduled",
            "run_receipt": receipt,
            "health": health,
        },
    )

    for run_day, completed_through in (
        ("2026-07-11", "2026-07-08"),
        ("2026-07-12", "2026-07-09"),
        ("2026-07-13", "2026-07-10"),
    ):
        _write_json(
            archive / f"market_admission_{run_day}.json",
            {
                "schema_version": "hermes-market-admission-v2",
                "generated_at": f"{run_day}T07:10:30+08:00",
                "status": "OK",
                "mode": "enforce_consensus",
                "completed_through": completed_through,
            },
        )

    watchdog = home / ".hermes/logs/watchdog.log"
    watchdog.parent.mkdir(parents=True, exist_ok=True)
    watchdog.write_text(
        "2026-07-13T09:00:05 ok as_of=2026-07-10 lag=0\n", encoding="utf-8"
    )
    _write_json(
        home / ".hermes/logs/external/external_precheck_latest.json",
        {
            "ready": True,
            "sources": {
                "aaii_sentiment": {
                    "status": "OK",
                    "freshness_status": "OK",
                    "evidence_status": "MATCH",
                    "latest_source_channel": "official_insights_rss",
                    "migration_status": "MONITORED",
                    "migration_readiness": "NOT_APPLICABLE",
                    "official_issue_as_of": "2026-07-11",
                    "official_file_sha256": "a" * 64,
                    "finished_at": "2026-07-13T06:45:05+08:00",
                },
                "naaim_exposure": {
                    "status": "OK",
                    "freshness_status": "OK",
                    "evidence_status": "MATCH",
                    "latest_source_channel": "naaim_public_workbook",
                    "migration_status": "MIGRATION_DUE",
                    "migration_readiness": "AUTOMATIC_PUBLIC",
                    "migration_deadline": "2026-08-01",
                    "official_issue_as_of": "2026-07-08",
                    "official_file_sha256": "b" * 64,
                    "finished_at": "2026-07-13T06:45:05+08:00",
                },
            },
        },
    )
    return home, now, health


def _switch_to_new_release(home: Path) -> tuple[Path, str]:
    base = home / ".hermes/skills/investment/escape-top"
    current = base / "current"
    old_release = current.resolve()
    old_package = old_release / "hermes_escape_top"
    release_name = "feed123_20260713_083000"
    release = base / "releases" / release_name
    package = release / "hermes_escape_top"
    package.mkdir(parents=True)
    (package / "VERSION").write_text("feed123 20260713_083000\n", encoding="utf-8")
    validator = package / "governance/live_config_policy.py"
    validator.parent.mkdir(parents=True, exist_ok=True)
    validator.write_bytes(
        (old_package / "governance/live_config_policy.py").read_bytes()
    )
    policy = package / "governance/approved_live_config.json"
    policy.write_bytes(
        (old_package / "governance/approved_live_config.json").read_bytes()
    )
    (package / "data").symlink_to(
        base / "shared/hermes_escape_top/data", target_is_directory=True
    )
    (package / "config").symlink_to(
        base / "shared/hermes_escape_top/config", target_is_directory=True
    )
    old_attestation = json.loads(
        (old_package / "LIVE_CONFIG_ATTESTATION.json").read_text(encoding="utf-8")
    )
    old_attestation.update(
        {
            "generated_at": "2026-07-13T08:30:00+08:00",
            "release_id": release_name,
            "release_hash": "feed123",
            "policy_sha256": hashlib.sha256(policy.read_bytes()).hexdigest(),
        }
    )
    _write_json(package / "LIVE_CONFIG_ATTESTATION.json", old_attestation)
    (release / "reports").symlink_to(base / "reports", target_is_directory=True)
    current.unlink()
    current.symlink_to(Path("releases") / release_name, target_is_directory=True)
    return release, old_attestation["policy_sha256"]


def test_clean_morning_acceptance_passes_with_visible_expected_warnings(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    assert report["status"] == "PASS"
    assert report["readiness"] == {
        "runtime_integrity": {"status": "PASS", "failed_checks": []},
        "strategy_decision": {
            "status": "WARN",
            "failed_checks": [],
            "warning_checks": ["bound_health_report", "dashboard_health"],
        },
    }
    statuses = {row["id"]: row["status"] for row in report["checks"]}
    assert statuses == {
        "release_identity": "PASS",
        "scheduled_receipt": "PASS",
        "scheduled_audit": "PASS",
        "persistence_transaction": "PASS",
        "bound_health_report": "WARN",
        "dashboard_health": "WARN",
        "watchdog": "PASS",
    }
    assert "dollar" in report["summary"]
    assert "IBKR" in report["summary"]
    assert len(report["checks"]) == 7
    assert report["operational_observations"]["runtime_retention"]["status"] == "PENDING"
    assert report["operational_observations"]["market_admission"]["status"] == "PASS"
    assert report["operational_observations"]["market_admission"]["consecutive_ok"] == 3
    assert report["operational_observations"]["external_source_migrations"]["status"] == "OBSERVING"


def test_new_release_with_old_hash_bound_report_is_pending_without_rewriting_evidence(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    base = home / ".hermes/skills/investment/escape-top"
    report_path = base / "reports/system_health_2026-07-10.json"
    receipt_path = base / "shared/hermes_escape_top/data/archive/run_receipt.json"
    report_before = report_path.read_bytes()
    receipt_before = receipt_path.read_bytes()
    _switch_to_new_release(home)
    dashboard_health["level"] = "OK"
    dashboard_health["layers"]["strategy_data"] = {"level": "OK", "checks": []}

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    assert report["status"] == "PENDING_POST_DEPLOY"
    assert report["readiness"]["runtime_integrity"] == {
        "status": "PASS",
        "failed_checks": [],
    }
    assert report["readiness"]["strategy_decision"]["status"] == "PENDING_POST_DEPLOY"
    assert report["post_deploy_certification"]["status"] == "PENDING_POST_DEPLOY"
    assert report["post_deploy_certification"]["report_generator_release_hash"] == "d9ec486"
    assert report["post_deploy_certification"]["current_release_hash"] == "feed123"
    assert report_path.read_bytes() == report_before
    assert receipt_path.read_bytes() == receipt_before


def test_matching_report_before_next_natural_schedule_remains_pending(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    _release, policy_sha = _switch_to_new_release(home)
    report_path = (
        home
        / ".hermes/skills/investment/escape-top/reports/system_health_2026-07-10.json"
    )
    health_report = json.loads(report_path.read_text(encoding="utf-8"))
    health_report["generated_at"] = "2026-07-13T08:45:00+08:00"
    health_report["generator_release_hash"] = "feed123"
    health_report["generator_policy_sha256"] = policy_sha
    _write_json(report_path, health_report)
    dashboard_health["level"] = "OK"
    dashboard_health["layers"]["strategy_data"] = {"level": "OK", "checks": []}

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    assert report["status"] == "PENDING_POST_DEPLOY"
    assert report["post_deploy_certification"]["status"] == "PENDING_POST_DEPLOY"
    assert report["post_deploy_certification"]["next_scheduled_at"] == (
        "2026-07-14T07:10:00+08:00"
    )


def test_next_natural_scheduled_report_certifies_new_release(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    release, policy_sha = _switch_to_new_release(home)
    attestation_path = release / "hermes_escape_top/LIVE_CONFIG_ATTESTATION.json"
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    attestation["generated_at"] = "2026-07-12T18:30:00+08:00"
    _write_json(attestation_path, attestation)
    report_path = (
        home
        / ".hermes/skills/investment/escape-top/reports/system_health_2026-07-10.json"
    )
    health_report = json.loads(report_path.read_text(encoding="utf-8"))
    health_report["generated_at"] = "2026-07-13T07:11:05+08:00"
    health_report["generator_release_hash"] = "feed123"
    health_report["generator_policy_sha256"] = policy_sha
    _write_json(report_path, health_report)

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    assert report["status"] == "PASS"
    assert report["post_deploy_certification"]["status"] == "CERTIFIED"


def test_post_deploy_pending_never_masks_strategy_or_runtime_failures(tmp_path):
    module = _load_module()

    def collect_with_failure(kind: str) -> dict:
        case_home = tmp_path / kind
        home, now, dashboard_health = _acceptance_fixture(case_home)
        base = home / ".hermes/skills/investment/escape-top"
        archive = base / "shared/hermes_escape_top/data/archive"
        report_path = base / "reports/system_health_2026-07-10.json"
        _switch_to_new_release(home)
        if kind == "stale_market":
            health_report = json.loads(report_path.read_text(encoding="utf-8"))
            blocking = {
                "level": "DEGRADED",
                "label": "行情落后 1 个交易日",
                "detail": "as_of=2026-07-09",
                "layer": "strategy_data",
            }
            health_report["health"]["level"] = "DEGRADED"
            health_report["health"]["layers"]["strategy_data"] = {
                "level": "DEGRADED",
                "checks": [blocking],
            }
            _write_json(report_path, health_report)
            dashboard_health["level"] = "DEGRADED"
            dashboard_health["layers"]["strategy_data"] = {
                "level": "DEGRADED",
                "checks": [blocking],
            }
        elif kind == "bad_receipt":
            receipt_path = archive / "run_receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt.update({"status": "FAILED", "ok": False})
            _write_json(receipt_path, receipt)
        elif kind == "audit_mismatch":
            audit_path = archive / "audit_log.jsonl"
            audit_row = json.loads(audit_path.read_text(encoding="utf-8"))
            audit_row["payload"]["as_of"] = "2026-07-09"
            audit_path.write_text(json.dumps(audit_row) + "\n", encoding="utf-8")
        elif kind == "transaction_failure":
            manifest_path = archive / ".score_run_transactions/runs/run-1/manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["status"] = "PENDING"
            _write_json(manifest_path, manifest)
        return module.collect_acceptance(
            home=home,
            now=now,
            dashboard_reader=lambda _url: (200, dashboard_health),
        )

    for kind in ("stale_market", "bad_receipt", "audit_mismatch", "transaction_failure"):
        report = collect_with_failure(kind)
        assert report["status"] == "FAIL", kind
        assert report["post_deploy_certification"]["status"] != "PENDING_POST_DEPLOY", kind


def test_same_hash_redeploy_requires_a_report_after_the_new_attestation():
    module = _load_module()
    checks = [
        {"id": check_id, "status": "PASS"}
        for check_id in module.RUNTIME_INTEGRITY_CHECKS
    ]
    checks.extend(
        [
            {"id": "bound_health_report", "status": "PASS"},
            {"id": "dashboard_health", "status": "PASS"},
        ]
    )

    certification = module._post_deploy_certification(
        {
            "hash": "same123",
            "policy_sha256": "same-policy",
            "attested_at": "2026-07-13T08:30:00+08:00",
        },
        {
            "generated_at": "2026-07-13T07:11:00+08:00",
            "generator_release_hash": "same123",
            "generator_policy_sha256": "same-policy",
        },
        {"level": "OK", "layers": {"strategy_data": {"level": "OK"}}},
        checks,
    )

    assert certification["status"] == "PENDING_POST_DEPLOY"


def test_strategy_failure_does_not_misreport_runtime_integrity(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    base = home / ".hermes/skills/investment/escape-top"
    report_path = base / "reports/system_health_2026-07-10.json"
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    blocking = {
        "level": "DEGRADED",
        "label": "双源行情候选已隔离",
        "detail": "VOLUME_MISMATCH=1",
        "layer": "strategy_data",
    }
    report_payload["health"]["layers"]["strategy_data"] = {
        "level": "DEGRADED",
        "checks": [blocking],
    }
    _write_json(report_path, report_payload)
    dashboard_health["layers"]["strategy_data"] = {
        "level": "DEGRADED",
        "checks": [blocking],
    }

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    assert report["status"] == "FAIL"
    assert report["readiness"]["runtime_integrity"] == {
        "status": "PASS",
        "failed_checks": [],
    }
    assert report["readiness"]["strategy_decision"] == {
        "status": "FAIL",
        "failed_checks": ["bound_health_report", "dashboard_health"],
        "warning_checks": [],
    }


def test_morning_acceptance_rejects_self_attested_unapproved_live_config(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    base = home / ".hermes/skills/investment/escape-top"
    config_path = base / "current/hermes_escape_top/config/config.json"
    attestation_path = base / "current/hermes_escape_top/LIVE_CONFIG_ATTESTATION.json"
    live_config = json.loads(config_path.read_text(encoding="utf-8"))
    live_config["features"]["rogue"] = True
    _write_json(config_path, live_config)
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    attestation["live_config_sha256"] = hashlib.sha256(config_path.read_bytes()).hexdigest()
    attestation["live_config_semantic_sha256"] = _semantic_sha256(live_config)
    attestation["feature_diff"]["rogue"] = {"repo": False, "live": True}
    _write_json(attestation_path, attestation)

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    release = next(row for row in report["checks"] if row["id"] == "release_identity")
    assert release["status"] == "FAIL"
    assert "policy" in release["detail"].lower()


def test_release_without_policy_fails_closed(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    package = (
        home
        / ".hermes/skills/investment/escape-top/current/hermes_escape_top"
    )
    (package / "governance/approved_live_config.json").unlink()
    (package / "governance/live_config_policy.py").unlink()
    attestation_path = package / "LIVE_CONFIG_ATTESTATION.json"
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    attestation["schema_version"] = "hermes-live-config-attestation-v1"
    for key in (
        "policy_sha256",
        "live_config_semantic_sha256",
        "repo_config_semantic_sha256",
    ):
        attestation.pop(key, None)
    _write_json(attestation_path, attestation)
    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    release = next(row for row in report["checks"] if row["id"] == "release_identity")
    assert release["status"] == "FAIL"
    assert "policy" in release["detail"].lower()
    assert report["release"] == {}


def test_retention_missing_warns_only_after_first_expected_window(tmp_path):
    module = _load_module()
    home, _now, _dashboard_health = _acceptance_fixture(tmp_path)
    base = home / ".hermes/skills/investment/escape-top"
    archive = base / "current/hermes_escape_top/data/archive"

    before, before_warnings = module._collect_operational_observations(
        home,
        base,
        archive,
        datetime(2026, 7, 18, 9, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    after, after_warnings = module._collect_operational_observations(
        home,
        base,
        archive,
        datetime(2026, 7, 19, 9, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert before["runtime_retention"]["status"] == "PENDING"
    assert not any("runtime retention" in warning for warning in before_warnings)
    assert after["runtime_retention"]["status"] == "WARN"
    assert any("runtime retention" in warning for warning in after_warnings)


def test_retention_apply_evidence_older_than_eight_days_warns(tmp_path):
    module = _load_module()
    home, _now, _dashboard_health = _acceptance_fixture(tmp_path)
    base = home / ".hermes/skills/investment/escape-top"
    archive = base / "current/hermes_escape_top/data/archive"
    report_path = home / ".hermes/logs/retention/runtime_retention_latest.json"
    _write_json(
        report_path,
        {
            "schema_version": "hermes-runtime-retention-v1",
            "generated_at": "2026-07-07T08:30:00+08:00",
            "status": "PASS",
            "result": {"mode": "APPLIED", "deleted_count": 12},
        },
    )

    observations, warnings = module._collect_operational_observations(
        home,
        base,
        archive,
        datetime(2026, 7, 16, 9, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert observations["runtime_retention"]["status"] == "WARN"
    assert "older than 8 days" in observations["runtime_retention"]["detail"]
    assert warnings


def test_market_admission_maturity_stops_at_a_missing_run_day(tmp_path):
    module = _load_module()
    archive = tmp_path / "archive"
    for run_day, completed_through in (
        ("2026-07-10", "2026-07-09"),
        ("2026-07-12", "2026-07-10"),
    ):
        _write_json(
            archive / f"market_admission_{run_day}.json",
            {
                "status": "OK",
                "completed_through": completed_through,
            },
        )

    observation = module._market_admission_observation(
        archive,
        {"live_enabled_features": ["use_market_admission_gate"]},
    )

    assert observation["status"] == "OBSERVING"
    assert observation["consecutive_ok"] == 1


def test_external_source_migration_observation_accepts_automatic_official_channels(tmp_path):
    module = _load_module()
    path = tmp_path / ".hermes/logs/external/external_precheck_latest.json"
    _write_json(
        path,
        {
            "sources": {
                "aaii_sentiment": {
                    "status": "OK",
                    "freshness_status": "OK",
                    "evidence_status": "MATCH",
                    "latest_source_channel": "official_insights_rss",
                    "migration_status": "MONITORED",
                    "migration_readiness": "NOT_APPLICABLE",
                    "official_issue_as_of": "2026-07-18",
                    "official_file_sha256": "a" * 64,
                    "finished_at": "2026-07-22T06:45:05+08:00",
                },
                "naaim_exposure": {
                    "status": "OK",
                    "freshness_status": "OK",
                    "evidence_status": "MATCH",
                    "latest_source_channel": "naaim_public_workbook",
                    "migration_status": "MIGRATION_DUE",
                    "migration_readiness": "AUTOMATIC_PUBLIC",
                    "migration_deadline": "2026-08-01",
                    "official_issue_as_of": "2026-07-15",
                    "official_file_sha256": "b" * 64,
                    "finished_at": "2026-07-22T06:45:04+08:00",
                },
            }
        },
    )

    observation = module._external_source_migration_observation(
        tmp_path,
        datetime(2026, 7, 22, 9, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert observation["status"] == "OBSERVING"
    assert observation["sources"]["aaii_sentiment"]["automated"] is True
    assert observation["sources"]["naaim_exposure"]["automated"] is True
    assert observation["sources"]["naaim_exposure"]["migration_status"] == "MIGRATION_DUE"


def test_external_source_migration_observation_warns_after_manual_or_expired_evidence(tmp_path):
    module = _load_module()
    path = tmp_path / ".hermes/logs/external/external_precheck_latest.json"
    _write_json(
        path,
        {
            "sources": {
                "aaii_sentiment": {
                    "status": "OK",
                    "freshness_status": "OK",
                    "evidence_status": "MATCH",
                    "latest_source_channel": "manual_official_file",
                    "migration_status": "MONITORED",
                    "official_issue_as_of": "2026-08-06",
                    "official_file_sha256": "a" * 64,
                    "finished_at": "2026-08-07T06:45:05+08:00",
                },
                "naaim_exposure": {
                    "status": "OK",
                    "freshness_status": "OK",
                    "evidence_status": "MATCH",
                    "latest_source_channel": "manual_official_file",
                    "migration_status": "ACTION_REQUIRED",
                    "migration_readiness": "MANUAL_FALLBACK",
                    "migration_deadline": "2026-08-01",
                    "official_issue_as_of": "2026-08-05",
                    "official_file_sha256": "b" * 64,
                    "finished_at": "2026-08-07T06:45:04+08:00",
                },
            }
        },
    )

    observation = module._external_source_migration_observation(
        tmp_path,
        datetime(2026, 8, 7, 9, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert observation["status"] == "WARN"
    assert "manual" in observation["detail"].lower()
    assert "ACTION_REQUIRED" in observation["detail"]


def test_external_source_migration_observation_accepts_retired_naaim_history(tmp_path):
    module = _load_module()
    path = tmp_path / ".hermes/logs/external/external_precheck_latest.json"
    _write_json(
        path,
        {
            "sources": {
                "aaii_sentiment": {
                    "status": "OK",
                    "freshness_status": "OK",
                    "evidence_status": "MATCH",
                    "latest_source_channel": "official_insights_rss",
                    "migration_status": "MONITORED",
                    "migration_readiness": "NOT_APPLICABLE",
                    "official_issue_as_of": "2026-08-06",
                    "official_file_sha256": "a" * 64,
                    "finished_at": "2026-08-12T06:45:05+08:00",
                },
                "naaim_exposure": {
                    "status": "OK",
                    "freshness_status": "STALE",
                    "evidence_status": "MATCH",
                    "latest_source_channel": "naaim_public_workbook",
                    "migration_status": "RETIRED_PAYWALL",
                    "migration_readiness": "NOT_EVIDENCED",
                    "lifecycle_status": "RETIRED_PAYWALL",
                    "lifecycle_reason": "public workbook retired behind paid subscription",
                    "official_issue_as_of": "2026-07-29",
                    "official_file_sha256": "b" * 64,
                    "finished_at": "2026-08-07T06:45:04+08:00",
                },
            }
        },
    )

    observation = module._external_source_migration_observation(
        tmp_path,
        datetime(2026, 8, 12, 9, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert observation["status"] == "PASS"
    assert observation["sources"]["naaim_exposure"]["retired"] is True
    assert "retired behind paywall" in observation["detail"]


def test_duplicate_scheduled_run_fails_acceptance(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    audit = home / ".hermes/skills/investment/escape-top/current/hermes_escape_top/data/archive/audit_log.jsonl"
    audit.write_text(audit.read_text(encoding="utf-8") * 2, encoding="utf-8")

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    row = next(item for item in report["checks"] if item["id"] == "scheduled_audit")
    assert report["status"] == "FAIL"
    assert row["status"] == "FAIL"
    assert "expected 1" in row["detail"]


def test_live_config_hash_drift_fails_release_identity(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    config = home / ".hermes/skills/investment/escape-top/current/hermes_escape_top/config/config.json"
    _write_json(config, {"features": {"use_market_admission_gate": False}})

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    row = next(item for item in report["checks"] if item["id"] == "release_identity")
    assert row["status"] == "FAIL"
    assert "not approved by policy" in row["detail"]


def test_health_report_hash_mismatch_fails_acceptance(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    path = home / ".hermes/skills/investment/escape-top/current/reports/system_health_2026-07-10.json"
    health_report = json.loads(path.read_text(encoding="utf-8"))
    health_report["input_hash"] = "wrong-run"
    _write_json(path, health_report)

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    row = next(item for item in report["checks"] if item["id"] == "bound_health_report")
    assert report["status"] == "FAIL"
    assert row["status"] == "FAIL"
    assert "input_hash" in row["detail"]


def test_immutable_health_report_wins_when_compatibility_file_was_overwritten(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    reports = home / ".hermes/skills/investment/escape-top/current/reports"
    compatibility = reports / "system_health_2026-07-10.json"
    matching = json.loads(compatibility.read_text(encoding="utf-8"))
    run_path = reports / "system_health_runs/system_health_2026-07-10_run_input-hash-1.json"
    _write_json(run_path, matching)
    overwritten = dict(matching, input_hash="later-preview-hash")
    _write_json(compatibility, overwritten)

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    row = next(item for item in report["checks"] if item["id"] == "bound_health_report")
    assert row["status"] == "WARN"
    assert "system_health_runs" in row["evidence"]


def test_unreadable_immutable_health_report_is_visible_warning(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    reports = home / ".hermes/skills/investment/escape-top/current/reports"
    corrupt = reports / "system_health_runs/system_health_2026-07-10_corrupt.json"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_text("{not-json\n", encoding="utf-8")

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    row = next(item for item in report["checks"] if item["id"] == "bound_health_report")
    assert row["status"] == "WARN"
    assert "unreadable health evidence" in row["detail"]
    assert corrupt.name in row["detail"]


def test_residual_active_transaction_fails_acceptance(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    active = home / ".hermes/skills/investment/escape-top/current/hermes_escape_top/data/archive/.score_run_transactions/active.json"
    _write_json(active, {"run_id": "run-1"})

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    row = next(item for item in report["checks"] if item["id"] == "persistence_transaction")
    assert report["status"] == "FAIL"
    assert "residual active transaction" in row["detail"]


def test_non_committed_transaction_fails_acceptance(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    manifest = home / ".hermes/skills/investment/escape-top/current/hermes_escape_top/data/archive/.score_run_transactions/runs/run-1/manifest.json"
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["status"] = "PENDING"
    _write_json(manifest, value)

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    row = next(item for item in report["checks"] if item["id"] == "persistence_transaction")
    assert report["status"] == "FAIL"
    assert "status=PENDING" in row["detail"]


def test_transaction_manifest_must_bind_to_scheduled_audit(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    manifest = home / ".hermes/skills/investment/escape-top/current/hermes_escape_top/data/archive/.score_run_transactions/runs/run-1/manifest.json"
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["metadata"]["as_of"] = "2026-07-09"
    _write_json(manifest, value)

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    row = next(item for item in report["checks"] if item["id"] == "persistence_transaction")
    assert report["status"] == "FAIL"
    assert "metadata" in row["detail"]


def test_transaction_artifacts_require_exact_archive_paths(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    manifest = home / ".hermes/skills/investment/escape-top/current/hermes_escape_top/data/archive/.score_run_transactions/runs/run-1/manifest.json"
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["artifacts"][0]["path"] = "wrong/audit_log.jsonl"
    _write_json(manifest, value)

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    row = next(item for item in report["checks"] if item["id"] == "persistence_transaction")
    assert report["status"] == "FAIL"
    assert "business artifacts mismatch" in row["detail"]


@pytest.mark.parametrize(
    ("level", "label"),
    [
        ("INFO", "BTC funding research unavailable"),
        ("DEGRADED", "VIX9D auxiliary stale"),
    ],
)
def test_auxiliary_source_health_warns_without_blocking_acceptance(
    tmp_path, level, label
):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    path = home / ".hermes/skills/investment/escape-top/current/reports/system_health_2026-07-10.json"
    health_report = json.loads(path.read_text(encoding="utf-8"))
    bad_aux = {
        "level": level,
        "checks": [{"level": level, "label": label, "detail": "1d"}],
    }
    health_report["health"]["layers"]["auxiliary_flows"] = bad_aux
    dashboard_health["layers"]["auxiliary_flows"] = bad_aux
    _write_json(path, health_report)

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    assert report["status"] == "PASS"
    assert next(
        item for item in report["checks"] if item["id"] == "bound_health_report"
    )["status"] == "WARN"
    assert next(
        item for item in report["checks"] if item["id"] == "dashboard_health"
    )["status"] == "WARN"
    assert "auxiliary" in report["summary"]


def test_operational_refresh_failure_is_visible_without_blocking_acceptance():
    module = _load_module()
    health = {
        "layers": {
            "strategy_data": {"level": "OK", "checks": []},
            "position_reconciliation": {"level": "OK", "checks": []},
            "auxiliary_flows": {"level": "OK", "checks": []},
            "operations": {
                "level": "DEGRADED",
                "checks": [
                    {
                        "level": "DEGRADED",
                        "label": "外部数据源刷新失败（认证缓存仍有效）",
                        "detail": "naaim_exposure: FETCH_ERROR workbook unavailable",
                        "layer": "operations",
                    }
                ],
            },
        }
    }

    failures, warnings = module._health_policy(health)

    assert failures == []
    assert warnings == [
        "operations: 外部数据源刷新失败（认证缓存仍有效） "
        "naaim_exposure: FETCH_ERROR workbook unavailable"
    ]


def test_duplicate_dollar_health_rows_are_one_visible_warning(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    path = home / ".hermes/skills/investment/escape-top/current/reports/system_health_2026-07-10.json"
    health_report = json.loads(path.read_text(encoding="utf-8"))
    external_dollar = {
        "level": "DEGRADED",
        "label": "外部数据源陈旧",
        "detail": "dollar: age=11d official publisher has not posted a newer observation",
        "layer": "strategy_data",
    }
    health_report["health"]["layers"]["strategy_data"]["checks"].append(
        external_dollar
    )
    dashboard_health["layers"]["strategy_data"]["checks"].append(external_dollar)
    _write_json(path, health_report)

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    assert report["status"] == "PASS"
    assert next(
        item for item in report["checks"] if item["id"] == "bound_health_report"
    )["status"] == "WARN"
    assert next(
        item for item in report["checks"] if item["id"] == "dashboard_health"
    )["status"] == "WARN"
    assert report["summary"].count("dollar stale") == 1


def test_duplicate_dollar_warning_does_not_hide_external_real_rate(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    path = home / ".hermes/skills/investment/escape-top/current/reports/system_health_2026-07-10.json"
    health_report = json.loads(path.read_text(encoding="utf-8"))
    rows = [
        {
            "level": "DEGRADED",
            "label": "外部数据源陈旧",
            "detail": "dollar: age=11d publisher lag",
            "layer": "strategy_data",
        },
        {
            "level": "DEGRADED",
            "label": "外部数据源陈旧",
            "detail": "real_rate: age=7d refresh required",
            "layer": "strategy_data",
        },
    ]
    health_report["health"]["layers"]["strategy_data"]["checks"].extend(rows)
    dashboard_health["layers"]["strategy_data"]["checks"].extend(rows)
    _write_json(path, health_report)

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    assert report["status"] == "FAIL"
    assert "real_rate" in next(
        item for item in report["checks"] if item["id"] == "bound_health_report"
    )["detail"]
    assert "real_rate" in next(
        item for item in report["checks"] if item["id"] == "dashboard_health"
    )["detail"]


def test_dollar_warning_cannot_hide_a_second_stale_source(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    path = home / ".hermes/skills/investment/escape-top/current/reports/system_health_2026-07-10.json"
    health_report = json.loads(path.read_text(encoding="utf-8"))
    health_report["health"]["layers"]["strategy_data"]["checks"][0]["detail"] = (
        "dollar, naaim_exposure"
    )
    dashboard_health["layers"]["strategy_data"]["checks"][0]["detail"] = (
        "dollar, naaim_exposure"
    )
    _write_json(path, health_report)

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    assert report["status"] == "FAIL"
    assert next(
        item for item in report["checks"] if item["id"] == "bound_health_report"
    )["status"] == "FAIL"
    assert next(
        item for item in report["checks"] if item["id"] == "dashboard_health"
    )["status"] == "FAIL"


def test_bound_health_report_must_be_scheduled_and_match_as_of(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    path = home / ".hermes/skills/investment/escape-top/current/reports/system_health_2026-07-10.json"
    health_report = json.loads(path.read_text(encoding="utf-8"))
    health_report["as_of"] = "2026-07-09"
    health_report["run_type"] = "manual_rerun"
    _write_json(path, health_report)

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    row = next(item for item in report["checks"] if item["id"] == "bound_health_report")
    assert report["status"] == "FAIL"
    assert "report_as_of" in row["detail"]
    assert "run_type" in row["detail"]


def test_watchdog_alert_in_scheduled_window_fails_acceptance(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    watchdog = home / ".hermes/logs/watchdog.log"
    watchdog.write_text(
        "2026-07-13T09:00:05 ALERT as_of=2026-07-10 lag=3\n", encoding="utf-8"
    )

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    row = next(item for item in report["checks"] if item["id"] == "watchdog")
    assert report["status"] == "FAIL"
    assert row["status"] == "FAIL"
    assert "ALERT" in row["detail"]


def test_report_writer_atomically_publishes_dated_and_latest_files(tmp_path):
    module = _load_module()
    report = {
        "schema_version": "hermes-morning-acceptance-v1",
        "generated_at": "2026-07-13T09:05:00+08:00",
        "acceptance_date": "2026-07-13",
        "status": "PASS",
        "summary": "PASS; no warnings",
        "checks": [],
    }

    paths = module.write_reports(report, tmp_path / "acceptance")

    assert json.loads(paths["dated_json"].read_text(encoding="utf-8")) == report
    assert json.loads(paths["latest_json"].read_text(encoding="utf-8")) == report
    assert "Hermes Morning Acceptance" in paths["dated_markdown"].read_text(encoding="utf-8")
    assert paths["latest_markdown"].read_text(encoding="utf-8") == paths[
        "dated_markdown"
    ].read_text(encoding="utf-8")
    assert list((tmp_path / "acceptance").glob("*.tmp")) == []


def test_pending_post_deploy_uses_distinct_nonzero_exit_code(monkeypatch, tmp_path):
    module = _load_module()
    pending = {
        "schema_version": "hermes-morning-acceptance-v1",
        "generated_at": "2026-07-13T09:05:00+08:00",
        "acceptance_date": "2026-07-13",
        "status": "PENDING_POST_DEPLOY",
        "summary": "awaiting natural scheduled run",
        "checks": [],
    }
    monkeypatch.setattr(module, "collect_acceptance", lambda **_kwargs: pending)

    exit_code = module.main(
        [
            "--home",
            str(tmp_path / "home"),
            "--output-dir",
            str(tmp_path / "acceptance"),
            "--now",
            "2026-07-13T09:05:00+08:00",
        ]
    )

    assert exit_code == 3
