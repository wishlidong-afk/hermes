"""CI shards must execute an exact, disjoint partition of collected tests."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[3]


def _run_shard(root, index, count=2, *extra):
    output = root / f"shard-{index}.json"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--rootdir", str(root), "-q",
         "-p", "no:cacheprovider", "-p", "ci_shards", "--ci-shard-index", str(index),
         "--ci-shard-count", str(count), "--ci-shard-report", str(output), *extra],
        cwd=root, capture_output=True, text=True, timeout=30,
        env={**os.environ, "PYTHONPATH": str(REPO / "scripts"),
             "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return result, output


def _verify(root, count=2):
    return subprocess.run(
        [sys.executable, str(REPO / "scripts/ci_shards.py"), "--count", str(count),
         "--inventory", str(root / "inventory.json"), str(root)],
        cwd=root, capture_output=True, text=True, timeout=10,
    )


def test_real_shards_execute_all_tests_once_and_verify_their_union(tmp_path):
    (tmp_path / "test_sample.py").write_text(
        "import pytest\n@pytest.mark.parametrize('n', range(9))\ndef test_case(n): assert n >= 0\n"
    )
    inventory, path = _run_shard(tmp_path, 0, 1, "--collect-only")
    assert inventory.returncode == 0, inventory.stdout + inventory.stderr
    path.rename(tmp_path / "inventory.json")
    reports = []
    for index in range(2):
        result, path = _run_shard(tmp_path, index)
        assert result.returncode == 0, result.stdout + result.stderr
        reports.append(json.loads(path.read_text()))
    result = _verify(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["tests"] == 9
    assert set(reports[0]["selected"]).isdisjoint(reports[1]["selected"])
    assert len(reports[0]["selected"]) + len(reports[1]["selected"]) == 9


def test_repeated_test_call_cannot_be_counted_as_one_execution(tmp_path):
    test_real_shards_execute_all_tests_once_and_verify_their_union(tmp_path)
    path = tmp_path / "shard-0.json"
    report = json.loads(path.read_text())
    report["phases"].append(next(p for p in report["phases"] if p["when"] == "call"))
    path.write_text(json.dumps(report))
    assert _verify(tmp_path).returncode == 1


@pytest.mark.parametrize("damage", [
    "missing_report", "extra_report", "duplicate_index", "different_collection",
    "different_revision", "different_tool", "wrong_selection", "failed_exit",
    "collect_only", "missing_teardown", "failed_phase", "foreign_test",
    "invalid_json", "incomplete_inventory", "different_run", "different_attempt",
])
def test_incomplete_or_conflicting_shards_fail_closed(tmp_path, damage):
    test_real_shards_execute_all_tests_once_and_verify_their_union(tmp_path)
    path = tmp_path / "shard-0.json"
    row = json.loads(path.read_text())
    if damage == "missing_report":
        path.unlink()
    elif damage == "extra_report":
        (tmp_path / "shard-extra.json").write_text(json.dumps(row))
    elif damage == "invalid_json":
        path.write_text("{")
    elif damage == "incomplete_inventory":
        inventory = tmp_path / "inventory.json"
        data = json.loads(inventory.read_text())
        data["collected"].pop()
        inventory.write_text(json.dumps(data))
    else:
        if damage == "duplicate_index":
            row["index"] = 1
        elif damage == "different_collection":
            row["collected"].pop()
        elif damage == "different_revision":
            row["revision"] = "different"
        elif damage == "different_tool":
            row["tool_sha256"] = "0" * 64
        elif damage == "different_run":
            row["run"] = "different"
        elif damage == "different_attempt":
            row["attempt"] = "different"
        elif damage == "wrong_selection":
            row["selected"].pop()
        elif damage == "failed_exit":
            row["exit_code"] = 1
        elif damage == "collect_only":
            row["collect_only"] = True
        elif damage == "missing_teardown":
            row["phases"].pop()
        elif damage == "failed_phase":
            row["phases"][0]["outcome"] = "failed"
        elif damage == "foreign_test":
            row["phases"][0]["nodeid"] = "not-selected"
        path.write_text(json.dumps(row))
    result = _verify(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "CI completeness FAIL" in result.stderr


@pytest.mark.parametrize("index,count", [(-1, 2), (2, 2), (0, 0)])
def test_invalid_partition_is_rejected_before_running_tests(tmp_path, index, count):
    (tmp_path / "test_sample.py").write_text("def test_case(): raise AssertionError('must not run')\n")
    result, output = _run_shard(tmp_path, index, count)
    assert result.returncode == 4
    assert not output.exists()


def test_real_assertion_failure_cannot_pass_the_aggregate(tmp_path):
    (tmp_path / "test_sample.py").write_text("def test_case(): assert False\n")
    result, path = _run_shard(tmp_path, 0, 1, "--collect-only")
    assert result.returncode == 0
    path.rename(tmp_path / "inventory.json")
    result, path = _run_shard(tmp_path, 0, 1)
    assert result.returncode == 1
    assert json.loads(path.read_text())["exit_code"] == 1
    assert _verify(tmp_path, 1).returncode == 1


def test_legitimate_pytest_skip_remains_visible_not_fabricated_as_pass(tmp_path):
    (tmp_path / "test_sample.py").write_text(
        "import pytest\n@pytest.mark.skip(reason='explicit fixture')\ndef test_case(): assert False\n"
    )
    result, path = _run_shard(tmp_path, 0, 1, "--collect-only")
    assert result.returncode == 0
    path.rename(tmp_path / "inventory.json")
    result, _path = _run_shard(tmp_path, 0, 1)
    assert result.returncode == 0
    result = _verify(tmp_path, 1)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["skipped_phases"] == 1


def test_legitimate_teardown_skip_preserves_pytest_success_and_is_reported(tmp_path):
    (tmp_path / "test_sample.py").write_text(
        "import pytest\n@pytest.fixture\ndef cleanup():\n    yield\n"
        "    pytest.skip('explicit teardown skip')\ndef test_case(cleanup): assert True\n"
    )
    result, path = _run_shard(tmp_path, 0, 1, "--collect-only")
    assert result.returncode == 0
    path.rename(tmp_path / "inventory.json")
    result, _path = _run_shard(tmp_path, 0, 1)
    assert result.returncode == 0
    result = _verify(tmp_path, 1)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["skipped_phases"] == 1


def test_workflow_preserves_independent_gates_and_requires_every_shard():
    workflow = (REPO / ".github/workflows/ci.yml").read_text()
    tests, remainder = workflow.split("\n  checks:\n")
    checks, aggregate = remainder.split("\n  verify:\n")
    assert "shard: [0, 1, 2, 3, 4, 5, 6, 7]" in tests
    assert "fail-fast: false" in tests
    assert "--ci-shard-count 8" in tests
    assert "--durations=25" in tests and "--junitxml=" in tests
    assert "needs:" not in checks
    for command in ("--collect-only", "python -m ruff check", "python -m mypy",
                    "python -m pip_audit -r requirements.lock", "check_governance_consistency.py",
                    "python -m compileall"):
        assert command in checks
    assert checks.count("if: ${{ !cancelled() }}") == 4
    assert "needs: [test-shards, checks]" in aggregate
    assert 'test "$TEST_RESULT" = success' in aggregate
    assert 'test "$CHECKS_RESULT" = success' in aggregate
    assert "--count 8 --inventory ci-results/inventory.json" in aggregate
    assert "pattern: ci-*-attempt-${{ github.run_attempt }}" in aggregate
    assert '"Re-run all jobs"' in workflow
    assert workflow.count("timeout-minutes: 20") == 3
    assert "continue-on-error" not in workflow
