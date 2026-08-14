from __future__ import annotations

import json
import importlib.util
import os
from datetime import date, datetime
from pathlib import Path
import plistlib
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_run_daily_module():
    path = REPO_ROOT / "ops" / "run_daily.py"
    spec = importlib.util.spec_from_file_location("hermes_ops_run_daily", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_watchdog_module():
    path = REPO_ROOT / "ops" / "hermes_watchdog.py"
    spec = importlib.util.spec_from_file_location("hermes_ops_watchdog", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_audit(path: Path, *records: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(records) + "\n", encoding="utf-8")


def test_scheduled_entry_commits_state_and_preserves_run_type():
    module = _load_run_daily_module()
    command = module.build_command(["--run-type", "scheduled"])

    assert "--commit-state" in command
    assert command[-2:] == ["--run-type", "scheduled"]


def test_deploy_verify_is_manual_and_does_not_commit_state():
    module = _load_run_daily_module()
    command = module.build_command(["--deploy-verify"])

    assert "--commit-state" not in command
    assert command[-2:] == ["--run-type", "manual_rerun"]


def test_daily_entry_honors_runtime_root_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    runtime = tmp_path / "escape-top-runtime"
    monkeypatch.setenv("HERMES_RUNTIME_ROOT", str(runtime))

    module = _load_run_daily_module()

    assert module.RUNTIME_ROOT == runtime.resolve()


def test_shell_entrypoints_prefer_current_release_when_present():
    daily = (REPO_ROOT / "ops" / "run_daily.sh").read_text(encoding="utf-8")
    dashboard = (REPO_ROOT / "ops" / "serve_dashboard.sh").read_text(encoding="utf-8")
    external = (REPO_ROOT / "ops" / "refresh_external_precheck.sh").read_text(encoding="utf-8")
    external_shadow = (REPO_ROOT / "ops" / "refresh_external_shadow.sh").read_text(encoding="utf-8")
    external_manual = (REPO_ROOT / "ops" / "refresh_external.sh").read_text(encoding="utf-8")
    third_source = (REPO_ROOT / "ops" / "retry_market_third_source.sh").read_text(encoding="utf-8")

    assert 'if [ -d "$BASE/current/hermes_escape_top" ]; then' in daily
    assert 'RUNTIME="$BASE/current"' in daily
    assert 'HERMES_RUNTIME_ROOT="$RUNTIME"' in daily
    assert 'export HERMES_RUNTIME_ROOT="$RUNTIME"' in dashboard
    assert 'export PYTHONPATH="$RUNTIME"' in dashboard
    assert 'if [ -d "$BASE/current/hermes_escape_top" ]; then' in external
    assert 'RUNTIME="$BASE/current"' in external
    assert 'HERMES_RUNTIME_ROOT="$RUNTIME"' in external
    assert 'export PYTHONPATH="$RUNTIME"' in external
    assert 'hermes_escape_top.scripts.refresh_external "$REFRESH_ARG"' in external
    assert '--lane decision' in external
    assert '--lock-timeout "${HERMES_EXTERNAL_PRECHECK_LOCK_TIMEOUT:-600}"' in external
    assert 'REFRESH_ARG="--pre-daily-check"' in external
    assert 'REFRESH_ARG="--retry-needed"' in external
    assert 'hermes_escape_top.scripts.refresh_external "$@"' in external_manual
    assert 'if [ -d "$BASE/current/hermes_escape_top" ]; then' in external_shadow
    assert 'RUNTIME="$BASE/current"' in external_shadow
    assert 'HERMES_RUNTIME_ROOT="$RUNTIME"' in external_shadow
    assert 'export PYTHONPATH="$RUNTIME"' in external_shadow
    assert "hermes_escape_top.scripts.refresh_external" in external_shadow
    assert "--all --lane shadow" in external_shadow
    assert '--lock-timeout "${HERMES_EXTERNAL_SHADOW_LOCK_TIMEOUT:-0}"' in external_shadow
    assert "hermes_escape_top.scripts.retry_market_third_source" in third_source
    assert '--lock-timeout "${HERMES_MARKET_THIRD_SOURCE_LOCK_TIMEOUT:-600}"' in third_source
    for script in (
        daily,
        dashboard,
        external,
        external_shadow,
        external_manual,
        third_source,
    ):
        assert "RUNTIME_LOCK_SHA256" in script
        assert 'runtime/$LOCK_SHA/.venv/bin/python' in script
        assert "/usr/bin/python3" not in script


def test_manual_external_entry_uses_managed_runtime_and_forwards_args(tmp_path):
    home = tmp_path / "home"
    base = home / ".hermes/skills/investment/escape-top"
    runtime = base / "current"
    scripts = runtime / "hermes_escape_top/scripts"
    scripts.mkdir(parents=True)
    (runtime / "hermes_escape_top/RUNTIME_LOCK_SHA256").write_text(
        "test-runtime\n", encoding="utf-8"
    )
    managed_python = base / "runtime/test-runtime/.venv/bin/python"
    managed_python.parent.mkdir(parents=True)
    managed_python.symlink_to(sys.executable)
    (runtime / "hermes_escape_top/__init__.py").write_text("", encoding="utf-8")
    scripts.joinpath("__init__.py").write_text("", encoding="utf-8")
    scripts.joinpath("refresh_external.py").write_text(
        "import json, os, sys\n"
        "print(json.dumps({\n"
        "    'args': sys.argv[1:],\n"
        "    'runtime': os.environ['HERMES_RUNTIME_ROOT'],\n"
        "    'data': os.environ['HERMES_DATA_DIR'],\n"
        "}))\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("HERMES_DATA_DIR", None)

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "ops/refresh_external.sh"), "--status"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "args": ["--status"],
        "runtime": str(runtime),
        "data": str(runtime / "hermes_escape_top"),
    }


def test_market_third_source_entry_uses_managed_runtime(tmp_path):
    home = tmp_path / "home"
    base = home / ".hermes/skills/investment/escape-top"
    runtime = base / "current"
    scripts = runtime / "hermes_escape_top/scripts"
    scripts.mkdir(parents=True)
    (runtime / "hermes_escape_top/RUNTIME_LOCK_SHA256").write_text(
        "test-runtime\n", encoding="utf-8"
    )
    managed_python = base / "runtime/test-runtime/.venv/bin/python"
    managed_python.parent.mkdir(parents=True)
    managed_python.symlink_to(sys.executable)
    (runtime / "hermes_escape_top/__init__.py").write_text("", encoding="utf-8")
    scripts.joinpath("__init__.py").write_text("", encoding="utf-8")
    scripts.joinpath("retry_market_third_source.py").write_text(
        "import json, os\n"
        "print(json.dumps({\n"
        "    'runtime': os.environ['HERMES_RUNTIME_ROOT'],\n"
        "    'data': os.environ['HERMES_DATA_DIR'],\n"
        "}))\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("HERMES_DATA_DIR", None)

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "ops/retry_market_third_source.sh")],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "runtime": str(runtime),
        "data": str(runtime / "hermes_escape_top"),
    }


