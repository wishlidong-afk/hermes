"""Verify a frozen candidate without updating earlier evidence records."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
CANDIDATE = Path("/Users/liweishi/Documents/New project/hermes-a2-postcommit-health-2026-11-04/candidate")
PACKET = Path("/Users/liweishi/Documents/github/hermes/building/reports/a2_postcommit_health/2026-11-04")
stage, *command = sys.argv[1:]
log = ROOT / (stage + ".log")
assert not log.exists(), "never overwrite a completed stage"
binding = json.loads((PACKET / "candidate-binding.json").read_text())


def hashes():
    return {name: hashlib.sha256((CANDIDATE / name).read_bytes()).hexdigest()
            for name in binding["files"]}


before = hashes()
assert before == binding["files"], "frozen candidate drifted before verification"
env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "PYTHONDONTWRITEBYTECODE": "1",
       "PYTHONPATH": str(CANDIDATE / "src") + ":" + str(CANDIDATE / "src/hermes_escape_top/tests"),
       "FRED_API_KEY": "hermes-final-gates-synthetic-key", "RUFF_CACHE_DIR": str(ROOT / "ruff-cache"),
       "PYTHONPYCACHEPREFIX": str(ROOT / "pycache")}
start = time.monotonic()
with log.open("w") as stream:
    result = subprocess.run(command, cwd=CANDIDATE, env=env, stdout=stream, stderr=subprocess.STDOUT)
after = hashes()
record = {"stage": stage, "command": command, "cwd": str(CANDIDATE),
          "exit_code": result.returncode, "seconds": round(time.monotonic() - start, 2),
          "log": log.name, "source_manifest_sha256": binding["manifest_sha256"],
          "bound_source_files": len(before), "source_unchanged": before == after == binding["files"]}
records = ROOT / "verification-runs.json"
rows = json.loads(records.read_text()) if records.exists() else []
rows.append(record)
records.write_text(json.dumps(rows, indent=2) + "\n")
print(json.dumps(record, indent=2), flush=True)
print(log.read_text()[-10000:], flush=True)
assert record["source_unchanged"], "candidate drifted during verification"
raise SystemExit(result.returncode)
