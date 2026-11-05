"""Publish full-suite evidence and the limited A1 r1 rehearsal separately."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
MAIN = Path("/Users/liweishi/Documents/github/hermes")
SOURCE = Path("/Users/liweishi/Documents/New project/hermes-a2-postcommit-health-2026-11-04")
PACKET = MAIN / "building/reports/a2_postcommit_health/2026-11-04"
OUTPUT = MAIN / "building/reports/a2_final_gates/2026-11-04"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


binding = read(PACKET / "candidate-binding.json")
assert binding["manifest_sha256"] == "90842a116706bb48fa17f1b2c207649252073ac074db7f8110d0b87d775448aa"
assert all(sha(SOURCE / "candidate" / name) == digest for name, digest in binding["files"].items())
old = read(SOURCE / "preservation-before.json")
assert all(sha(MAIN / name) == digest for name, digest in old["main_files"].items())
env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
for value in old["git"].values():
    repo = Path(value["root"])
    assert subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], env=env, text=True).strip() == value["head"]
    assert sha(repo / ".git/index") == value["index_sha256"]
    assert sha(repo / ".git/config") == value["config_sha256"]
assert sha(PACKET / "SHA256SUMS.json") == "958ed44498c80000501fa7d8767866dca13bb1bfa43c9d1f7c112f84c82c6267"
assert all(sha(PACKET / name) == digest for name, digest in read(PACKET / "SHA256SUMS.json")["files"].items())
prepared = read(ROOT / "a1-r1-source-binding-final.json")
private = ROOT / "a1-r1-private-final"
assert all(sha(private / name) == digest for name, digest in prepared["prepared_artifacts"].items())
assert prepared["helper_sha256"] == sha(ROOT / "a1_r1_transition.py")
postcheck = read(ROOT / "a1-r1-postcheck.json")
assert postcheck["status"] == "PASS" and postcheck["revisions"] == [1, 2, 2]
runs = read(ROOT / "verification-runs.json")
for stage in ("full-suite", "a1-tool-negative-guards-final", "a1-tools-mypy-final", "a1-tools-ruff-final",
              "a1-r1-transition", "a1-r1-audit-state-postcheck"):
    row = next(row for row in runs if row["stage"] == stage)
    assert row["exit_code"] == 0 and row["source_unchanged"], stage
assert "2288 passed" in (ROOT / "full-suite.log").read_text()
packet = ROOT / "new-packet"
packet.mkdir()
for name in ("verification-runs.json", "a1-r1-preparation.json", "a1-r1-preparation-final.json",
             "a1-r1-source-binding.json", "a1-r1-source-binding-final.json", "a1-tool-guards.json",
             "a1-tool-guards-final.json", "a1-r1-summary.json", "a1-r1-postcheck.json"):
    shutil.copy2(ROOT / name, packet / name)
(packet / "tools").mkdir()
for name in ("a1_r1_transition.py", "check_a1_sources.py", "check_tool_guards.py", "postcheck_a1.py",
             "a1_r1_transition_preparation_before.py", "a1_r1_transition_before_review.py",
             "check_a1_sources_before_review.py", "run.py", "publish.py"):
    shutil.copy2(ROOT / name, packet / "tools" / name)
(packet / "logs").mkdir()
for row in runs:
    shutil.copy2(ROOT / row["log"], packet / "logs" / row["log"])
for step in ("old_r1", "candidate_r2", "candidate_repeat", "old_rollback"):
    for suffix in (".json", ".stdout.log", ".stderr.log"):
        shutil.copy2(ROOT / ("a1-r1-" + step + suffix), packet / ("a1-r1-" + step + suffix))
audit = [json.loads(line)["payload"] for line in
         (private / "r6/shared/hermes_escape_top/data/archive/audit_log.jsonl").read_text().splitlines()]
write(packet / "a1-transition-observations.json", {"synthetic_only": True,
    "runs": [{"as_of": value["as_of"], "transaction_protocol": value["persistence"]["protocol"],
              "input_hash": value["input_hash"], "valuation_source": value["soft_data"]["records"]["valuation"]["source"],
              "decision_evidence": value["decision_evidence"]} for value in audit]})
write(packet / "reused-evidence.json", {"unchanged_candidate_manifest": binding["manifest_sha256"],
      "previous_packet": str(PACKET), "previous_packet_manifest_sha256": sha(PACKET / "SHA256SUMS.json"),
      "four_date_strict_sha256": sha(PACKET / "equivalence.json"),
      "scope": "Reuse unchanged-source strict/governance/dependency/production-static results; no claim of rerunning them."})
write(packet / "preservation.json", {"candidate_files_unchanged": len(binding["files"]),
      "previous_main_files_unchanged": len(old["main_files"]), "original_git_unchanged": True,
      "prepared_materials_unchanged_after_rehearsal": len(prepared["prepared_artifacts"]), "live_written": False})
write(packet / "internal-review.json", {"reviewer": "Zeno", "agent_id": "01a1a69e-f834-7fd3-8912-f0a0bfa9ed94",
      "initial_tool_P2": ["worker bypassed full gate/controlled parent", "candidate non-Python binding and execution-time drift not checked"],
      "disposition": "Both targeted fixes accepted in followup static review; no new finding reported.",
      "scope": "internal static review only, no external approval or execution claims",
      "helper_sha256": prepared["helper_sha256"], "bound_prepared_artifacts": 393, "closed": True})
write(packet / "completion-boundary.json", {"local_full_suite": "2288 PASS", "A1_r1_only": "MECHANISM_PASS",
      "still_open": ["old r2 transition rejection", "new business-date chain", "v2 pending/committed active-pointer rollback",
                     "final integrated external review", "Git integration and CI", "precise deployment authorization",
                     "live-config/data-bound release proof", "natural ON/v2 observation", "A2 closure"],
      "DEPLOY": "HOLD", "A2": "OPEN", "Phase_B": "NOT_STARTED"})
files = {str(path.relative_to(packet)): sha(path) for path in sorted(packet.rglob("*")) if path.is_file()}
write(packet / "SHA256SUMS.json", {"schema_version": "hermes-final-gates-evidence-v1", "files": files})
assert not OUTPUT.exists()
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
shutil.copytree(packet, OUTPUT)
assert all(sha(OUTPUT / name) == digest for name, digest in files.items())
print(json.dumps({"status": "PASS", "packet": str(OUTPUT), "bound_files": len(files),
                  "manifest_sha256": sha(OUTPUT / "SHA256SUMS.json"), "production_source_unchanged": True}, indent=2))