def test_runbook_uses_explicit_validation_python_and_lists_external_wrapper():
    runbook = (REPO_ROOT / "docs/PRODUCTION_RUNBOOK.md").read_text(encoding="utf-8")

    assert "PYTHONPATH=src python3 scripts/system_validation.py" not in runbook
    assert (
        "PYTHONPATH=src /Users/liweishi/.hermes-v3/.venv/bin/python "
        "scripts/system_validation.py"
    ) in runbook
    allowlist_line = next(
        line for line in runbook.splitlines() if ".hermes` 只提交 allowlist" in line
    )
    assert "`bin/refresh_external.sh`" in allowlist_line
    assert "`bin/refresh_external_shadow.sh`" in allowlist_line
    assert "**09:20 CST** `com.hermes.external-shadow`" in runbook
    assert "--all --lane shadow" in runbook


def test_production_dependency_lock_is_exact_and_hashed():
    direct = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    lock = (REPO_ROOT / "requirements.lock").read_text(encoding="utf-8")

    for requirement in (
        "numpy==2.0.2",
        "pandas==2.3.3",
        "scipy==1.13.1",
        "requests==2.33.0",
        "curl-cffi==0.15.0",
        "yfinance==1.2.1",
        "ib-insync==0.9.86",
    ):
        assert requirement in direct
        assert requirement in lock
    assert "--hash=sha256:" in lock


