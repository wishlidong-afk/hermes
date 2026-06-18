from __future__ import annotations

import importlib.util
from pathlib import Path


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


def test_verify_live_uses_non_official_entry_mode():
    script = (REPO_ROOT / "ops" / "verify_live.sh").read_text(encoding="utf-8")

    assert 'run_daily.sh" --deploy-verify' in script
    assert 'payload.get("run_type") == "manual_rerun"' in script
