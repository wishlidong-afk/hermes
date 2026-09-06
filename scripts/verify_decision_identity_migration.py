#!/usr/bin/env python3
"""Replay actual v1/v2 writers and rollback against disposable, offline roots."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-source", type=Path, required=True)
    parser.add_argument("--candidate-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    baseline, candidate = args.baseline_source.resolve(), args.candidate_source.resolve()
    tests = candidate / "src/hermes_escape_top/tests"
    sys.path[:0] = [str(candidate / "src"), str(tests)]
    from conftest import PACKAGE_DATA, TEST_DATA, _tracked_package_files
    from test_pipeline_transaction import BUSINESS_ARTIFACTS

    worker = tests / "test_scheduled_revision_sequence.py"
    cases = {}
    with tempfile.TemporaryDirectory(prefix="hermes-a1-real-v1-migration-") as temporary:
        for prior_revision, sequence in (
            (1, ((baseline, 30), (candidate, 31), (candidate, 1))),
            (2, ((baseline, 30), (baseline, 31), (candidate, 1), (candidate, 2))),
        ):
            root = Path(temporary) / f"v1-r{prior_revision}"
            for src in _tracked_package_files():
                if src.name == "audit_log.jsonl":
                    continue
                dst = root / "data" / src.relative_to(PACKAGE_DATA)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            shutil.copytree(TEST_DATA, root / "data", dirs_exist_ok=True)
            results = []
            for source, day in sequence:
                env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "HERMES_DATA_DIR": str(root),
                       "PYTHONPATH": f"{source}/src:{tests}"}
                child = subprocess.run(
                    [sys.executable, str(worker), str(root), str(day), "hold"],
                    cwd=source, env=env, text=True, capture_output=True, timeout=90,
                )
                if child.returncode:
                    raise RuntimeError(child.stderr)
                result = json.loads((root / f"result-{day}.json").read_text())
                result["source"] = str(source)
                results.append(result)
            assert results[-1]["decision_evidence"]["decision_revision"] == 2
            assert results[-1]["decision_evidence"]["decision_id"] == results[-2]["decision_evidence"]["decision_id"]
            assert all(row["transaction_artifacts"] == 7 and row["transaction_status"] == "COMMITTED"
                       and row["state_matches_audit"] for row in results)
            archive = root / "data/archive"
            before = {name: hashlib.sha256((archive / name).read_bytes()).hexdigest()
                      for name in BUSINESS_ARTIFACTS}
            env["PYTHONPATH"] = f"{baseline}/src:{tests}"
            rollback = subprocess.run(
                [sys.executable, str(worker), str(root), "3", "hold"],
                cwd=baseline, env=env, text=True, capture_output=True, timeout=90,
            )
            assert rollback.returncode != 0 and "revision budget exhausted" in rollback.stderr
            after = {name: hashlib.sha256((archive / name).read_bytes()).hexdigest()
                     for name in BUSINESS_ARTIFACTS}
            assert before == after
            cases[f"v1_r{prior_revision}_to_v2"] = {
                "runs": results, "rollback_writer": "FAIL_CLOSED_WITHOUT_LEGACY_RESET",
                "seven_artifacts_before_rollback": before, "seven_artifacts_after_rollback": after,
            }
    report = {
        "status": "PASS", "network_used": False, "live_written": False,
        "inputs": "tracked seed plus test fixtures; unchanged complete history for v1 proof",
        "baseline_source": str(baseline), "candidate_source": str(candidate),
        "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps({"status": "PASS", "output": str(args.output)}))


if __name__ == "__main__":
    main()