def test_ci_and_package_build_use_the_audited_runtime_contract():
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    pyproject = (REPO_ROOT / "src/pyproject.toml").read_text(encoding="utf-8")

    assert "python -m pip install -r requirements.lock" in workflow
    assert "python -m pip install -r requirements.txt" not in workflow
    assert "python -m pip_audit -r requirements.lock" in workflow
    assert 'requires-python = ">=3.10"' in pyproject
    assert 'build-backend = "setuptools.build_meta:__legacy__"' in pyproject


def test_runtime_bootstrap_uses_hash_verified_immutable_environment():
    script = (REPO_ROOT / "ops/bootstrap_runtime.sh").read_text(encoding="utf-8")

    assert '"$UV_BIN" pip sync' in script
    assert "--require-hashes" in script
    assert "ib_insync" in script
    assert 'runtime/$LOCK_SHA' not in script  # destination is supplied explicitly
    assert "os.replace" in script


def test_external_precheck_launchagent_runs_before_daily():
    plist_path = REPO_ROOT / "ops" / "launchagents" / "com.hermes.external-precheck.plist"
    data = plistlib.loads(plist_path.read_bytes())

    assert data["Label"] == "com.hermes.external-precheck"
    assert data["ProgramArguments"] == ["/bin/bash", "/Users/liweishi/.hermes/bin/refresh_external_precheck.sh"]
    assert data["StartCalendarInterval"] == [
        {"Hour": 6, "Minute": 45},
        {"Hour": 7, "Minute": 5},
    ]
    assert data["StandardOutPath"].endswith("/logs/external_precheck.launchd.out.log")
    assert data["StandardErrorPath"].endswith("/logs/external_precheck.launchd.err.log")


def test_external_shadow_launchagent_runs_after_morning_acceptance():
    plist_path = REPO_ROOT / "ops" / "launchagents" / "com.hermes.external-shadow.plist"
    data = plistlib.loads(plist_path.read_bytes())

    assert data["Label"] == "com.hermes.external-shadow"
    assert data["ProgramArguments"] == [
        "/bin/bash",
        "/Users/liweishi/.hermes/bin/refresh_external_shadow.sh",
    ]
    assert data["StartCalendarInterval"] == {"Hour": 9, "Minute": 20}
    assert data["RunAtLoad"] is False
    assert data["StandardOutPath"].endswith("/logs/external_shadow.launchd.out.log")
    assert data["StandardErrorPath"].endswith("/logs/external_shadow.launchd.err.log")


def test_market_third_source_retry_runs_after_vendor_publication_window():
    plist_path = REPO_ROOT / "ops" / "launchagents" / "com.hermes.market-third-source.plist"
    data = plistlib.loads(plist_path.read_bytes())

    assert data["Label"] == "com.hermes.market-third-source"
    assert data["ProgramArguments"] == [
        "/bin/bash",
        "/Users/liweishi/.hermes/bin/retry_market_third_source.sh",
    ]
    assert data["StartCalendarInterval"] == {"Hour": 9, "Minute": 2}
    assert data["RunAtLoad"] is False
    assert data["StandardOutPath"].endswith("/logs/market_third_source.launchd.out.log")
    assert data["StandardErrorPath"].endswith("/logs/market_third_source.launchd.err.log")


def test_runtime_retention_launchagent_runs_weekly_with_audited_apply():
    plist_path = REPO_ROOT / "ops" / "launchagents" / "com.hermes.runtime-retention.plist"
    assert plist_path.exists(), "weekly runtime-retention LaunchAgent is not implemented"
    data = plistlib.loads(plist_path.read_bytes())

    assert data["Label"] == "com.hermes.runtime-retention"
    assert data["ProgramArguments"] == [
        "/usr/bin/python3",
        "/Users/liweishi/.hermes/bin/prune_runtime_artifacts.py",
        "--apply",
        "--report-dir",
        "/Users/liweishi/.hermes/logs/retention",
    ]
    assert data["StartCalendarInterval"] == {
        "Weekday": 0,
        "Hour": 8,
        "Minute": 30,
    }
    assert data["RunAtLoad"] is False
    assert data["StandardOutPath"].endswith("/logs/retention.launchd.out.log")
    assert data["StandardErrorPath"].endswith("/logs/retention.launchd.err.log")


