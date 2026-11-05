"""Exercise tool refusals only; no scoring, refresh, broker calls, or original writes."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("a1_rehearsal_guard_checks", ROOT / "a1_r1_transition.py")
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load the explicitly selected rehearsal tool")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
binding = json.loads((ROOT / "a1-r1-source-binding-final.json").read_text())
rows = []


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refusal(name, callback, errors):
    try:
        callback()
    except errors as exc:
        rows.append({"case": name, "refused": True, "error_type": type(exc).__name__, "error": str(exc)})
    else:
        raise AssertionError("guard did not refuse " + name)


tool.verify_gate()
assert all(sha(tool.PRIVATE / name) == digest for name, digest in binding["prepared_artifacts"].items())
original_root = tool.ROOT
with tempfile.TemporaryDirectory(prefix="a1-gate-negative-", dir=ROOT) as temporary:
    setattr(tool, "ROOT", Path(temporary))
    for name, record in (
        ("missing_full", []),
        ("failed_full", [{"stage": "full-suite", "exit_code": 1, "source_unchanged": True}]),
        ("wrong_full_tree", [{"stage": "full-suite", "exit_code": 0, "source_unchanged": True,
                              "source_manifest_sha256": "wrong", "bound_source_files": 512}]),
    ):
        (tool.ROOT / "verification-runs.json").write_text(json.dumps(record))
        refusal(name, tool.verify_gate, RuntimeError)
setattr(tool, "ROOT", original_root)
package = tool.PACKAGES["candidate"]
for name, path in (
    ("candidate_config_drift", package / "config/config.json"),
    ("candidate_policy_drift", package / "governance/approved_live_config.json"),
    ("candidate_lock_drift", package.parent / "requirements.lock"),
    ("candidate_python_drift", package / "pipeline.py"),
):
    original = path.read_bytes()
    try:
        path.write_bytes(original + b"\n")
        refusal(name, tool.verify_gate, AssertionError)
    finally:
        path.write_bytes(original)
assert all(sha(tool.PRIVATE / name) == digest for name, digest in binding["prepared_artifacts"].items())
launch = tool.PRIVATE / ".launch.json"
assert not launch.exists()
environment = {**os.environ, "PYTHONPATH": str(tool.PACKAGES["old"].parent),
               "HERMES_DATA_DIR": str(tool.PACKAGES["old"]), "PYTHONDONTWRITEBYTECODE": "1"}
direct = subprocess.run([str(tool.PYTHON), "-B", str(ROOT / "a1_r1_transition.py"), "worker", "old_r1"],
                        env=environment, capture_output=True, text=True)
assert direct.returncode != 0 and ".launch.json" in direct.stderr
rows.append({"case": "direct_worker_without_parent", "refused": True, "exit_code": direct.returncode})
token_name = "HERMES_A1_PRIVATE_LAUNCH_TOKEN"
old_token = os.environ.get(token_name)
try:
    os.environ[token_name] = "synthetic-guard-token"
    for name, value in (
        ("wrong_parent", {"parent_pid": os.getppid() + 1, "step": "old_r1", "token": "synthetic-guard-token"}),
        ("wrong_step", {"parent_pid": os.getppid(), "step": "candidate_r2", "token": "synthetic-guard-token"}),
        ("wrong_token", {"parent_pid": os.getppid(), "step": "old_r1", "token": "wrong"}),
    ):
        launch.write_text(json.dumps(value))
        launch.chmod(0o600)
        refusal(name, lambda: tool.verify_launch("old_r1"), RuntimeError)
finally:
    launch.unlink(missing_ok=True)
    if old_token is None:
        os.environ.pop(token_name, None)
    else:
        os.environ[token_name] = old_token
assert all(sha(tool.PRIVATE / name) == digest for name, digest in binding["prepared_artifacts"].items())
assert not (tool.PRIVATE / "r6/shared/hermes_escape_top/data/archive/.score_run_transactions").exists()
output = ROOT / "a1-tool-guards-final.json"
assert not output.exists()
output.write_text(json.dumps({"status": "PASS", "cases": rows, "prepared_artifacts_restored": True,
                              "scoring_invoked": False, "synthetic_metadata_used_for_full_gate_negatives": True}, indent=2) + "\n")
print(json.dumps({"status": "PASS", "cases": len(rows), "scoring_invoked": False}))
