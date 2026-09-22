"""Evidence-only wrapper: unchanged strict comparator, two interpreters."""
import argparse
import hashlib
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--old-python", required=True)
parser.add_argument("--new-python", required=True)
parser.add_argument("--old-lock", type=Path, required=True)
parser.add_argument("--new-lock", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
path = args.source / "scripts/compare_pipeline_persistence.py"
spec = importlib.util.spec_from_file_location("comparator", path)
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
seed = args.source / "src/hermes_escape_top/data"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def versions(python):
    code = "import importlib.metadata as m,json; print(json.dumps({d.metadata['Name'].lower().replace('_','-'):d.version for d in m.distributions()}))"
    return json.loads(subprocess.check_output([python, "-c", code], text=True))


old, new = versions(args.old_python), versions(args.new_python)
locked = [line.split("==")[0] for line in args.old_lock.read_text().splitlines()
          if line and not line.startswith(("#", " ")) and "==" in line]
assert all(name in old and name in new for name in locked)
changed = {name: [old.get(name), new.get(name)] for name in locked
           if old.get(name) != new.get(name)}
assert changed == {"soupsieve": ["2.8.4", "2.9"]}, changed
report = {
    "contract": "strict", "production_dependency_changes": changed,
    "old_versions": old, "new_versions": new,
    "old_python": c._python_evidence(args.old_python),
    "new_python": c._python_evidence(args.new_python),
    "old_lock_sha256": sha(args.old_lock), "new_lock_sha256": sha(args.new_lock),
    "comparator_sha256": sha(path), "driver_sha256": sha(Path(__file__)),
    "source": c._tree_fingerprint(args.source,
        relative_roots=c.SOURCE_FINGERPRINT_ROOTS,
        excluded_prefixes=c.SOURCE_FINGERPRINT_EXCLUDES),
    "seed": c._tree_fingerprint(seed, relative_roots=(*c.SEED_SUBDIRS, "sentiment.xls")),
    "notes": ["Same frozen source and seed; independent isolated data roots and processes.",
              "Existing comparator normalization unchanged; includes seven business artifacts.",
              "IBKR excluded. No official live runs or live data writes."],
    "dates": {},
}
with tempfile.TemporaryDirectory(prefix="hermes-dependency-equivalence-") as tmp:
    for day in ("2022-01-03", "2022-01-25", "2026-05-29", "2026-06-04"):
        baseline = c._run_and_snapshot(args.source, seed, Path(tmp) / ("old-" + day), day, args.old_python)
        candidate = c._run_and_snapshot(args.source, seed, Path(tmp) / ("new-" + day), day, args.new_python)
        differences = c._differences(baseline, candidate)
        report["dates"][day] = {"equal": not differences, "strict_differences": differences,
                                "baseline": c._summary(baseline), "candidate": c._summary(candidate)}
        print(day, "PASS" if not differences else "FAIL", flush=True)
report["all_equal"] = all(row["equal"] for row in report["dates"].values())
args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
raise SystemExit(0 if report["all_equal"] else 1)