def test_watchdog_prefers_current_release_audit_over_shared_and_legacy(tmp_path):
    module = _load_watchdog_module()
    home = tmp_path / "home"
    base = home / ".hermes" / "skills" / "investment" / "escape-top"
    _write_audit(base / "hermes_escape_top/data/archive/audit_log.jsonl", '{"as_of":"2026-07-01"}')
    _write_audit(base / "shared/hermes_escape_top/data/archive/audit_log.jsonl", '{"as_of":"2026-07-07"}')
    current = base / "current/hermes_escape_top/data/archive/audit_log.jsonl"
    _write_audit(current, '{"as_of":"2026-07-08"}')

    assert module.resolve_audit_log(home) == current
    assert module.latest_audit_as_of(home) == date(2026, 7, 8)


def test_watchdog_falls_back_to_shared_then_legacy_audit(tmp_path):
    module = _load_watchdog_module()
    home = tmp_path / "home"
    base = home / ".hermes" / "skills" / "investment" / "escape-top"
    legacy = base / "hermes_escape_top/data/archive/audit_log.jsonl"
    shared = base / "shared/hermes_escape_top/data/archive/audit_log.jsonl"
    _write_audit(legacy, '{"as_of":"2026-07-01"}')
    _write_audit(shared, '{"as_of":"2026-07-08"}')

    assert module.resolve_audit_log(home) == shared
    shared.unlink()
    assert module.resolve_audit_log(home) == legacy


def test_watchdog_skips_malformed_audit_tail_and_uses_last_valid_record(tmp_path):
    module = _load_watchdog_module()
    home = tmp_path / "home"
    audit = home / ".hermes/skills/investment/escape-top/current/hermes_escape_top/data/archive/audit_log.jsonl"
    audit.parent.mkdir(parents=True, exist_ok=True)
    audit.write_text(
        '{"as_of":"2026-07-07"}\n'
        '{"payload":{"as_of":"2026-07-08"}}\n'
        '{"payload":',
        encoding="utf-8",
    )

    assert module.latest_audit_as_of(home) == date(2026, 7, 8)


def test_watchdog_returns_none_when_audit_has_no_valid_as_of(tmp_path):
    module = _load_watchdog_module()
    home = tmp_path / "home"
    audit = home / ".hermes/skills/investment/escape-top/current/hermes_escape_top/data/archive/audit_log.jsonl"
    _write_audit(audit, "not-json", '{"status":"COMMITTED"}', '{"as_of":"bad-date"}')

    assert module.latest_audit_as_of(home) is None


def test_watchdog_reports_existing_but_invalid_audit_honestly(monkeypatch, tmp_path):
    module = _load_watchdog_module()
    audit = tmp_path / "audit_log.jsonl"
    _write_audit(audit, "not-json")
    notifications = []
    logs = []
    monkeypatch.setattr(module, "resolve_audit_log", lambda: audit)
    monkeypatch.setattr(module, "latest_audit_as_of", lambda: None)
    monkeypatch.setattr(module, "notify", lambda title, body: notifications.append((title, body)))
    monkeypatch.setattr(module, "log", logs.append)

    assert module.main() == 0
    assert notifications == [("Hermes watchdog", "audit_log has no valid as_of records")]
    assert logs == ["ALERT audit_log invalid"]


def test_watchdog_calendar_does_not_expire_after_2028():
    module = _load_watchdog_module()

    assert not module.is_trading_day(date(2031, 6, 19))
    assert not module.is_trading_day(date(2031, 7, 4))
    assert module.is_trading_day(date(2031, 7, 3))
    assert module.completed_trading_days_after(
        date(2031, 7, 3),
        datetime(2031, 7, 7, 21, 0, tzinfo=module.ET),
    ) == 1


def test_watchdog_does_not_observe_saturday_new_year_on_preceding_friday():
    module = _load_watchdog_module()

    assert module.is_trading_day(date(2027, 12, 31))
    assert module.completed_trading_days_after(
        date(2027, 12, 29),
        datetime(2028, 1, 3, 21, 0, tzinfo=module.ET),
    ) == 3


