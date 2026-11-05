"""Narrow offline R6 r1 -> candidate r2 -> old-writer rejection rehearsal."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT / "a1-r1-private-final"
CANDIDATE = Path("/Users/liweishi/Documents/New project/hermes-a2-postcommit-health-2026-11-04/candidate")
BASELINE = Path("/Users/liweishi/Documents/New project/hermes-a2-integration-2026-11-04/live")
PYTHON = Path("/Users/liweishi/Documents/New project/hermes-a2-integration-2026-11-04/venv/bin/python")
AS_OF = "2026-05-29"
STEPS = ("old_r1", "candidate_r2", "candidate_repeat", "old_rollback")
PACKAGES = {name: PRIVATE / "r6/releases" / release / "hermes_escape_top" for name, release in (
    ("old", "c1f4b8f_OFFLINE"), ("candidate", "candidate_ac025f0f_OFFLINE"),
)}
BUSINESS = ("audit_log.jsonl", "hermes_state.sqlite", "reentry_state.sqlite", "mirror_reference.sqlite",
            "flow_reference.sqlite", "signal_journal.jsonl", f"soft_adapter_snapshot_{AS_OF}.json")
MANIFEST = "90842a116706bb48fa17f1b2c207649252073ac074db7f8110d0b87d775448aa"
PACKET = Path("/Users/liweishi/Documents/github/hermes/building/reports/a2_postcommit_health/2026-11-04")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def verify_gate():
    records = ROOT / "verification-runs.json"
    if not records.is_file() or not any(
        row["stage"] == "full-suite" and row["exit_code"] == 0 and row["source_unchanged"]
        and row["source_manifest_sha256"] == MANIFEST and row["bound_source_files"] == 512
        for row in json.loads(records.read_text())
    ):
        raise RuntimeError("the exact frozen candidate full-suite gate is not satisfied")
    binding = json.loads((PACKET / "candidate-binding.json").read_text())
    assert binding["manifest_sha256"] == MANIFEST
    assert all(sha(CANDIDATE / name) == digest for name, digest in binding["files"].items())
    prepared = json.loads((ROOT / "a1-r1-source-binding-final.json").read_text())
    assert prepared["status"] == "PASS" and prepared["helper_sha256"] == sha(Path(__file__))
    for name, digest in prepared["prepared_artifacts"].items():
        relative = Path(name)
        assert not relative.is_absolute() and ".." not in relative.parts
        assert sha(PRIVATE / relative) == digest, name


def verify_launch(step):
    launch = json.loads((PRIVATE / ".launch.json").read_text())
    if (launch["parent_pid"] != os.getppid() or launch["step"] != step
            or launch["token"] != os.environ.get("HERMES_A1_PRIVATE_LAUNCH_TOKEN")):
        raise RuntimeError("worker requires its controlled rehearsal parent")


def prepare():
    assert not PRIVATE.exists(), "never overwrite an earlier rehearsal"
    PRIVATE.mkdir(mode=0o700)
    (PRIVATE / ".rehearsal").write_text("a1-r1-transition-v1\n")
    for name in ("home", "tmp", "broker-caches"):
        (PRIVATE / name).mkdir(mode=0o700)
    data = PRIVATE / "r6/shared/hermes_escape_top/data"
    data.mkdir(parents=True)
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    tracked = subprocess.check_output(["git", "-C", str(CANDIDATE), "ls-files", "-z", "--",
                                       "src/hermes_escape_top/data"], env=env).decode().split("\0")
    for name in filter(None, tracked):
        path = CANDIDATE / name
        relative = path.relative_to(CANDIDATE / "src/hermes_escape_top/data")
        if relative.parent.name == "archive" and relative.name == "audit_log.jsonl":
            continue
        target = data / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    shutil.copytree(CANDIDATE / "src/hermes_escape_top/tests/fixtures/data", data, dirs_exist_ok=True)
    (data / "valuation_snapshot.json").unlink(missing_ok=True)
    valuation = PRIVATE / "r6/data"
    valuation.mkdir()
    write(valuation / "valuation_snapshot.json", {"items": {
        "FNGS": {"forward_pe_percentile": 50.0}, "SOXX": {"forward_pe_percentile": 50.0},
        "MSTR": {"mnav_premium_percentile": 50.0},
    }})
    bindings = {}
    for name, source in (("old", BASELINE), ("candidate", CANDIDATE)):
        package = PACKAGES[name]
        package.mkdir(parents=True)
        hashes = {}
        source_package = source / "src/hermes_escape_top"
        for path in sorted(source_package.rglob("*.py")):
            relative = path.relative_to(source_package)
            if relative.parts[0] in {"tests", "data"} or "__pycache__" in relative.parts:
                continue
            target = package / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            hashes[relative.as_posix()] = sha(target)
        for relative in ("config/config.json", "governance/approved_live_config.json"):
            target = package / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_package / relative, target)
        shutil.copy2(source / "requirements.lock", package.parent / "requirements.lock")
        (package / "VERSION").write_text(("c1f4b8f" if name == "old" else "OFFLINE_CANDIDATE_ac025f0f") + " OFFLINE_ONLY\n")
        (package / "data").symlink_to(data, target_is_directory=True)
        (package.parent / "data").symlink_to(valuation, target_is_directory=True)
        assert (package / "core/data/decision_identity.py").is_file()
        bindings[name] = {"source": str(source), "python_files": hashes,
                          "config_sha256": sha(package / "config/config.json"),
                          "lock_sha256": sha(package.parent / "requirements.lock")}
    assert bindings["old"]["config_sha256"] == bindings["candidate"]["config_sha256"]
    write(ROOT / "a1-r1-preparation-final.json", {"sources": bindings, "as_of": AS_OF,
          "seed": "tracked package data plus test fixtures and synthetic valuation 50; no live capture",
          "synthetic_only": True, "helper_sha256": sha(Path(__file__))})


def worker(step):
    verify_gate()
    verify_launch(step)
    if (PRIVATE / ".rehearsal").read_text() != "a1-r1-transition-v1\n":
        raise ValueError("worker requires its explicitly prepared private root")
    from datetime import datetime, timedelta
    from unittest.mock import patch
    from zoneinfo import ZoneInfo

    attempts = []

    def deny_network(event, _args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            attempts.append(event)
            raise RuntimeError("offline A1 rehearsal forbids network")

    sys.addaudithook(deny_network)
    from hermes_escape_top import pipeline
    from hermes_escape_top.config import load_config, resolve_path
    from hermes_escape_top.core.data.decision_identity import decision_outputs, scoring_logic_hash
    from hermes_escape_top.core.data.decision_revision import DecisionRevisionConflict
    from hermes_escape_top.core.data.manifest import write_manifest
    from hermes_escape_top.ibkr import positions, executions

    package = Path(pipeline.__file__).resolve().parent
    expected = PACKAGES["old" if step in {"old_r1", "old_rollback"} else "candidate"]
    assert package == expected
    positions._SNAPSHOT_PATH = PRIVATE / "broker-caches/positions.json"
    executions._CACHE_PATH = PRIVATE / "broker-caches/executions.json"
    config = load_config()
    archive = resolve_path(config, "archive_dir")
    assert archive.resolve() == PRIVATE / "r6/shared/hermes_escape_top/data/archive"
    if step == "old_r1":
        write_manifest(resolve_path(config, "history_dir"), archive / "data_manifest_latest.json")
    before = {name: sha(archive / name) if (archive / name).is_file() else None for name in BUSINESS}
    instant = datetime(2026, 5, 31, 7, 10, tzinfo=ZoneInfo("Asia/Shanghai")) + timedelta(minutes=STEPS.index(step))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    payload, error = None, None
    with patch.object(pipeline, "datetime", Clock):
        try:
            payload = pipeline.score_pipeline(AS_OF, include_ibkr=False, run_type="scheduled",
                                              market_admission_status={"operation_id": "SYNTHETIC_" + step,
                                                                       "completed_through": AS_OF})
        except DecisionRevisionConflict as exc:
            error = str(exc)
    after = {name: sha(archive / name) if (archive / name).is_file() else None for name in BUSINESS}
    assert not attempts and not list((PRIVATE / "broker-caches").iterdir())
    assert not (archive / ".score_run_transactions/active.json").exists()
    report = {"step": step, "pid": os.getpid(), "error": error, "scoring_logic_hash": scoring_logic_hash(package),
              "network_attempts": len(attempts), "broker_cache_files": 0, "before": before, "after": after}
    if step == "old_rollback":
        assert payload is None and error and "revision budget exhausted" in error
        assert before == after
    else:
        assert error is None and payload is not None
        evidence = payload["decision_evidence"]
        assert evidence["identity_schema_version"] == "hermes-decision-identity-v2"
        assert evidence["bar_finality"] == "FINAL"
        journal = archive / f".score_run_transactions/runs/{payload['persistence']['run_id']}/manifest.json"
        record = json.loads(journal.read_text())
        assert record["status"] == "COMMITTED" and len(record["artifacts"]) == 7
        report.update(decision_evidence=evidence, decision_outputs=decision_outputs(payload),
                      input_hash=payload["input_hash"], transaction_status=record["status"])
    write(ROOT / ("a1-r1-" + step + ".json"), report)


def run():
    verify_gate()
    assert not (ROOT / "a1-r1-summary.json").exists(), "never overwrite a completed rehearsal"
    results = []
    profile = '(version 1) (allow default) (deny network*) (deny file-write*) '
    profile += f'(allow file-write* (subpath "{ROOT}") (literal "/dev/null")) '
    profile += '(deny file-read* (subpath "/Users/liweishi/.hermes"))'
    for step in STEPS:
        package = PACKAGES["old" if step in {"old_r1", "old_rollback"} else "candidate"]
        token = os.urandom(32).hex()
        write(PRIVATE / ".launch.json", {"parent_pid": os.getpid(), "step": step, "token": token})
        (PRIVATE / ".launch.json").chmod(0o600)
        env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(PRIVATE / "home"),
               "TMPDIR": str(PRIVATE / "tmp"), "PYTHONDONTWRITEBYTECODE": "1",
               "PYTHONPATH": str(package.parent), "HERMES_DATA_DIR": str(package),
               "HERMES_A1_PRIVATE_LAUNCH_TOKEN": token}
        result = subprocess.run(["/usr/bin/sandbox-exec", "-p", profile, str(PYTHON), "-B", __file__, "worker", step],
                                cwd=PRIVATE, env=env, capture_output=True, text=True, timeout=180)
        (ROOT / ("a1-r1-" + step + ".stdout.log")).write_text(result.stdout)
        (ROOT / ("a1-r1-" + step + ".stderr.log")).write_text(result.stderr)
        assert result.returncode == 0, result.stderr[-4000:]
        results.append(json.loads((ROOT / ("a1-r1-" + step + ".json")).read_text()))
    assert [row["decision_evidence"]["decision_revision"] for row in results[:3]] == [1, 2, 2]
    assert results[1]["decision_evidence"]["decision_id"] == results[2]["decision_evidence"]["decision_id"]
    assert len({row["pid"] for row in results}) == 4
    write(ROOT / "a1-r1-summary.json", {"status": "PASS", "synthetic_only": True, "revisions": [1, 2, 2],
          "old_writer": "FAIL_CLOSED_REVISION_BUDGET_SEVEN_ARTIFACTS_UNCHANGED", "helper_sha256": sha(Path(__file__)),
          "not_proved": ["old r2 transition", "new business date", "v2 active pointer recovery", "natural observation", "deployment"]})
    print((ROOT / "a1-r1-summary.json").read_text())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "worker", "run"))
    parser.add_argument("step", nargs="?", choices=STEPS)
    args = parser.parse_args()
    if (args.mode == "worker") != (args.step is not None):
        parser.error("only worker mode requires a step")
    if args.mode == "prepare":
        prepare()
    elif args.mode == "worker":
        worker(args.step)
    else:
        run()
