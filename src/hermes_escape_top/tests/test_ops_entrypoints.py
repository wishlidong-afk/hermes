from __future__ import annotations

import json
import importlib.util
import os
from pathlib import Path
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


def test_daily_entry_refreshes_alpaca_flow_from_latest_completed_session():
    module = _load_run_daily_module()

    command = module.build_alpaca_flow_command()

    assert command[-3:] == ["hermes_escape_top.core.data.alpaca_flow", "--as-of", "latest"]


def test_daily_entry_honors_runtime_root_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    runtime = tmp_path / "escape-top-runtime"
    monkeypatch.setenv("HERMES_RUNTIME_ROOT", str(runtime))

    module = _load_run_daily_module()

    assert module.RUNTIME_ROOT == runtime.resolve()


def test_shell_entrypoints_prefer_current_release_when_present():
    daily = (REPO_ROOT / "ops" / "run_daily.sh").read_text(encoding="utf-8")
    dashboard = (REPO_ROOT / "ops" / "serve_dashboard.sh").read_text(encoding="utf-8")

    assert 'if [ -d "$BASE/current/hermes_escape_top" ]; then' in daily
    assert 'RUNTIME="$BASE/current"' in daily
    assert 'HERMES_RUNTIME_ROOT="$BASE"' in daily
    assert 'export HERMES_RUNTIME_ROOT="$BASE"' in dashboard
    assert 'export PYTHONPATH="$RUNTIME"' in dashboard


def test_daily_entry_writes_auxiliary_alpaca_status_atomically(tmp_path):
    module = _load_run_daily_module()
    path = tmp_path / "archive" / "alpaca_daily_flow_status.json"

    record = module.write_alpaca_flow_status(
        {"status": "ERROR", "error": "timeout"},
        path=path,
    )

    assert record["status"] == "ERROR"
    assert json.loads(path.read_text(encoding="utf-8"))["error"] == "timeout"
    assert not list(path.parent.glob("*.tmp"))


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