def test_watchdog_session_completion_starts_at_1630_et():
    module = _load_watchdog_module()

    assert module.last_completed_session(
        datetime(2031, 7, 7, 16, 29, tzinfo=module.ET)
    ) == date(2031, 7, 3)
    assert module.last_completed_session(
        datetime(2031, 7, 7, 16, 30, tzinfo=module.ET)
    ) == date(2031, 7, 7)


def test_external_precheck_writes_latest_and_dated_reports():
    script = (REPO_ROOT / "ops" / "refresh_external_precheck.sh").read_text(encoding="utf-8")

    assert "hermes_escape_top.scripts.pipeline_lock_exec" not in script
    assert "HERMES_EXTERNAL_PRECHECK_INNER" not in script
    assert "HERMES_EXTERNAL_PRECHECK_LOCK_TIMEOUT" in script
    assert 'DATE_STAMP="$(date +%F)"' in script
    assert 'external_precheck_${DATE_STAMP}.json' in script
    assert 'external_precheck_latest.json' in script
    assert 'external_precheck_${DATE_STAMP}.md' in script
    assert 'external_precheck_latest.md' in script
    assert 'RUN_STAMP="$(date +%Y%m%dT%H%M%S%z)_${MODE}_$$"' in script
    assert 'external_precheck_${DATE_STAMP}_${RUN_STAMP}.json' in script
    assert 'external_precheck_${DATE_STAMP}_${RUN_STAMP}.md' in script
    assert "publish_copy" in script
    assert "# External Precheck" in script
    assert "nonblocking_refresh_error_sources" in script
    assert "lifecycle_warning_sources" in script
    assert "HERMES_EXTERNAL_PRECHECK_MODE" in script
    assert "--retry-needed" in script


@pytest.mark.parametrize("exit_code", [0, 1, 75])
def test_external_shadow_uses_managed_runtime_and_preserves_evidence(tmp_path, exit_code):
    home = tmp_path / "home"
    base = home / ".hermes/skills/investment/escape-top"
    runtime = base / "current"
    scripts = runtime / "hermes_escape_top/scripts"
    scripts.mkdir(parents=True)
    (runtime / "hermes_escape_top/RUNTIME_LOCK_SHA256").write_text(
        "test-runtime\n", encoding="utf-8"
    )
    managed_python = base / "runtime/test-runtime/.venv/bin/python"
    managed_python.parent.mkdir(parents=True)
    managed_python.symlink_to(sys.executable)
    (runtime / "hermes_escape_top/__init__.py").write_text("", encoding="utf-8")
    scripts.joinpath("__init__.py").write_text("", encoding="utf-8")
    scripts.joinpath("refresh_external.py").write_text(
        "import json, os, sys\n"
        "print(json.dumps({\n"
        "    'ok': int(os.environ['TEST_EXIT_CODE']) == 0,\n"
        "    'busy': int(os.environ['TEST_EXIT_CODE']) == 75,\n"
        "    'args': sys.argv[1:],\n"
        "    'runtime': os.environ['HERMES_RUNTIME_ROOT'],\n"
        "    'data': os.environ['HERMES_DATA_DIR'],\n"
        "}))\n"
        "raise SystemExit(int(os.environ['TEST_EXIT_CODE']))\n",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "HOME": str(home),
        "TEST_EXIT_CODE": str(exit_code),
    }
    env.pop("HERMES_DATA_DIR", None)

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "ops/refresh_external_shadow.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == exit_code, result.stdout + result.stderr
    report_dir = home / ".hermes/logs/external-shadow"
    latest = report_dir / "external_shadow_latest.json"
    assert latest.exists()
    payload = json.loads(latest.read_text(encoding="utf-8"))
    assert payload["args"] == ["--all", "--lane", "shadow", "--lock-timeout", "0"]
    assert payload["runtime"] == str(runtime)
    assert payload["data"] == str(runtime / "hermes_escape_top")
    immutable = list(report_dir.glob("external_shadow_????-??-??_*.json"))
    assert len(immutable) == 1


