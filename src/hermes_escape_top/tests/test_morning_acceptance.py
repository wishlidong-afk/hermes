from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[3]
EXPECTED_ARTIFACTS = (
    "audit_log.jsonl",
    "flow_reference.sqlite",
    "hermes_state.sqlite",
    "mirror_reference.sqlite",
    "reentry_state.sqlite",
    "signal_journal.jsonl",
)


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
    reports = base / "reports"
    package.mkdir(parents=True)
    archive.mkdir(parents=True)
    reports.mkdir(parents=True)
    (package / "VERSION").write_text("d9ec486 20260712_184620\n", encoding="utf-8")
    (package / "data").symlink_to(base / "shared/hermes_escape_top/data", target_is_directory=True)
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
            "as_of": "2026-07-10",
            "input_hash": "input-hash-1",
            "run_type": "scheduled",
            "run_receipt": receipt,
            "health": health,
        },
    )

    watchdog = home / ".hermes/logs/watchdog.log"
    watchdog.parent.mkdir(parents=True, exist_ok=True)
    watchdog.write_text(
        "2026-07-13T09:00:05 ok as_of=2026-07-10 lag=0\n", encoding="utf-8"
    )
    return home, now, health


def test_clean_morning_acceptance_passes_with_visible_expected_warnings(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)

    report = module.collect_acceptance(
        home=home,
        now=now,
        dashboard_reader=lambda _url: (200, dashboard_health),
    )

    assert report["status"] == "PASS"
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


def test_unexpected_auxiliary_degradation_fails_acceptance(tmp_path):
    module = _load_module()
    home, now, dashboard_health = _acceptance_fixture(tmp_path)
    path = home / ".hermes/skills/investment/escape-top/current/reports/system_health_2026-07-10.json"
    health_report = json.loads(path.read_text(encoding="utf-8"))
    bad_aux = {
        "level": "DEGRADED",
        "checks": [{"level": "DEGRADED", "label": "SIP stale", "detail": "1d"}],
    }
    health_report["health"]["layers"]["auxiliary_flows"] = bad_aux
    dashboard_health["layers"]["auxiliary_flows"] = bad_aux
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
