"""Check A1 reports against actual audit/state rows and enumerate all differences."""
import hashlib
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT / "a1-r1-private-final"
ARCHIVE = PRIVATE / "r6/shared/hermes_escape_top/data/archive"
STEPS = ("old_r1", "candidate_r2", "candidate_repeat", "old_rollback")
LOGIC = ("42d207d6b6c84001bf85324ea6af84b5947c7748b7217d72f0d715b21232ad8a",
         "ac025f0f93d16ee3b97e1aaa8f7e70b49801032d81085453b7e5531eae8e7dad")


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def differences(left, right, path=""):
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict):
        result = []
        for key in sorted(set(left) | set(right)):
            child = path + "/" + key
            result.extend([child] if key not in left or key not in right else differences(left[key], right[key], child))
        return result
    if isinstance(left, list):
        if len(left) != len(right):
            return [path]
        return [item for index, (a, b) in enumerate(zip(left, right, strict=True))
                for item in differences(a, b, path + "/" + str(index))]
    return [] if left == right else [path]


reports = [read(ROOT / ("a1-r1-" + step + ".json")) for step in STEPS]
summary = read(ROOT / "a1-r1-summary.json")
assert summary["status"] == "PASS" and summary["helper_sha256"] == sha(ROOT / "a1_r1_transition.py")
assert reports[0]["scoring_logic_hash"] == reports[3]["scoring_logic_hash"] == LOGIC[0]
assert reports[1]["scoring_logic_hash"] == reports[2]["scoring_logic_hash"] == LOGIC[1]
audit = [json.loads(line)["payload"] for line in (ARCHIVE / "audit_log.jsonl").read_text().splitlines() if line.strip()]
assert len(audit) == 3
with sqlite3.connect((ARCHIVE / "hermes_state.sqlite").as_uri() + "?mode=ro", uri=True) as connection:
    state = [json.loads(row[0]) for row in connection.execute("SELECT payload_json FROM score_runs ORDER BY id")]
assert len(state) == 3
evidence = []
for index, report in enumerate(reports[:3]):
    certification = report["decision_evidence"]
    assert certification == audit[index]["decision_evidence"] == state[index]["decision_evidence"]
    assert report["input_hash"] == audit[index]["input_hash"] == state[index]["input_hash"]
    assert certification["revision_budget"] == 2 and "identity_migration" not in certification
    assert certification["semantic_identity"]["scoring_logic_hash"] == report["scoring_logic_hash"]
    run_id = audit[index]["persistence"]["run_id"]
    journal = read(ARCHIVE / f".score_run_transactions/runs/{run_id}/manifest.json")
    assert journal["status"] == "COMMITTED" and len(journal["artifacts"]) == 7
    evidence.append(certification)
assert [value["decision_revision"] for value in evidence] == [1, 2, 2]
assert evidence[1]["supersedes_decision_id"] == evidence[0]["decision_id"]
assert evidence[1]["previous_decision_hash"] == evidence[0]["decision_hash"]
assert evidence[1]["semantic_hash"] == evidence[2]["semantic_hash"]
assert reports[3]["before"] == reports[3]["after"]
assert all(sha(ARCHIVE / name) == digest for name, digest in reports[3]["after"].items())
result = {
    "status": "PASS", "synthetic_only": True, "scope": "identity-v2 FINAL r1 transition with capture OFF only",
    "revisions": [1, 2, 2], "audit_state_report_identity_equal": True, "audit_rows": len(audit),
    "budget": 2, "old_writer_refused_without_legacy_reset": True,
    "old_to_candidate_certification_difference_paths": differences(evidence[0], evidence[1]),
    "candidate_repeat_certification_difference_paths": differences(evidence[1], evidence[2]),
    "old_to_candidate_decision_output_difference_paths": differences(reports[0]["decision_outputs"], reports[1]["decision_outputs"]),
    "candidate_repeat_decision_output_difference_paths": differences(reports[1]["decision_outputs"], reports[2]["decision_outputs"]),
    "reports_sha256": {step: sha(ROOT / ("a1-r1-" + step + ".json")) for step in STEPS},
    "DEPLOY": "HOLD", "A2": "OPEN", "Phase_B": "NOT_STARTED",
}
output = ROOT / "a1-r1-postcheck.json"
assert not output.exists()
output.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
