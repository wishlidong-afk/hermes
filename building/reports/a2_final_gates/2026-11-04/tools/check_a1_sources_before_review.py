"""Bind copied A1 packages to the real old commit and the frozen candidate."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
OLD_REPO = Path("/Users/liweishi/Documents/New project/hermes-r6-offline-tools-2026-10-30")
COMMIT = "c1f4b8fc1df23876fefeccd33bc08e0270627f9e"
CANDIDATE = Path("/Users/liweishi/Documents/New project/hermes-a2-postcommit-health-2026-11-04/candidate")
PRIVATE = ROOT / "a1-r1-private-final/r6/releases"
PACKAGES = {"old": PRIVATE / "c1f4b8f_OFFLINE/hermes_escape_top",
            "candidate": PRIVATE / "candidate_ac025f0f_OFFLINE/hermes_escape_top"}
source = json.loads((ROOT / "a1-r1-preparation-final.json").read_text())
helper_sha = hashlib.sha256((ROOT / "a1_r1_transition.py").read_bytes()).hexdigest()
assert source["helper_sha256"] == helper_sha
env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
tree = subprocess.check_output(["git", "-C", str(OLD_REPO), "ls-tree", "-r", "-z", COMMIT,
                                "--", "src/hermes_escape_top", "requirements.lock"], env=env)
blobs = {}
for raw in tree.decode().split("\0"):
    if raw:
        metadata, name = raw.split("\t", 1)
        mode, kind, object_id = metadata.split()
        if kind == "blob":
            blobs[name] = object_id
old = []
for relative, expected in source["sources"]["old"]["python_files"].items():
    path = PACKAGES["old"] / relative
    content = path.read_bytes()
    assert hashlib.sha256(content).hexdigest() == expected
    object_id = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
    assert object_id == blobs["src/hermes_escape_top/" + relative], relative
    old.append({"path": relative, "sha256": expected, "commit_blob": object_id})
for relative, path in (
    ("requirements.lock", PACKAGES["old"].parent / "requirements.lock"),
    ("src/hermes_escape_top/config/config.json", PACKAGES["old"] / "config/config.json"),
    ("src/hermes_escape_top/governance/approved_live_config.json", PACKAGES["old"] / "governance/approved_live_config.json"),
):
    content = path.read_bytes()
    assert hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest() == blobs[relative]
current = []
for relative, expected in source["sources"]["candidate"]["python_files"].items():
    assert hashlib.sha256((PACKAGES["candidate"] / relative).read_bytes()).hexdigest() == expected
    assert hashlib.sha256((CANDIDATE / "src/hermes_escape_top" / relative).read_bytes()).hexdigest() == expected
    current.append({"path": relative, "sha256": expected})
for name in ("old", "candidate"):
    assert {path.relative_to(PACKAGES[name]).as_posix() for path in PACKAGES[name].rglob("*.py")} == set(
        source["sources"][name]["python_files"])
result = {"status": "PASS", "baseline_commit": COMMIT, "helper_sha256": helper_sha,
          "old_python_files": old, "candidate_python_files": current,
          "old_python_count": len(old), "candidate_python_count": len(current),
          "default_config_identical": source["sources"]["old"]["config_sha256"] == source["sources"]["candidate"]["config_sha256"],
          "synthetic_versions_and_valuation": True, "natural_run": False}
output = ROOT / "a1-r1-source-binding.json"
assert not output.exists()
output.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({key: value for key, value in result.items() if key not in {"old_python_files", "candidate_python_files"}}, indent=2))
