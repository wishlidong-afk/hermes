"""Offline real-writer r2 refusal and genuine new-as-of release continuity."""

from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIOR = Path("/Users/liweishi/Documents/New project/hermes-a2-final-gates-2026-11-04")
PRIOR_TOOL_SHA = "d3cf05c609caa56a0b36047f59ac3e6415c78fd86af15af91ec5435eff3c4b6c"
PRIVATE = ROOT / "private"
STEPS = (
    "old_r1",
    "old_r2",
    "candidate_blocked",
    "old_repeat",
    "new_date",
    "new_release_repeat",
)
NEW_DATE = "2026-06-01"
PREPARED_DIGEST = "08e37a470b7c6b6497aef56c828977b3925f04f0d5b2dd8050484de5343b36ac"
CANDIDATE_BINDING_SHA = (
    "1d7344b684529ea02e3289e8eae8bf017d1ce60344bc336c75f83b7f1e194086"
)


def load_prior():
    path = PRIOR / "a1_r1_transition.py"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == PRIOR_TOOL_SHA
    spec = importlib.util.spec_from_file_location("prior_r1", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


anchor = load_prior()
helper = load_prior()
helper.ROOT = ROOT
helper.PRIVATE = PRIVATE
helper.PACKAGES = {
    name: PRIVATE / "r6/releases" / release / "hermes_escape_top"
    for name, release in (
        ("old", "c1f4b8f_OFFLINE"),
        ("candidate", "candidate_ac025f0f_OFFLINE"),
        ("second", "candidate_ac025f0f_SECOND_OFFLINE"),
    )
}
PACKAGES = helper.PACKAGES


def output_bytes(path, content):
    relative = path.relative_to(ROOT)
    assert ".." not in relative.parts and not ROOT.is_symlink()
    for parent in (path.parent, *path.parents):
        if parent == ROOT.parent:
            break
        if parent.is_symlink():
            raise ValueError("tool output ancestor symlink is forbidden")
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
    ) as stream:
        stream.write(content)


def output_json(path, value):
    output_bytes(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def require_os_isolation():
    check = ctypes.CDLL("/usr/lib/libsandbox.dylib", use_errno=True).sandbox_check
    if check(os.getpid(), b"network-outbound", 0) != 1:
        raise RuntimeError("worker requires active OS network isolation")
    for path in (Path(__file__), ROOT / "source-binding-execution.json"):
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_NOFOLLOW)
        except PermissionError:
            continue
        else:
            os.close(descriptor)
            raise RuntimeError(
                "worker must not have write access to verification material"
            )


