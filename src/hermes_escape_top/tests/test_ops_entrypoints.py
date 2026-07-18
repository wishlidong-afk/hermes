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
    external_manual = (REPO_ROOT / "ops" / "refresh_external.sh").read_text(encoding="utf-8")

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
    assert '--lock-timeout "${HERMES_EXTERNAL_PRECHECK_LOCK_TIMEOUT:-600}"' in external
    assert 'REFRESH_ARG="--pre-daily-check"' in external
    assert 'REFRESH_ARG="--retry-needed"' in external
    assert 'hermes_escape_top.scripts.refresh_external "$@"' in external_manual
    for script in (daily, dashboard, external, external_manual):
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


def test_production_dependency_lock_is_exact_and_hashed():
    lock = (REPO_ROOT / "requirements.lock").read_text(encoding="utf-8")

    for requirement in (
        "numpy==2.0.2",
        "pandas==2.3.3",
        "scipy==1.13.1",
        "requests==2.32.5",
        "yfinance==1.2.0",
    ):
        assert requirement in lock
    assert "--hash=sha256:" in lock


def test_runtime_bootstrap_uses_hash_verified_immutable_environment():
    script = (REPO_ROOT / "ops/bootstrap_runtime.sh").read_text(encoding="utf-8")

    assert '"$UV_BIN" pip sync' in script
    assert "--require-hashes" in script
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
    assert "HERMES_EXTERNAL_PRECHECK_MODE" in script
    assert "--retry-needed" in script


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
        "    'nonblocking_refresh_error_sources': [],\n"
        "    'blocking_refresh_error_sources': [],\n"
        "    'refresh': {'ok': True, 'ok_count': 1, 'error_count': 0, 'runs': []},\n"
        "    'sources': {\n"
        "        'dollar': {\n"
        "            'status': 'OK',\n"
        "            'freshness_status': 'WARN',\n"
        "            'latest_promoted_as_of': '2026-07-02',\n"
        "            'next_action': 'run refresh_external --source dollar',\n"
        "        }\n"
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
    assert '[ "$rc" -eq 0 ] && [ "$DEPLOY_VERIFY" -eq 0 ]' in script
