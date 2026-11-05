"""Check actual audit/state, terminal journals and rollback-probe reports."""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from hermes_escape_top.core.data.sqlite_snapshot import sqlite_state_hash

ROOT = Path(__file__).resolve().parent
NAMES = (
    "audit_log.jsonl",
    "hermes_state.sqlite",
    "reentry_state.sqlite",
    "mirror_reference.sqlite",
    "flow_reference.sqlite",
    "signal_journal.jsonl",
    "soft_adapter_snapshot_2026-05-29.json",
)
CASES = ("pending", "committed_active", "committed_clean")


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def business(archive):
    result = {}
    for name in NAMES:
        path = archive / name
        assert path.is_file()
        if path.suffix == ".sqlite":
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
                digest = sqlite_state_hash(connection)
        else:
            digest = sha(path)
        result[name] = {"digest": digest, "mode": path.stat().st_mode & 0o777}
    return result


results = {}
all_pids: list[int] = []
for case in CASES:
    directory = ROOT / "cases" / case
    archive = directory / "private/r6/shared/hermes_escape_top/data/archive"
    summary = read(directory / "summary.json")
    reports = {name: read(directory / (name + ".json")) for name in summary["stages"]}
    for name, report in reports.items():
        process = read(directory / (name + ".process.json"))
        assert process["pid"] == report["pid"]
        assert process["driver_sha256"] == sha(ROOT / "verify_v2_rollback.py")
        assert process["returncode"] == process["expected_returncode"] == (-9 if process["SIGKILL_sent"] else 0)
        if name in {"old_blocked", "old_budget"}:
            assert report["v2_journal_evidence_unchanged"]
            assert report["v2_journal_evidence_before"]
    all_pids.extend(row["pid"] for row in reports.values())
    assert all(row["network_attempts"] == 0 for row in reports.values())
    assert not list((directory / "private/broker-caches").iterdir())
    assert not (archive / ".score_run_transactions/active.json").exists()
    audit = [
        json.loads(line)["payload"] for line in (archive / "audit_log.jsonl").read_text().splitlines() if line.strip()
    ]
    with closing(sqlite3.connect((archive / "hermes_state.sqlite").as_uri() + "?mode=ro", uri=True)) as connection:
        state = [json.loads(row[0]) for row in connection.execute("SELECT payload_json FROM score_runs ORDER BY id")]
    assert len(audit) == len(state) == 2
    for left, right in zip(audit, state, strict=True):
        assert left["decision_evidence"] == right["decision_evidence"]
        assert left["input_hash"] == right["input_hash"]
        assert left["decision_evidence"]["revision_budget"] == 2
    if case == "pending":
        capture = reports["capture_pending"]
        recovery = reports["recover"]
        assert capture["business_before"] == recovery["business_after"]
        assert capture["business_at_checkpoint"] != recovery["business_after"]
        assert [value["decision_evidence"]["decision_revision"] for value in audit] == [1, 1]
        assert audit[0]["decision_evidence"]["decision_id"] == audit[1]["decision_evidence"]["decision_id"]
        assert audit[1]["decision_evidence"] == reports["old_repeat"]["decision_evidence"]
        assert recovery["status_after"] == "RECOVERED_ROLLBACK" and recovery["evidence_removed"]
        journal = read(archive / f".score_run_transactions/runs/{capture['run_id']}/manifest.json")
        assert journal["status"] == "RECOVERED_ROLLBACK"
        assert all(
            not (archive.parent / row["path"]).exists()
            for row in journal["artifacts"]
            if row["role"] == "DECISION_INPUT_EVIDENCE"
        )
    else:
        capture = reports["capture_active" if case == "committed_active" else "capture_clean"]
        assert [value["decision_evidence"]["decision_revision"] for value in audit] == [1, 2]
        assert audit[1]["decision_evidence"] == capture["decision_evidence"]
        assert audit[1]["decision_evidence"]["supersedes_decision_id"] == audit[0]["decision_evidence"]["decision_id"]
        assert audit[1]["decision_evidence"]["previous_decision_hash"] == audit[0]["decision_evidence"]["decision_hash"]
        record_path = archive / f".score_run_transactions/runs/{audit[1]['persistence']['run_id']}/manifest.json"
        journal = read(record_path)
        assert journal["status"] == "COMMITTED" and journal["schema_version"] == "hermes-score-run-transaction-v2"
        assert sum(row["role"] == "BUSINESS" for row in journal["artifacts"]) == 7
        assert journal["input_binding"]["decision_id"] == audit[1]["decision_evidence"]["decision_id"]
        assert journal["input_binding"]["input_hash"] == audit[1]["input_hash"]
        assert all(
            sha(archive.parent / row["path"]) == row["after_sha256"]
            for row in journal["artifacts"]
            if row["role"] == "DECISION_INPUT_EVIDENCE"
        )
        expected = capture["business_at_checkpoint" if case == "committed_active" else "business_after"]
        assert business(archive) == expected
        assert {name: sha(archive / name) for name in NAMES} == reports["old_budget"]["raw_business_before"]
        if case == "committed_active":
            recovery = reports["recover"]
            assert recovery["journal_before_sha256"] == recovery["journal_after_sha256"] == sha(record_path)
            assert recovery["evidence_preserved"] and recovery["business_before"] == recovery["business_after"]
    if case != "committed_clean":
        refusal = reports["old_blocked"]
        assert refusal["error"]["type"] == "PersistenceRecoveryError"
        assert refusal["raw_business_before"] == refusal["raw_business_after"]
        assert refusal["active_pointer_unchanged"]
        assert capture["active_pointer"]["run_id"] == "V2_REQUIRES_UPGRADED_WRITER"
    if case != "pending":
        refusal = reports["old_budget"]
        assert refusal["error"]["type"] == "DecisionRevisionConflict"
        assert refusal["raw_business_before"] == refusal["raw_business_after"]
    results[case] = {
        "status": "PASS",
        "audit_revisions": [row["decision_evidence"]["decision_revision"] for row in audit],
        "audit_state_identity_equal": True,
        "actual_terminal_journal_status": journal["status"],
        "active_absent": True,
        "registered_business_roles": sum(row["role"] == "BUSINESS" for row in journal["artifacts"]),
    }
assert len(all_pids) == len(set(all_pids)) == 13
output = ROOT / "postcheck.json"
with output.open("x") as stream:
    stream.write(
        json.dumps(
            {
                "status": "PASS",
                "cases": results,
                "distinct_processes": 13,
                "synthetic_only": True,
                "DEPLOY": "HOLD",
                "A2": "OPEN",
                "Phase_B": "NOT_STARTED",
            },
            indent=2,
        )
        + "\n"
    )
print(output.read_text())
