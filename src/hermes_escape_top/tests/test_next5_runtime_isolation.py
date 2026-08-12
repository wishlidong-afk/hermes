from __future__ import annotations

from pathlib import Path

import pytest

from hermes_escape_top.core.data.runtime_root import require_explicit_runtime_data_root
from hermes_escape_top.scripts import check_next5_unlock as next5


def test_next5_status_writes_only_runtime_archive(monkeypatch, tmp_path):
    journal = tmp_path / "data/archive/signal_journal.jsonl"
    status = tmp_path / "data/archive/NEXT5_unlock_status.md"
    journal.parent.mkdir(parents=True)
    journal.write_text(
        '{"as_of":"2026-06-18","symbol":"MSTR","status":"EXIT","regime":"HIGH_VOL"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(next5, "JOURNAL_PATH", journal)
    monkeypatch.setattr(next5, "LOCAL_STATUS_PATH", status)

    with pytest.raises(SystemExit) as exc:
        next5.main()

    assert exc.value.code == 0
    assert status.exists()
    assert str(tmp_path) in next5.scan()["journal_path"]


def test_next5_source_has_no_repo_write_candidates():
    source = Path(next5.__file__).read_text(encoding="utf-8")

    assert "Documents/github" not in source
    assert "building/logs" not in source
    assert "REPO_STATUS_PATH" not in source


def test_next5_runtime_archive_stays_under_explicit_data_root(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_DATA_DIR", str(tmp_path))
    runtime_root = require_explicit_runtime_data_root("next5")
    archive = runtime_root / "data" / "archive"

    assert archive.is_relative_to(runtime_root)
