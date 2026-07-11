from __future__ import annotations

import json
from pathlib import Path

from hermes_escape_top.core.data.audit import write_audit_record
from hermes_escape_top.core.data.jsonl import append_jsonl_records, repair_jsonl_tail
from hermes_escape_top.core.decision.signal_journal import SignalJournalEntry, append_signal_journal


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_append_removes_an_incomplete_tail_before_writing(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    path.write_bytes(b'{"id": 1}\n{"id":')

    result = append_jsonl_records(path, [{"id": 2}])

    assert _rows(path) == [{"id": 1}, {"id": 2}]
    assert result["tail_repair"]["status"] == "TRUNCATED_PARTIAL"
    assert result["tail_repair"]["removed_bytes"] == len(b'{"id":')


def test_valid_last_record_without_newline_is_preserved(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    path.write_bytes(b'{"id": 1}')

    result = append_jsonl_records(path, [{"id": 2}])

    assert _rows(path) == [{"id": 1}, {"id": 2}]
    assert result["tail_repair"]["status"] == "ADDED_NEWLINE"


def test_repair_is_noop_for_a_clean_tail(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    path.write_bytes(b'{"id": 1}\n')

    result = repair_jsonl_tail(path)

    assert result == {"status": "CLEAN", "removed_bytes": 0}
    assert path.read_bytes() == b'{"id": 1}\n'


def test_audit_writer_repairs_partial_tail(tmp_path: Path):
    archive = tmp_path / "archive"
    archive.mkdir()
    path = archive / "audit_log.jsonl"
    path.write_bytes(b'{"schema_version":"old","as_of":"2026-07-09"}\n{"partial":')

    write_audit_record(
        {
            "as_of": "2026-07-10",
            "input_hash": "input",
            "config_version": "unit",
            "scores": {},
        },
        archive,
    )

    rows = _rows(path)
    assert len(rows) == 2
    assert rows[-1]["as_of"] == "2026-07-10"


def test_signal_journal_repairs_partial_tail(tmp_path: Path):
    path = tmp_path / "signal_journal.jsonl"
    path.write_bytes(b'{"as_of":"2026-07-09","symbol":"MSTR","status":"EXIT"}\n{"partial":')

    append_signal_journal(
        path,
        [SignalJournalEntry("2026-07-10", "MSTR", "HOLD", 10.0, [])],
    )

    rows = _rows(path)
    assert len(rows) == 2
    assert rows[-1]["as_of"] == "2026-07-10"