def test_external_precheck_markdown_includes_top_level_source_status(tmp_path):
    home = tmp_path / "home"
    runtime = home / ".hermes" / "skills" / "investment" / "escape-top" / "current"
    scripts = runtime / "hermes_escape_top" / "scripts"
    scripts.mkdir(parents=True)
    (runtime / "hermes_escape_top/RUNTIME_LOCK_SHA256").write_text("test-runtime\n")
    managed_python = (
        home
        / ".hermes/skills/investment/escape-top/runtime/test-runtime/.venv/bin/python"
    )
    managed_python.parent.mkdir(parents=True)
    managed_python.symlink_to(sys.executable)
    (runtime / "hermes_escape_top" / "__init__.py").write_text("", encoding="utf-8")
    scripts.joinpath("__init__.py").write_text("", encoding="utf-8")
    scripts.joinpath("refresh_external.py").write_text(
        "import json\n"
        "print(json.dumps({\n"
        "    'ready': True,\n"
        "    'blocking_sources': [],\n"
        "    'warning_sources': ['dollar'],\n"
        "    'lifecycle_warning_sources': ['naaim_exposure'],\n"
        "    'nonblocking_refresh_error_sources': [],\n"
        "    'blocking_refresh_error_sources': [],\n"
        "    'refresh': {'ok': True, 'ok_count': 1, 'error_count': 0, 'runs': []},\n"
        "    'sources': {\n"
        "        'dollar': {\n"
        "            'status': 'OK',\n"
        "            'freshness_status': 'WARN',\n"
        "            'latest_promoted_as_of': '2026-07-02',\n"
        "            'next_action': 'run refresh_external --source dollar',\n"
        "        },\n"
        "        'naaim_exposure': {\n"
        "            'status': 'OK',\n"
        "            'freshness_status': 'STALE',\n"
        "            'lifecycle_status': 'RETIRED_PAYWALL',\n"
        "            'latest_promoted_as_of': '2026-07-29',\n"
        "            'next_action': 'certified history frozen; weekly probe only',\n"
        "        },\n"
        "    },\n"
        "}))\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "ops" / "refresh_external_precheck.sh")],
        env={**os.environ, "HOME": str(home)},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = home / ".hermes" / "logs" / "external" / "external_precheck_latest.md"
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "| dollar | OK/WARN | 2026-07-02 | run refresh_external --source dollar |" in text
    assert "lifecycle_warning_sources: `['naaim_exposure']`" in text
    assert "| naaim_exposure | OK/STALE/RETIRED_PAYWALL | 2026-07-29 | certified history frozen; weekly probe only |" in text


def test_external_precheck_keeps_two_same_day_runs_immutable(tmp_path):
    home = tmp_path / "home"
    runtime = home / ".hermes" / "skills" / "investment" / "escape-top" / "current"
    scripts = runtime / "hermes_escape_top" / "scripts"
    scripts.mkdir(parents=True)
    (runtime / "hermes_escape_top/RUNTIME_LOCK_SHA256").write_text("test-runtime\n")
    managed_python = (
        home
        / ".hermes/skills/investment/escape-top/runtime/test-runtime/.venv/bin/python"
    )
    managed_python.parent.mkdir(parents=True)
    managed_python.symlink_to(sys.executable)
    (runtime / "hermes_escape_top" / "__init__.py").write_text("", encoding="utf-8")
    scripts.joinpath("__init__.py").write_text("", encoding="utf-8")
    scripts.joinpath("refresh_external.py").write_text(
        "import json\n"
        "print(json.dumps({'ready': True, 'blocking_sources': [], "
        "'warning_sources': [], 'nonblocking_refresh_error_sources': [], "
        "'blocking_refresh_error_sources': [], 'refresh': {'ok': True}, 'sources': {}}))\n",
        encoding="utf-8",
    )
    env = {**os.environ, "HOME": str(home)}

    first = subprocess.run(
        ["bash", str(REPO_ROOT / "ops" / "refresh_external_precheck.sh")],
        env={**env, "HERMES_EXTERNAL_PRECHECK_MODE": "all"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    second = subprocess.run(
        ["bash", str(REPO_ROOT / "ops" / "refresh_external_precheck.sh")],
        env={**env, "HERMES_EXTERNAL_PRECHECK_MODE": "retry_needed"},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr
    report_dir = home / ".hermes/logs/external"
    immutable_json = list(report_dir.glob("external_precheck_????-??-??_*_*.json"))
    immutable_md = list(report_dir.glob("external_precheck_????-??-??_*_*.md"))
    assert len(immutable_json) == 2
    assert len(immutable_md) == 2
    assert any("_all_" in path.name for path in immutable_json)
    assert any("_retry_needed_" in path.name for path in immutable_json)
    assert (report_dir / "external_precheck_latest.json").exists()
    assert (report_dir / "external_precheck_latest.md").exists()


def test_run_daily_entry_uses_current_release_runtime_and_data_root(tmp_path):
    home = tmp_path / "home"
    live = home / ".hermes" / "skills" / "investment" / "escape-top"
    current = live / "current"
    script = current / "scripts" / "run_daily.py"
    package = current / "hermes_escape_top"
    script.parent.mkdir(parents=True)
    package.mkdir(parents=True)
    (package / "RUNTIME_LOCK_SHA256").write_text("test-runtime\n")
    managed_python = live / "runtime/test-runtime/.venv/bin/python"
    managed_python.parent.mkdir(parents=True)
    managed_python.symlink_to(sys.executable)
    marker = tmp_path / "entry_env.json"
    script.write_text(
        "import json, os, pathlib, sys\n"
        f"marker = pathlib.Path({str(marker)!r})\n"
        "payload = {\n"
        "    'argv': sys.argv[1:],\n"
        "    'cwd': os.getcwd(),\n"
        "    'HERMES_RUNTIME_ROOT': os.environ.get('HERMES_RUNTIME_ROOT'),\n"
        "    'HERMES_DATA_DIR': os.environ.get('HERMES_DATA_DIR'),\n"
        "}\n"
        "marker.write_text(json.dumps(payload, sort_keys=True))\n",
        encoding="utf-8",
    )

    env = {**os.environ, "HOME": str(home), "HERMES_RUN_LOG": str(tmp_path / "daily.log")}
    env.pop("HERMES_DATA_DIR", None)
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "ops" / "run_daily.sh"), "--deploy-verify"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["argv"] == ["--deploy-verify"]
    assert payload["HERMES_RUNTIME_ROOT"] == str(current)
    assert payload["HERMES_DATA_DIR"] == str(package)

    manual = subprocess.run(
        ["bash", str(REPO_ROOT / "ops" / "run_daily.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert manual.returncode == 0, manual.stdout + manual.stderr
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["argv"] == ["--run-type", "manual_rerun"]

    for override in (["--run-type", "scheduled"], ["--run-type=scheduled"]):
        before = marker.read_bytes()
        rejected = subprocess.run(
            ["bash", str(REPO_ROOT / "ops" / "run_daily.sh"), *override],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert rejected.returncode == 64
        assert "--run-type is internal" in rejected.stderr
        assert marker.read_bytes() == before

    scheduled = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "ops" / "run_daily.sh"),
            "--scheduled-launchd",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert scheduled.returncode == 0, scheduled.stdout + scheduled.stderr
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["argv"] == ["--run-type", "scheduled"]

    plist = plistlib.loads(
        (REPO_ROOT / "ops/launchagents/com.hermes.daily.plist").read_bytes()
    )
    assert plist["ProgramArguments"][-1] == "--scheduled-launchd"


def test_daily_entry_leaves_alpaca_flow_to_package_engine():
    source = (REPO_ROOT / "ops" / "run_daily.py").read_text(encoding="utf-8")

    assert "hermes_escape_top.core.data.alpaca_flow" not in source
    assert "alpaca_daily_flow_status" not in source


def test_verify_live_uses_non_official_entry_mode():
    script = (REPO_ROOT / "ops" / "verify_live.sh").read_text(encoding="utf-8")

    assert 'bash "$RUN_DAILY" --deploy-verify' in script
    assert 'payload.get("run_type") == "manual_rerun"' in script
    assert 'HERMES_DATA_DIR="$VERIFY_ROOT"' in script


def test_verify_live_uses_isolated_data_and_cleans_it(tmp_path):
    base = tmp_path / "live" / "escape-top"
    package_data = base / "hermes_escape_top" / "data"
    (package_data / "history").mkdir(parents=True)
    (package_data / "soft_history").mkdir()
    archive = package_data / "archive"
    archive.mkdir()
    (package_data / "history" / "MSTR.csv").write_text("date,Close\n2026-06-18,100\n")
    live_audit = archive / "audit_log.jsonl"
    live_state = archive / "hermes_state.sqlite"
    live_audit.write_text("live-audit-sentinel\n", encoding="utf-8")
    live_state.write_bytes(b"live-state-sentinel")

    run_daily = tmp_path / "run_daily.sh"
    run_daily.write_text(
        "#!/bin/bash\n"
        "set -eu\n"
        "mkdir -p \"$HERMES_DATA_DIR/data/archive\"\n"
        "ts=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)\n"
        "printf '{\"payload\":{\"run_type\":\"manual_rerun\",\"run_ts\":\"%s\",\"as_of\":\"2026-06-18\"}}\\n' \"$ts\" > \"$HERMES_DATA_DIR/data/archive/audit_log.jsonl\"\n"
        "printf '[M4-1] score_pipeline OK\\n[manifest] OK\\n[NEXT5] OK\\n' > \"$HERMES_RUN_LOG\"\n",
        encoding="utf-8",
    )
    run_daily.chmod(0o755)
    temp_root = tmp_path / "tmp"
    temp_root.mkdir()
    env = os.environ.copy()
    env.update({
        "HERMES_VERIFY_TEST_MODE": "1",
        "HERMES_VERIFY_BASE": str(base),
        "HERMES_VERIFY_RUN_DAILY": str(run_daily),
        "HERMES_VERIFY_PYTHON": sys.executable,
        "TMPDIR": str(temp_root),
    })

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "ops" / "verify_live.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "verify_live PASS" in result.stdout
    assert live_audit.read_text(encoding="utf-8") == "live-audit-sentinel\n"
    assert live_state.read_bytes() == b"live-state-sentinel"
    assert not list(temp_root.glob("hermes-deploy-verify.*"))


def test_verify_live_fails_when_real_run_writes_official_receipt(tmp_path):
    # Counterexample for the receipt-pollution gate (the MARK fix): a deploy-verify
    # run that stamps an official receipt/state MUST make verify_live fail. Before
    # the MARK fix this check was silently short-circuited under `set -u`.
    base = tmp_path / "live" / "escape-top"
    package_data = base / "hermes_escape_top" / "data"
    (package_data / "history").mkdir(parents=True)
    (package_data / "soft_history").mkdir()
    (package_data / "archive").mkdir()
    (package_data / "history" / "MSTR.csv").write_text("date,Close\n2026-06-18,100\n")

    run_daily = tmp_path / "run_daily.sh"
    run_daily.write_text(
        "#!/bin/bash\n"
        "set -eu\n"
        "mkdir -p \"$HERMES_DATA_DIR/data/archive\"\n"
        "ts=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)\n"
        "printf '{\"payload\":{\"run_type\":\"manual_rerun\",\"run_ts\":\"%s\",\"as_of\":\"2026-06-18\"}}\\n' \"$ts\" > \"$HERMES_DATA_DIR/data/archive/audit_log.jsonl\"\n"
        # maintenance steps pass, but the run ALSO stamps an official receipt -> pollution
        "printf '[M4-1] score_pipeline OK\\n[manifest] OK\\n[NEXT5] OK\\n[receipt] official run stamped\\n' > \"$HERMES_RUN_LOG\"\n",
        encoding="utf-8",
    )
    run_daily.chmod(0o755)
    temp_root = tmp_path / "tmp"
    temp_root.mkdir()
    env = os.environ.copy()
    env.update({
        "HERMES_VERIFY_TEST_MODE": "1",
        "HERMES_VERIFY_BASE": str(base),
        "HERMES_VERIFY_RUN_DAILY": str(run_daily),
        "HERMES_VERIFY_PYTHON": sys.executable,
        "TMPDIR": str(temp_root),
    })

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "ops" / "verify_live.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert "wrote official receipt/state" in result.stdout
    assert "verify_live PASS" not in result.stdout


def test_deploy_verify_skips_live_log_side_effects():
    script = (REPO_ROOT / "ops" / "run_daily.sh").read_text(encoding="utf-8")

    assert 'LOG="${HERMES_RUN_LOG:-' in script
    assert '[ "$rc" -eq 0 ] && [ "$OFFICIAL_RUN" -eq 1 ]' in script
