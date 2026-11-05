"""Publish diagnostic JSON/logs only, with previous source and Git preservation."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAIN = Path("/Users/liweishi/Documents/github/hermes")
SOURCE = Path("/Users/liweishi/Documents/New project/hermes-a2-postcommit-health-2026-11-04")
INITIAL = Path("/Users/liweishi/Documents/New project/hermes-a1-v2-rollback-2026-11-04")
OUTPUT = MAIN / "building/reports/a1_v2_rollback/2026-11-04"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    with path.open("x") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


binding = read(MAIN / "building/reports/a2_postcommit_health/2026-11-04/candidate-binding.json")
assert all(sha(SOURCE / "candidate" / name) == digest for name, digest in binding["files"].items())
original = read(SOURCE / "preservation-before.json")
assert all(sha(MAIN / name) == digest for name, digest in original["main_files"].items())
env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
for value in original["git"].values():
    repo = Path(value["root"])
    assert (
        subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], env=env, text=True).strip()
        == value["head"]
    )
    assert sha(repo / ".git/index") == value["index_sha256"]
    assert sha(repo / ".git/config") == value["config_sha256"]
protected = {
    "a2_postcommit_health": "958ed44498c80000501fa7d8767866dca13bb1bfa43c9d1f7c112f84c82c6267",
    "a2_final_gates": "e171778ffb5198da45f4b8d53c8fbbfa84e26ac83558e44e6ce738189ac386cb",
    "a2_a1_boundaries": "91e97ee8a83f13f99a23d510af7ce34da4022323c0e50a128a0c793e2c134204",
}
for name, expected in protected.items():
    packet = MAIN / "building/reports" / name / "2026-11-04"
    assert sha(packet / "SHA256SUMS.json") == expected
    assert all(sha(packet / file) == digest for file, digest in read(packet / "SHA256SUMS.json")["files"].items())
assert read(ROOT / "postcheck.json")["status"] == "PASS"
runs = read(ROOT / "verification-runs.json")
for stage in ("tool-guards", "v2-rollback-matrix", "independent-postcheck", "tools-ruff-final", "tools-mypy-final"):
    row = next(row for row in runs if row["stage"] == stage)
    assert row["exit_code"] == 0 and row["source_unchanged"], stage
packet = ROOT / "packet"
packet.mkdir()
(packet / "tools").mkdir()
(packet / "logs").mkdir()
(packet / "before").mkdir()
for name in ("verify_v2_rollback.py", "postcheck.py", "check_guards.py", "run.py", "publish.py"):
    shutil.copy2(ROOT / name, packet / "tools" / name)
for name in ("postcheck.json", "guards.json", "tool-binding.json", "verification-runs.json", "internal-review.json"):
    shutil.copy2(ROOT / name, packet / name)
for row in runs:
    shutil.copy2(ROOT / row["log"], packet / "logs" / row["log"])
shutil.copy2(INITIAL / "verify_v2_rollback.py", packet / "before/verify_v2_rollback.py")
shutil.copy2(INITIAL / "postcheck.json", packet / "before/postcheck.json")
shutil.copy2(INITIAL / "v2-rollback-matrix.log", packet / "before/v2-rollback-matrix.log")
materials = {}
for case in ("pending", "committed_active", "committed_clean"):
    source = ROOT / "cases" / case
    target = packet / "cases" / case
    target.mkdir(parents=True)
    prepared = read(source / "source-binding-execution.json")
    assert len(prepared["prepared_artifacts"]) == 594
    assert all(sha(source / "private" / name) == digest for name, digest in prepared["prepared_artifacts"].items())
    assert prepared["helper_sha256"] == sha(source / "verify_boundaries.py")
    materials[case] = len(prepared["prepared_artifacts"])
    for path in source.iterdir():
        if path.is_file() and path.suffix in {".json", ".log", ".py"}:
            shutil.copy2(path, target / path.name)
write(
    packet / "preservation.json",
    {
        "frozen_candidate_files_unchanged": len(binding["files"]),
        "original_main_files_unchanged": len(original["main_files"]),
        "original_git_head_index_config_unchanged": True,
        "prepared_materials_per_case": materials,
        "prior_packet_manifests": protected,
        "live_written": False,
    },
)
write(
    packet / "reuse-and-boundary.json",
    {
        "full_suite": "2288 passed reused from unchanged source/environment, not rerun",
        "candidate_manifest": binding["manifest_sha256"],
        "candidate_logic": "ac025f0f93d16ee3b97e1aaa8f7e70b49801032d81085453b7e5531eae8e7dad",
        "final_driver_sha256": sha(ROOT / "verify_v2_rollback.py"),
        "synthetic_only": True,
        "completed": [
            "v2 PENDING rollback and old r1 repeat",
            "COMMITTED stale pointer cleanup without rewind",
            "cleaned COMMITTED old writer reaches revision-budget refusal",
        ],
        "not_proved": [
            "power-loss durability",
            "IBKR/cache execution paths",
            "actual live config/data-bound release proof",
            "final integrated external audit",
            "Git/CI",
            "deployment",
            "natural ON/v2 observations",
            "A1/A2 closure",
        ],
        "limitations": (
            "Controlled local roots, local hashes are not signatures; "
            "not a same-user/concurrent ancestor replacement security boundary"
        ),
        "DEPLOY": "HOLD",
        "A2": "OPEN",
        "Phase_B": "NOT_STARTED",
    },
)
files = {path.relative_to(packet).as_posix(): sha(path) for path in sorted(packet.rglob("*")) if path.is_file()}
write(packet / "SHA256SUMS.json", {"schema_version": "hermes-a1-v2-rollback-evidence-v1", "files": files})
assert not OUTPUT.exists()
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
shutil.copytree(packet, OUTPUT)
assert all(sha(OUTPUT / name) == digest for name, digest in files.items())
print(
    json.dumps(
        {
            "status": "PASS",
            "packet": str(OUTPUT),
            "bound_files": len(files),
            "manifest_sha256": sha(OUTPUT / "SHA256SUMS.json"),
        },
        indent=2,
    )
)
