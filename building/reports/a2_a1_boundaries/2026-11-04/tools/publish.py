"""Freeze only synthetic diagnostic evidence; never copy private databases."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAIN = Path("/Users/liweishi/Documents/github/hermes")
PRIOR = Path("/Users/liweishi/Documents/New project/hermes-a2-final-gates-2026-11-04")
OLD_ATTEMPT = Path("/Users/liweishi/Documents/New project/hermes-a2-a1-boundaries-2026-11-04")
INTERMEDIATE = Path("/Users/liweishi/Documents/New project/hermes-a2-a1-boundaries-final-2026-11-04")
SOURCE = Path("/Users/liweishi/Documents/New project/hermes-a2-postcommit-health-2026-11-04")
PRIOR_PACKET = MAIN / "building/reports/a2_final_gates/2026-11-04"
OUTPUT = MAIN / "building/reports/a2_a1_boundaries/2026-11-04"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    with path.open("x") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


binding = read(MAIN / "building/reports/a2_postcommit_health/2026-11-04/candidate-binding.json")
assert all(sha(SOURCE / "candidate" / name) == digest for name, digest in binding["files"].items())
old = read(SOURCE / "preservation-before.json")
assert all(sha(MAIN / name) == digest for name, digest in old["main_files"].items())
env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
for value in old["git"].values():
    repo = Path(value["root"])
    assert (
        subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], env=env, text=True).strip()
        == value["head"]
    )
    assert sha(repo / ".git/index") == value["index_sha256"]
    assert sha(repo / ".git/config") == value["config_sha256"]
assert sha(PRIOR_PACKET / "SHA256SUMS.json") == "e171778ffb5198da45f4b8d53c8fbbfa84e26ac83558e44e6ce738189ac386cb"
assert all(
    sha(PRIOR_PACKET / name) == digest for name, digest in read(PRIOR_PACKET / "SHA256SUMS.json")["files"].items()
)
prepared = read(ROOT / "source-binding-execution.json")
assert len(prepared["prepared_artifacts"]) == 594
assert all(sha(ROOT / "private" / name) == digest for name, digest in prepared["prepared_artifacts"].items())
assert prepared["helper_sha256"] == sha(ROOT / "verify_boundaries.py")
assert read(ROOT / "summary.json")["status"] == read(ROOT / "independent-postcheck.json")["status"] == "PASS"
assert read(ROOT / "internal-review.json")["followup_received"]
runs = read(ROOT / "verification-runs.json")
for stage in ("tool-guards", "r2-and-new-date", "independent-postcheck", "tools-ruff-final", "tools-mypy"):
    row = next(row for row in runs if row["stage"] == stage)
    assert row["exit_code"] == 0 and row["source_unchanged"], stage
packet = ROOT / "packet"
packet.mkdir()
(packet / "tools").mkdir()
(packet / "logs").mkdir()
(packet / "earlier-attempt").mkdir()
for name in ("verify_boundaries.py", "check_guards.py", "postcheck.py", "run.py", "publish.py"):
    shutil.copy2(ROOT / name, packet / "tools" / name)
for name in (
    "source-binding.json",
    "source-binding-execution.json",
    "a1-r1-preparation-final.json",
    "guards-execution.json",
    "summary.json",
    "independent-postcheck.json",
    "verification-runs.json",
    "internal-review.json",
):
    shutil.copy2(ROOT / name, packet / name)
for row in runs:
    shutil.copy2(ROOT / row["log"], packet / "logs" / row["log"])
for step in ("old_r1", "old_r2", "candidate_blocked", "old_repeat", "new_date", "new_release_repeat"):
    for suffix in (".json", ".stdout.log", ".stderr.log"):
        shutil.copy2(ROOT / (step + suffix), packet / (step + suffix))
for name in ("r2-and-new-date.log", "old_r2.stderr.log", "verification-runs.json"):
    shutil.copy2(OLD_ATTEMPT / name, packet / "earlier-attempt" / name)
shutil.copy2(OLD_ATTEMPT / "verify_boundaries.py", packet / "tools/before_csv_fix.py")
shutil.copy2(INTERMEDIATE / "verify_boundaries.py", packet / "tools/before_hardening.py")
write(
    packet / "reuse.json",
    {
        "candidate_manifest": binding["manifest_sha256"],
        "bound_source_files": len(binding["files"]),
        "prior_packet": str(PRIOR_PACKET),
        "prior_packet_manifest_sha256": sha(PRIOR_PACKET / "SHA256SUMS.json"),
        "full_suite": "2288 passed; reused unchanged source/environment, not rerun",
        "prior_helper_sha256": sha(PRIOR / "a1_r1_transition.py"),
        "prior_guard_scope": (
            "11 original full-suite/parent-token refusals reused; "
            "11 new tool checks separately executed"
        ),
        "intermediate_normal_run_summary_sha256": sha(INTERMEDIATE / "summary.json"),
        "intermediate_normal_run": "Passed before hardening, not used as proof of hardened bytes",
    },
)
write(
    packet / "preservation.json",
    {
        "candidate_files_unchanged": len(binding["files"]),
        "original_main_files_unchanged": len(old["main_files"]),
        "prepared_files_unchanged": 594,
        "prior_packet_files_unchanged": len(read(PRIOR_PACKET / "SHA256SUMS.json")["files"]),
        "original_git_head_index_config_unchanged": True,
        "live_written": False,
    },
)
write(
    packet / "boundary.json",
    {
        "synthetic_only": True,
        "capture_inputs": False,
        "transaction_protocol": "v1",
        "completed": [
            "real old r2 rejects candidate without business overwrite",
            "actual new as_of r1 stable across candidate releases",
            "old audit prefix and predecessor fields preserved",
        ],
        "not_proved": [
            "v2 PENDING/COMMITTED-active/clean rollback",
            "actual live config/data release proof",
            "final external review",
            "Git integration and CI",
            "natural observation",
            "deployment",
        ],
        "security_scope": (
            "Controlled local rehearsal, not an adversarial same-user or concurrent "
            "ancestor replacement security boundary; hashes are not signatures"
        ),
        "DEPLOY": "HOLD",
        "A2": "OPEN",
        "Phase_B": "NOT_STARTED",
    },
)
files = {path.relative_to(packet).as_posix(): sha(path) for path in sorted(packet.rglob("*")) if path.is_file()}
write(packet / "SHA256SUMS.json", {"schema_version": "hermes-a1-boundaries-evidence-v1", "files": files})
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
