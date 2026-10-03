from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_real_pipeline_replays_restored_nonempty_state_without_network(tmp_path):
    repo = Path(__file__).resolve().parents[3]
    report = tmp_path / "replay.json"
    result = subprocess.run(
        [sys.executable, str(repo / "scripts/verify_a2_isolated_replay.py"), "--output", str(report)],
        cwd=repo, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(report.read_text())
    assert evidence["status"] == "PASS"
    assert evidence["scope"] == "ISOLATED_MECHANISM_REHEARSAL_NOT_PRODUCTION_CAPTURE"
    assert evidence["production_capture"] is False
    assert evidence["network_attempts"] == 0
    assert evidence["source_unchanged"] is True
    assert evidence["nonempty_pre_state"] is True
    assert evidence["artifacts_compared"] == 7
    assert evidence["strict_differences"] == []
    assert evidence["input_hash_equal"] is True
    assert evidence["reader_calls"] == {"positions": 1, "executions": 1, "soft_data": 1}
    assert len(set(evidence["worker_pids"])) == 3
    assert evidence["replay_transaction_status"] == "COMMITTED"


@pytest.mark.parametrize("mode", ["seed", "reference", "replay"])
def test_worker_rejects_arbitrary_root_before_any_state_write(tmp_path, mode):
    repo = Path(__file__).resolve().parents[3]
    root = tmp_path / "not-an-authorized-rehearsal"
    config = tmp_path / "config.json"
    result = subprocess.run(
        [sys.executable, str(repo / "scripts/verify_a2_isolated_replay.py"), "--worker", str(root),
         str(config), mode, str(tmp_path / "tape.json")], cwd=repo,
        env={**os.environ, "HERMES_DATA_DIR": str(root), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode != 0
    assert "explicitly created isolated rehearsal root" in result.stderr
    assert not root.exists()


def test_rehearsal_refuses_output_outside_temp_before_running_workers(tmp_path):
    repo = Path(__file__).resolve().parents[3]
    output = repo / "this-report-must-not-be-created.json"
    result = subprocess.run(
        [sys.executable, str(repo / "scripts/verify_a2_isolated_replay.py"), "--output", str(output)],
        cwd=repo, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode != 0
    assert "new file under a temporary root" in result.stderr
    assert not output.exists()


def test_changed_broker_value_fails_even_when_market_input_hash_stays_equal(tmp_path):
    repo = Path(__file__).resolve().parents[3]
    report = tmp_path / "negative-replay.json"
    result = subprocess.run(
        [sys.executable, str(repo / "scripts/verify_a2_isolated_replay.py"), "--output", str(report),
         "--probe-net-liq-change"], cwd=repo,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    evidence = json.loads(report.read_text())
    assert evidence["status"] == "FAIL"
    assert evidence["input_hash_equal"] is True
    assert "payload" in evidence["strict_differences"]
    assert "artifact:hermes_state.sqlite" in evidence["strict_differences"]
    assert evidence["source_unchanged"] is True
    assert evidence["network_attempts"] == 0