def verify_gate():
    assert not PRIVATE.is_symlink() and not ROOT.is_symlink()
    assert helper.sha(anchor.PACKET / "candidate-binding.json") == CANDIDATE_BINDING_SHA
    anchor.verify_gate()
    binding = json.loads((ROOT / "source-binding-execution.json").read_text())
    assert binding["helper_sha256"] == helper.sha(Path(__file__))
    materials = binding["prepared_artifacts"]
    assert len(materials) == 594
    assert (
        hashlib.sha256(
            json.dumps(materials, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        == PREPARED_DIGEST
    )
    expected_python = {name for name in materials if name.endswith(".py")}
    actual_python = {
        path.relative_to(PRIVATE).as_posix()
        for package in PACKAGES.values()
        for path in package.rglob("*.py")
    }
    assert expected_python == actual_python
    for relative, digest in binding["prepared_artifacts"].items():
        path = Path(relative)
        assert not path.is_absolute() and ".." not in path.parts
        assert helper.sha(PRIVATE / path) == digest, relative


def prepare():
    anchor.verify_gate()
    # Reuse the audited preparation, never its mutable audit/state or old results.
    original_packages = helper.PACKAGES
    helper.PACKAGES = {key: value for key, value in PACKAGES.items() if key != "second"}
    helper.prepare()
    helper.PACKAGES = original_packages
    shutil.copytree(PACKAGES["candidate"], PACKAGES["second"], symlinks=True)
    shutil.copy2(
        PACKAGES["candidate"].parent / "requirements.lock",
        PACKAGES["second"].parent / "requirements.lock",
    )
    (PACKAGES["second"].parent / "data").symlink_to(
        PRIVATE / "r6/data", target_is_directory=True
    )
    (PACKAGES["second"] / "VERSION").write_text(
        "OFFLINE_SECOND_RELEASE_ac025f0f OFFLINE_ONLY\n"
    )
    artifacts = {}
    for name, package in PACKAGES.items():
        original = anchor.BASELINE if name == "old" else anchor.CANDIDATE
        for path in sorted(package.rglob("*.py")):
            relative = path.relative_to(package)
            assert (
                path.read_bytes()
                == (original / "src/hermes_escape_top" / relative).read_bytes()
            )
            artifacts[path.relative_to(PRIVATE).as_posix()] = helper.sha(path)
        for relative in ("config/config.json", "governance/approved_live_config.json"):
            path = package / relative
            assert (
                path.read_bytes()
                == (original / "src/hermes_escape_top" / relative).read_bytes()
            )
            artifacts[path.relative_to(PRIVATE).as_posix()] = helper.sha(path)
        lock = package.parent / "requirements.lock"
        assert lock.read_bytes() == (original / "requirements.lock").read_bytes()
        for path in (lock, package / "VERSION"):
            artifacts[path.relative_to(PRIVATE).as_posix()] = helper.sha(path)
    helper.write(
        ROOT / "source-binding.json",
        {
            "helper_sha256": helper.sha(Path(__file__)),
            "prepared_artifacts": artifacts,
            "prior_helper_sha256": PRIOR_TOOL_SHA,
            "synthetic_only": True,
            "candidate_manifest": anchor.MANIFEST,
        },
    )
    print(json.dumps({"prepared_artifacts": len(artifacts), "synthetic_only": True}))


def package_for(step):
    return PACKAGES[
        "old"
        if step.startswith("old_")
        else "second"
        if step == "new_release_repeat"
        else "candidate"
    ]


def worker(step):
    require_os_isolation()
    verify_gate()
    helper.verify_launch(step)
    assert (PRIVATE / ".rehearsal").read_text() == "a1-r1-transition-v1\n"
    from datetime import datetime, timedelta
    from unittest.mock import patch
    from zoneinfo import ZoneInfo

    attempts = []

    def deny_network(event, _args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            attempts.append(event)
            raise RuntimeError("offline A1 boundary rehearsal forbids network")

    sys.addaudithook(deny_network)
    from hermes_escape_top import pipeline
    from hermes_escape_top.config import load_config, resolve_path
    from hermes_escape_top.core.data.decision_revision import DecisionRevisionConflict
    from hermes_escape_top.core.data.manifest import write_manifest
    from hermes_escape_top.ibkr import executions, positions

    assert Path(pipeline.__file__).resolve().parent == package_for(step)
    positions._SNAPSHOT_PATH = PRIVATE / "broker-caches/positions.json"
    executions._CACHE_PATH = PRIVATE / "broker-caches/executions.json"
    config = load_config()
    archive = resolve_path(config, "archive_dir")
    assert archive.resolve() == PRIVATE / "r6/shared/hermes_escape_top/data/archive"
    as_of = NEW_DATE if step in {"new_date", "new_release_repeat"} else anchor.AS_OF
    mutation = None
    if step == "old_r2":
        history = resolve_path(config, "history_dir") / "SOXL.csv"
        assert not history.is_symlink()
        assert (
            history.resolve(strict=True)
            == PRIVATE / "r6/shared/hermes_escape_top/data/history/SOXL.csv"
        )
        before_sha = helper.sha(history)
        with history.open(newline="") as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames
            assert fields is not None
            rows = list(reader)
        assert {"date", "open", "high", "low", "close", "adj_close"} <= set(fields)
        matches = [row for row in rows if row["date"][:10] == anchor.AS_OF]
        assert len(matches) == 1
        previous = dict(matches[0])
        for key in ("open", "high", "low", "close", "adj_close"):
            matches[0][key] = str(float(matches[0][key]) * 1.025)
        with history.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        mutation = {
            "before": previous,
            "after": matches[0],
            "before_sha256": before_sha,
            "after_sha256": helper.sha(history),
            "scope": "private fixture only",
        }
        assert mutation["before_sha256"] != mutation["after_sha256"]
    if step in {"old_r1", "old_r2"}:
        write_manifest(
            resolve_path(config, "history_dir"), archive / "data_manifest_latest.json"
        )
    business = (*anchor.BUSINESS[:-1], f"soft_adapter_snapshot_{as_of}.json")
    before = {
        name: helper.sha(archive / name) if (archive / name).is_file() else None
        for name in business
    }
    audit_before = (
        (archive / "audit_log.jsonl").read_bytes()
        if (archive / "audit_log.jsonl").exists()
        else b""
    )
    instant = datetime(2026, 6, 3, 7, 10, tzinfo=ZoneInfo("Asia/Shanghai")) + timedelta(
        minutes=STEPS.index(step)
    )

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    payload, error = None, None
    with patch.object(pipeline, "datetime", Clock):
        try:
            payload = pipeline.score_pipeline(
                as_of,
                include_ibkr=False,
                run_type="scheduled",
                market_admission_status={
                    "operation_id": "SYNTHETIC_" + step,
                    "completed_through": as_of,
                },
            )
        except DecisionRevisionConflict as exc:
            error = str(exc)
    after = {
        name: helper.sha(archive / name) if (archive / name).is_file() else None
        for name in business
    }
    assert not attempts and not list((PRIVATE / "broker-caches").iterdir())
    assert not (archive / ".score_run_transactions/active.json").exists()
    audit_after = (archive / "audit_log.jsonl").read_bytes()
    assert audit_after.startswith(audit_before)
    report = {
        "step": step,
        "as_of": as_of,
        "pid": os.getpid(),
        "error": error,
        "before": before,
        "after": after,
        "mutation": mutation,
        "network_attempts": len(attempts),
        "broker_cache_files": 0,
        "audit_prefix_unchanged": True,
        "audit_before_sha256": hashlib.sha256(audit_before).hexdigest(),
        "audit_before_bytes": len(audit_before),
        "audit_after_sha256": hashlib.sha256(audit_after).hexdigest(),
    }
    if step == "candidate_blocked":
        assert payload is None and error and "revision budget exhausted" in error
        assert before == after and len(before) == 7
        assert audit_before == audit_after
    else:
        assert payload is not None and error is None
        evidence = payload["decision_evidence"]
        assert evidence["bar_finality"] == "FINAL"
        assert evidence["identity_schema_version"] == "hermes-decision-identity-v2"
        journal = json.loads(
            (
                archive
                / f".score_run_transactions/runs/{payload['persistence']['run_id']}/manifest.json"
            ).read_text()
        )
        assert journal["status"] == "COMMITTED" and len(journal["artifacts"]) == 7
        report.update(
            decision_evidence=evidence,
            input_hash=payload["input_hash"],
            transaction_status="COMMITTED",
        )
    output_json(ROOT / (step + ".json"), report)


def postcheck():
    reports = [json.loads((ROOT / (step + ".json")).read_text()) for step in STEPS]
    assert len({row["pid"] for row in reports}) == len(STEPS)
    successful = [row for row in reports if row["error"] is None]
    assert [row["decision_evidence"]["decision_revision"] for row in successful] == [
        1,
        2,
        2,
        1,
        1,
    ]
    evidence = [row["decision_evidence"] for row in successful]
    assert evidence[0]["semantic_hash"] != evidence[1]["semantic_hash"]
    assert evidence[1]["decision_id"] == evidence[2]["decision_id"]
    for item in evidence[1:3]:
        assert item["supersedes_decision_id"] == evidence[0]["decision_id"]
        assert item["previous_decision_hash"] == evidence[0]["decision_hash"]
    assert evidence[3]["decision_id"] == evidence[4]["decision_id"]
    assert evidence[3]["semantic_hash"] == evidence[4]["semantic_hash"]
    assert evidence[3]["as_of"] == NEW_DATE != evidence[2]["as_of"]
    assert evidence[3]["scorer_release_hash"] != evidence[4]["scorer_release_hash"]
    for item in evidence[3:]:
        assert item["previous_decision_hash"] is None
        assert item["supersedes_decision_id"] is None
    archive = PRIVATE / "r6/shared/hermes_escape_top/data/archive"
    audit = [
        json.loads(line)["payload"]
        for line in (archive / "audit_log.jsonl").read_text().splitlines()
        if line.strip()
    ]
    with sqlite3.connect(
        (archive / "hermes_state.sqlite").as_uri() + "?mode=ro", uri=True
    ) as connection:
        state = [
            json.loads(row[0])
            for row in connection.execute(
                "SELECT payload_json FROM score_runs ORDER BY id"
            )
        ]
    assert len(audit) == len(state) == len(successful) == 5
    for row, audit_row, state_row in zip(successful, audit, state, strict=True):
        assert (
            row["decision_evidence"]
            == audit_row["decision_evidence"]
            == state_row["decision_evidence"]
        )
        assert row["input_hash"] == audit_row["input_hash"] == state_row["input_hash"]
        assert row["decision_evidence"]["revision_budget"] == 2
        assert "identity_migration" not in row["decision_evidence"]
    assert reports[2]["before"] == reports[2]["after"]
    verify_gate()
    output_json(
        ROOT / "summary.json",
        {
            "status": "PASS",
            "successful_revisions": [1, 2, 2, 1, 1],
            "old_r2_candidate_refused": True,
            "seven_artifacts_unchanged_on_refusal": True,
            "old_r2_remains_repeatable": True,
            "genuine_new_business_as_of": NEW_DATE,
            "new_date_cross_release_r1_stable": True,
            "old_audit_prefix_preserved": True,
            "audit_state_report_equal": True,
            "audit_rows": 5,
            "synthetic_only": True,
            "capture_inputs": False,
            "transaction_protocol": "v1",
            "helper_sha256": helper.sha(Path(__file__)),
            "DEPLOY": "HOLD",
            "A2": "OPEN",
            "Phase_B": "NOT_STARTED",
            "not_proved": [
                "v2 active pointer rollback",
                "actual live config/data release proof",
                "natural observation",
                "deployment",
            ],
        },
    )


def run():
    verify_gate()
    for step in STEPS:
        for suffix in (".json", ".stdout.log", ".stderr.log"):
            path = ROOT / (step + suffix)
            assert not path.exists() and not path.is_symlink(), (
                "never overwrite an output or follow a link"
            )
    for step in STEPS:
        profile = "(version 1) (allow default) (deny network*) (deny file-write*) "
        for path in (
            PRIVATE / "r6/shared/hermes_escape_top/data",
            PRIVATE / "tmp",
            PRIVATE / "broker-caches",
        ):
            profile += f'(allow file-write* (subpath "{path}")) '
        profile += f'(allow file-write* (literal "{ROOT / (step + ".json")}" ) (literal "/dev/null")) '
        profile += '(deny file-read* (subpath "/Users/liweishi/.hermes"))'
        token = os.urandom(32).hex()
        launch = PRIVATE / ".launch.json"
        assert not PRIVATE.is_symlink()
        if launch.exists() or launch.is_symlink():
            assert not launch.is_symlink() and launch.is_file()
            launch.unlink()
        output_json(
            PRIVATE / ".launch.json",
            {"parent_pid": os.getpid(), "step": step, "token": token},
        )
        (PRIVATE / ".launch.json").chmod(0o600)
        env = {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(PRIVATE / "home"),
            "TMPDIR": str(PRIVATE / "tmp"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(package_for(step).parent),
            "HERMES_DATA_DIR": str(package_for(step)),
            "HERMES_A1_PRIVATE_LAUNCH_TOKEN": token,
        }
        result = subprocess.run(
            [
                "/usr/bin/sandbox-exec",
                "-p",
                profile,
                str(anchor.PYTHON),
                "-B",
                __file__,
                "worker",
                step,
            ],
            cwd=PRIVATE,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        output_bytes(ROOT / (step + ".stdout.log"), result.stdout.encode())
        output_bytes(ROOT / (step + ".stderr.log"), result.stderr.encode())
        assert result.returncode == 0, result.stderr[-5000:]
        print(step + ": verified", flush=True)
    postcheck()
    print((ROOT / "summary.json").read_text())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "worker", "run"))
    parser.add_argument("step", nargs="?", choices=STEPS)
    args = parser.parse_args()
    if (args.mode == "worker") != (args.step is not None):
        parser.error("only worker mode requires a step")
    {"prepare": prepare, "run": run, "worker": lambda: worker(args.step)}[args.mode]()
