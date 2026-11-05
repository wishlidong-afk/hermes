"""Independently check frozen reports against actual audit, state and journals."""

import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "private/r6/shared/hermes_escape_top/data/archive"
STEPS = (
    "old_r1",
    "old_r2",
    "candidate_blocked",
    "old_repeat",
    "new_date",
    "new_release_repeat",
)
OLD_LOGIC = "42d207d6b6c84001bf85324ea6af84b5947c7748b7217d72f0d715b21232ad8a"
NEW_LOGIC = "ac025f0f93d16ee3b97e1aaa8f7e70b49801032d81085453b7e5531eae8e7dad"


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def differences(left, right, path=""):
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict):
        return [
            value
            for key in sorted(left.keys() | right.keys())
            for value in (
                [path + "/" + key]
                if key not in left or key not in right
                else differences(left[key], right[key], path + "/" + key)
            )
        ]
    return [] if left == right else [path]


reports = [read(ROOT / (step + ".json")) for step in STEPS]
success = [row for row in reports if row["error"] is None]
audit_bytes = (ARCHIVE / "audit_log.jsonl").read_bytes()
audit = [
    json.loads(line)["payload"] for line in audit_bytes.splitlines() if line.strip()
]
with sqlite3.connect(
    (ARCHIVE / "hermes_state.sqlite").as_uri() + "?mode=ro", uri=True
) as connection:
    state = [
        json.loads(row[0])
        for row in connection.execute("SELECT payload_json FROM score_runs ORDER BY id")
    ]
assert len(audit) == len(state) == len(success) == 5
assert [row["decision_evidence"]["decision_revision"] for row in audit] == [
    1,
    2,
    2,
    1,
    1,
]
for index, report in enumerate(success):
    assert (
        report["decision_evidence"]
        == audit[index]["decision_evidence"]
        == state[index]["decision_evidence"]
    )
    assert (
        report["input_hash"] == audit[index]["input_hash"] == state[index]["input_hash"]
    )
    evidence = report["decision_evidence"]
    assert evidence["semantic_identity"]["scoring_logic_hash"] == (
        OLD_LOGIC if index < 3 else NEW_LOGIC
    )
    assert evidence["revision_budget"] == 2 and "identity_migration" not in evidence
    journal = read(
        ARCHIVE
        / f".score_run_transactions/runs/{audit[index]['persistence']['run_id']}/manifest.json"
    )
    assert journal["status"] == "COMMITTED" and len(journal["artifacts"]) == 7
    assert audit[index]["persistence"]["protocol"] == "recoverable-journal-v1"
    assert (
        hashlib.sha256(audit_bytes[: report["audit_before_bytes"]]).hexdigest()
        == report["audit_before_sha256"]
    )
blocked = reports[2]
assert blocked["before"] == blocked["after"] and len(blocked["before"]) == 7
assert all(blocked["before"].values())
assert blocked["audit_before_sha256"] == blocked["audit_after_sha256"]
assert (
    success[1]["decision_evidence"]["decision_id"]
    == success[2]["decision_evidence"]["decision_id"]
)
for report in success[1:3]:
    assert (
        report["decision_evidence"]["supersedes_decision_id"]
        == success[0]["decision_evidence"]["decision_id"]
    )
    assert (
        report["decision_evidence"]["previous_decision_hash"]
        == success[0]["decision_evidence"]["decision_hash"]
    )
for report in success[3:]:
    assert report["decision_evidence"]["supersedes_decision_id"] is None
    assert report["decision_evidence"]["previous_decision_hash"] is None
assert success[3]["as_of"] == success[4]["as_of"] == "2026-06-01"
assert (
    success[3]["decision_evidence"]["decision_id"]
    == success[4]["decision_evidence"]["decision_id"]
)
assert (
    success[3]["decision_evidence"]["scorer_release_hash"]
    != success[4]["decision_evidence"]["scorer_release_hash"]
)
assert [row["as_of"] for row in audit] == ["2026-05-29"] * 3 + ["2026-06-01"] * 2
assert len({row["pid"] for row in reports}) == 6
assert all(row["network_attempts"] == row["broker_cache_files"] == 0 for row in reports)
assert not (ARCHIVE / ".score_run_transactions/active.json").exists()
result = {
    "status": "PASS",
    "synthetic_only": True,
    "audit_rows": 5,
    "successful_revisions": [1, 2, 2, 1, 1],
    "old_material_semantic_difference_paths": differences(
        success[0]["decision_evidence"]["semantic_identity"],
        success[1]["decision_evidence"]["semantic_identity"],
    ),
    "new_release_semantic_difference_paths": differences(
        success[3]["decision_evidence"]["semantic_identity"],
        success[4]["decision_evidence"]["semantic_identity"],
    ),
    "old_r2_candidate_refused_seven_existing_artifacts_unchanged": True,
    "old_audit_prefix_still_present_after_new_date": True,
    "report_audit_state_equal": True,
    "transaction_protocol": "v1",
    "separate_processes": 6,
    "reports_sha256": {step: sha(ROOT / (step + ".json")) for step in STEPS},
    "helper_sha256": sha(ROOT / "verify_boundaries.py"),
    "DEPLOY": "HOLD",
    "A2": "OPEN",
    "Phase_B": "NOT_STARTED",
}
assert result["new_release_semantic_difference_paths"] == []
output = ROOT / "independent-postcheck.json"
assert not output.exists()
with output.open("x") as stream:
    stream.write(json.dumps(result, indent=2) + "\n")
print(output.read_text())
