from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from hermes_escape_top.core.data.external_sources.import_queue import (
    finalize_import,
    queue_import_candidates,
)


def test_import_queue_deduplicates_content_and_preserves_originals(tmp_path):
    archive = tmp_path / "archive"
    first = tmp_path / "Downloads" / "sentiment.xls"
    duplicate = tmp_path / "external_imports" / "sentiment-copy.xls"
    first.parent.mkdir(parents=True)
    duplicate.parent.mkdir(parents=True)
    first.write_bytes(b"same official workbook")
    duplicate.write_bytes(first.read_bytes())

    queued = queue_import_candidates(
        "aaii_sentiment",
        archive,
        [first, duplicate],
        processed_hashes=set(),
    )

    digest = hashlib.sha256(first.read_bytes()).hexdigest()
    assert len(queued) == 1
    assert queued[0].name == f"{digest}.xls"
    assert queued[0].parent.name == "inbox"
    assert first.read_bytes() == b"same official workbook"
    assert duplicate.read_bytes() == b"same official workbook"


def test_import_queue_moves_terminal_files_and_never_restages_same_hash(tmp_path):
    archive = tmp_path / "archive"
    source = tmp_path / "sentiment.xls"
    source.write_bytes(b"official workbook")
    queued = queue_import_candidates(
        "aaii_sentiment",
        archive,
        [source],
        processed_hashes=set(),
    )[0]

    processed = finalize_import(queued, status="OK")

    assert processed.parent.name == "processed"
    assert processed.read_bytes() == source.read_bytes()
    assert not queued.exists()
    assert queue_import_candidates(
        "aaii_sentiment",
        archive,
        [source],
        processed_hashes=set(),
    ) == []

    other = tmp_path / "sentiment-new.xls"
    other.write_bytes(b"broken workbook")
    rejected_inbox = queue_import_candidates(
        "aaii_sentiment",
        archive,
        [other],
        processed_hashes=set(),
    )[0]
    rejected = finalize_import(rejected_inbox, status="PARSE_ERROR")

    assert rejected.parent.name == "rejected"
    assert queue_import_candidates(
        "aaii_sentiment",
        archive,
        [other],
        processed_hashes=set(),
    ) == []


def test_import_queue_respects_hashes_already_bound_by_ledger(tmp_path):
    archive = tmp_path / "archive"
    source = tmp_path / "sentiment.xls"
    source.write_bytes(b"legacy successful workbook")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    assert queue_import_candidates(
        "aaii_sentiment",
        archive,
        [source],
        processed_hashes={digest},
    ) == []
    assert source.exists()


def test_import_queue_rehashes_artifact_before_finalizing(tmp_path):
    archive = tmp_path / "archive"
    source = tmp_path / "sentiment.xls"
    source.write_bytes(b"official workbook")
    queued = queue_import_candidates(
        "aaii_sentiment",
        archive,
        [source],
        processed_hashes=set(),
    )[0]
    queued.write_bytes(b"tampered after staging")

    with pytest.raises(ValueError, match="content hash"):
        finalize_import(queued, status="OK")

    assert queued.exists()
    assert queue_import_candidates(
        "aaii_sentiment",
        archive,
        [],
        processed_hashes=set(),
    ) == []


def test_import_queue_finalizes_the_exact_verified_bytes_after_path_tampering(tmp_path):
    archive = tmp_path / "archive"
    source = tmp_path / "sentiment.xls"
    verified = b"official workbook"
    source.write_bytes(verified)
    queued = queue_import_candidates(
        "aaii_sentiment",
        archive,
        [source],
        processed_hashes=set(),
    )[0]
    queued.write_bytes(b"tampered after verification")

    processed = finalize_import(queued, status="OK", expected_content=verified)

    assert processed.parent.name == "processed"
    assert processed.read_bytes() == verified
    assert not queued.exists()
