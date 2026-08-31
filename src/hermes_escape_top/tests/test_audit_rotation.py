"""Tests for audit-log rotation — bound the append-only log without losing records."""
from __future__ import annotations

import gzip
import json

from hermes_escape_top.core.data.audit import rotate_audit_log


def test_rotate_compacts_to_latest_per_day_losslessly(tmp_path):
    p = tmp_path / "audit_log.jsonl"
    lines = []
    # 3 days × 3 re-runs each (same scheduled run_type) — the re-run bloat case.
    for day in ("2026-06-10", "2026-06-11", "2026-06-12"):
        for i in range(3):
            lines.append(json.dumps({"payload": {"as_of": day, "run_type": "scheduled", "scores": {}, "n": i}}))
    p.write_text("\n".join(lines) + "\n")

    arch = rotate_audit_log(p, keep_days=90, min_size_mb=0)  # force rotation

    kept = [l for l in p.read_text().splitlines() if l.strip()]
    archived = [l for l in gzip.open(arch, "rt").read().splitlines() if l.strip()]
    # archive is lossless (every original record preserved)
    assert len(archived) == 9
    # main file compacted to the latest record per (as_of, run_type) = 1/day
    assert len(kept) == 3
    # the kept record is the NEWEST for each day (n == 2)
    assert all(json.loads(l)["payload"]["n"] == 2 for l in kept)
    # no day is dropped
    assert {json.loads(l)["payload"]["as_of"] for l in kept} == {"2026-06-10", "2026-06-11", "2026-06-12"}


def test_rotate_keeps_distinct_run_types_per_day(tmp_path):
    p = tmp_path / "audit_log.jsonl"
    lines = [
        json.dumps({"payload": {"as_of": "2026-06-12", "run_type": "scheduled", "scores": {}}}),
        json.dumps({"payload": {"as_of": "2026-06-12", "run_type": "manual_rerun", "scores": {}}}),
    ]
    p.write_text("\n".join(lines) + "\n")
    rotate_audit_log(p, keep_days=90, min_size_mb=0)
    kept = [json.loads(l)["payload"]["run_type"] for l in p.read_text().splitlines() if l.strip()]
    # both the official and the preview record for the day survive
    assert set(kept) == {"scheduled", "manual_rerun"}


def test_rotate_keeps_each_scheduled_revision_but_compacts_revision_repeats(tmp_path):
    p = tmp_path / "audit_log.jsonl"
    base = {"as_of": "2026-08-28", "run_type": "scheduled", "scores": {}}
    lines = [
        json.dumps({"payload": {**base, "decision_evidence": {"decision_revision": 1}, "n": "r1"}}),
        json.dumps({"payload": {**base, "decision_evidence": {"decision_revision": 2}, "n": "r2-first"}}),
        json.dumps({"payload": {**base, "decision_evidence": {"decision_revision": 2}, "n": "r2-repeat"}}),
        json.dumps({"payload": {**base, "run_type": "manual_rerun", "n": "preview"}}),
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    archive = rotate_audit_log(p, keep_days=90, min_size_mb=0)

    kept = [json.loads(line)["payload"] for line in p.read_text(encoding="utf-8").splitlines()]
    assert [row["n"] for row in kept] == ["r1", "r2-repeat", "preview"]
    with gzip.open(archive, "rt", encoding="utf-8") as handle:
        assert len(handle.read().splitlines()) == 4


def test_rotate_is_noop_below_size_threshold(tmp_path):
    p = tmp_path / "audit_log.jsonl"
    original = '{"payload":{"as_of":"2026-06-12","scores":{}}}\n'
    p.write_text(original)
    assert rotate_audit_log(p, min_size_mb=100) is None  # tiny file -> no-op
    assert p.read_text() == original                     # untouched
