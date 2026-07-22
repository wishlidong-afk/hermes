from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
from queue import Queue
import stat
from threading import Thread
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from hermes_escape_top.core.data.external_sources.ledger import (
    append_source_run,
    iter_source_runs,
    ledger_path,
    latest_source_run,
    source_reliability,
    source_status,
)
from hermes_escape_top.core.data.external_sources.registry import ExternalSourceSpec
from hermes_escape_top.core.data.external_sources.runner import (
    PreparedFrameAdapter,
    _official_metadata,
    run_external_source_refresh,
)
from hermes_escape_top.core.safe_io import PipelineBusy, pipeline_lock


class FakeAdapter:
    def fetch_raw(self):
        return {"rows": [{"date": "2026-06-30", "value": 1.2}]}

    def parse(self, raw):
        return pd.DataFrame(raw["rows"])


class MissingColumnAdapter:
    def fetch_raw(self):
        return {"rows": [{"date": "2026-06-30"}]}

    def parse(self, raw):
        return pd.DataFrame(raw["rows"])


class FetchBoomAdapter:
    def fetch_raw(self):
        raise RuntimeError("network down")

    def parse(self, raw):
        raise AssertionError("parse should not run")


class ParseBoomAdapter:
    def fetch_raw(self):
        return {"rows": [{"date": "2026-06-30", "value": 1.2}]}

    def parse(self, raw):
        raise ValueError("bad html")


class RoutedParseBoomAdapter:
    def fetch_raw(self):
        return {
            "url": "https://actual.example.test/feed",
            "rows": [{"date": "2026-06-30", "value": 1.2}],
        }

    def parse(self, raw):
        raise ValueError("bad routed payload")


class RoutedMissingColumnAdapter(RoutedParseBoomAdapter):
    def parse(self, raw):
        return pd.DataFrame([{"date": "2026-06-30"}])


class OfficialParseBoomAdapter:
    def fetch_raw(self):
        return {
            "file_name": "sentiment.xls",
            "content_sha256": "official-file-sha",
            "rows": [],
        }

    def parse(self, raw):
        raise ValueError("bad official workbook")


class ValueAdapter:
    def __init__(self, value: float) -> None:
        self.value = value

    def fetch_raw(self):
        return {"rows": [{"date": "2026-06-30", "value": self.value}]}

    def parse(self, raw):
        return pd.DataFrame(raw["rows"])


class SameRawParseBoomAdapter(ValueAdapter):
    def parse(self, raw):
        raise ValueError("same raw rejected by current parser")


class RowTimestampAdapter:
    def __init__(self, fetched_at: str) -> None:
        self.fetched_at = fetched_at

    def fetch_raw(self):
        return {
            "metadata": {"fetched_at": "transport-only"},
            "rows": [
                {
                    "date": "2026-06-30",
                    "value": 1.2,
                    "fetched_at": self.fetched_at,
                }
            ],
        }

    def parse(self, raw):
        return pd.DataFrame(raw["rows"])[["date", "value"]]


def test_official_filename_derived_from_url_excludes_query_credentials():
    metadata = _official_metadata(
        {
            "xlsx_url": (
                "https://www.naaim.org/data/latest.xlsx"
                "?token=official-file-secret&expires=9999999999"
            )
        },
        "2026-07-01",
    )

    assert metadata["official_file_name"] == "latest.xlsx"
    assert "official-file-secret" not in str(metadata)

def test_prepared_frame_adapter_still_promotes_only_through_runner(tmp_path):
    archive = tmp_path / "archive"
    target = tmp_path / "soft_history" / "legacy.csv"
    spec = ExternalSourceSpec(
        source_id="legacy_compat",
        target_path=target,
        required_columns=("date", "value"),
    )
    adapter = PreparedFrameAdapter(
        pd.DataFrame([{"date": "2026-07-15", "value": 1.5}]),
        source_channel="legacy_compatibility_entrypoint",
    )

    result = run_external_source_refresh(spec, adapter, archive)

    assert result.status == "OK"
    assert result.source_channel == "legacy_compatibility_entrypoint"
    assert pd.read_csv(target).to_dict("records") == [{"date": "2026-07-15", "value": 1.5}]


def test_runner_persists_normalized_source_provenance(tmp_path):
    class Adapter:
        def fetch_raw(self):
            return {
                "provenance": {
                    "source": "secondary_api",
                    "primary_source": "primary_api",
                    "fallback_used": True,
                    "primary_failure": "TimeoutError",
                },
                "rows": [{"date": "2026-07-17", "value": 1.0}],
            }

        def parse(self, raw):
            return pd.DataFrame(raw["rows"])

    spec = ExternalSourceSpec(
        source_id="provenance_test",
        target_path=tmp_path / "canonical.csv",
        required_columns=("date", "value"),
        min_rows=1,
    )

    result = run_external_source_refresh(spec, Adapter(), tmp_path / "archive")
    ledger = latest_source_run(tmp_path / "archive", "provenance_test")

    assert result.status == "OK"
    assert result.source_channel == "secondary_api"
    assert result.primary_source == "primary_api"
    assert result.fallback_used is True
    assert result.primary_failure == "TimeoutError"
    assert ledger["primary_source"] == "primary_api"


def test_runner_rejects_fallback_without_primary_failure(tmp_path):
    class Adapter:
        def fetch_raw(self):
            return {
                "provenance": {
                    "source": "secondary_api",
                    "primary_source": "primary_api",
                    "fallback_used": True,
                    "primary_failure": None,
                },
                "rows": [{"date": "2026-07-17", "value": 1.0}],
            }

        def parse(self, raw):
            return pd.DataFrame(raw["rows"])

    target = tmp_path / "canonical.csv"
    spec = ExternalSourceSpec(
        source_id="invalid_provenance",
        target_path=target,
        required_columns=("date", "value"),
        min_rows=1,
    )

    result = run_external_source_refresh(spec, Adapter(), tmp_path / "archive")

    assert result.status == "PARSE_ERROR"
    assert result.error_type == "ProvenanceError"
    assert "primary_failure" in str(result.error_message)
    assert not target.exists()


def test_runner_rejects_legacy_top_level_fallback_without_primary_failure(tmp_path):
    class Adapter:
        def fetch_raw(self):
            return {
                "source": "okx_failover",
                "primary_source": "deribit",
                "fallback_used": True,
                "rows": [{"date": "2026-07-17", "value": 1.0}],
            }

        def parse(self, raw):
            return pd.DataFrame(raw["rows"])

    target = tmp_path / "canonical.csv"
    spec = ExternalSourceSpec(
        source_id="invalid_legacy_provenance",
        target_path=target,
        required_columns=("date", "value"),
        min_rows=1,
    )

    result = run_external_source_refresh(spec, Adapter(), tmp_path / "archive")

    assert result.status == "PARSE_ERROR"
    assert result.error_type == "ProvenanceError"
    assert "primary_failure" in str(result.error_message)
    assert not target.exists()


def _ledger_record(source_id: str, status: str, when: str) -> dict:
    return {
        "source_id": source_id,
        "status": status,
        "started_at": when,
        "finished_at": when,
    }


def test_ledger_append_repairs_interrupted_tail_before_new_record(tmp_path):
    archive = tmp_path / "archive"
    first = _ledger_record("dollar", "OK", "2026-07-10T06:45:00+08:00")
    second = _ledger_record("aaii_sentiment", "OK", "2026-07-10T07:05:00+08:00")
    append_source_run(archive, first)
    path = ledger_path(archive)
    with path.open("ab") as handle:
        handle.write(b'{"source_id":"interrupted"')

    append_source_run(archive, second)

    rows = list(iter_source_runs(archive))
    assert [row["source_id"] for row in rows] == ["dollar", "aaii_sentiment"]
    assert path.read_bytes().endswith(b"\n")


def test_source_reliability_deduplicates_same_day_retries(tmp_path):
    archive = tmp_path / "archive"
    append_source_run(archive, _ledger_record("dollar", "FETCH_ERROR", "2026-07-10T06:45:00+08:00"))
    append_source_run(archive, _ledger_record("dollar", "OK", "2026-07-10T07:05:00+08:00"))
    append_source_run(archive, _ledger_record("dollar", "FETCH_ERROR", "2026-07-11T06:45:00+08:00"))
    append_source_run(archive, _ledger_record("dollar", "FETCH_ERROR", "2026-07-11T07:05:00+08:00"))
    append_source_run(archive, _ledger_record("dollar", "OK", "2026-07-12T06:45:00+08:00"))

    reliability = source_reliability(archive, "dollar", today=pd.Timestamp("2026-07-12").date())

    assert reliability["success_rate_30d"] == 66.67
    assert reliability["success_rate_90d"] == 66.67
    assert reliability["samples_30d"] == 3
    assert reliability["samples_90d"] == 3
    assert reliability["consecutive_failures"] == 0
    assert reliability["last_success_at"] == "2026-07-12T06:45:00+08:00"


def test_runner_records_stage_outcomes_and_canonical_advancement(tmp_path):
    target = tmp_path / "soft_history" / "dollar.csv"
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
    )

    fetch_error = run_external_source_refresh(spec, FetchBoomAdapter(), tmp_path / "archive")
    parse_error = run_external_source_refresh(spec, ParseBoomAdapter(), tmp_path / "archive")
    validation_error = run_external_source_refresh(spec, MissingColumnAdapter(), tmp_path / "archive")
    first_ok = run_external_source_refresh(spec, FakeAdapter(), tmp_path / "archive")
    second_ok = run_external_source_refresh(spec, FakeAdapter(), tmp_path / "archive")

    assert (
        fetch_error.transport_status,
        fetch_error.parse_status,
        fetch_error.validation_status,
        fetch_error.promotion_status,
    ) == ("ERROR", "NOT_RUN", "NOT_RUN", "NOT_RUN")
    assert (
        parse_error.transport_status,
        parse_error.parse_status,
        parse_error.validation_status,
        parse_error.promotion_status,
    ) == ("OK", "ERROR", "NOT_RUN", "NOT_RUN")
    assert (
        validation_error.transport_status,
        validation_error.parse_status,
        validation_error.validation_status,
        validation_error.promotion_status,
    ) == ("OK", "OK", "ERROR", "NOT_RUN")
    assert (
        first_ok.transport_status,
        first_ok.parse_status,
        first_ok.validation_status,
        first_ok.promotion_status,
    ) == ("OK", "OK", "OK", "OK")
    assert first_ok.previous_promoted_as_of is None
    assert first_ok.advanced is True
    assert second_ok.previous_promoted_as_of == "2026-06-30"
    assert second_ok.advanced is False


def test_source_reliability_reports_stage_rates_recovery_and_advancement(tmp_path):
    archive = tmp_path / "archive"
    first = _ledger_record("aaii_sentiment", "FETCH_ERROR", "2026-07-10T06:45:00+08:00")
    first.update(
        transport_status="ERROR",
        parse_status="NOT_RUN",
        validation_status="NOT_RUN",
        promotion_status="NOT_RUN",
        advanced=None,
    )
    recovered = _ledger_record("aaii_sentiment", "OK", "2026-07-11T06:45:00+08:00")
    recovered.update(
        transport_status="OK",
        parse_status="OK",
        validation_status="OK",
        promotion_status="OK",
        advanced=True,
        latest_promoted_as_of="2026-07-10",
    )
    unchanged = _ledger_record("aaii_sentiment", "OK", "2026-07-12T06:45:00+08:00")
    unchanged.update(
        transport_status="OK",
        parse_status="OK",
        validation_status="OK",
        promotion_status="UNCHANGED",
        advanced=False,
        latest_promoted_as_of="2026-07-10",
    )
    for row in (first, recovered, unchanged):
        append_source_run(archive, row)

    reliability = source_reliability(
        archive,
        "aaii_sentiment",
        today=pd.Timestamp("2026-07-12").date(),
    )

    assert reliability["stage_reliability"]["transport"] == {
        "success_rate_30d": 66.67,
        "success_rate_90d": 66.67,
        "samples_30d": 3,
        "samples_90d": 3,
        "consecutive_failures": 0,
        "evidence_status_30d": "INSUFFICIENT_EVIDENCE",
        "evidence_status_90d": "INSUFFICIENT_EVIDENCE",
    }
    assert reliability["stage_reliability"]["parse"]["success_rate_30d"] == 100.0
    assert reliability["stage_reliability"]["parse"]["samples_30d"] == 2
    assert reliability["stage_reliability"]["promotion"]["success_rate_30d"] == 100.0
    assert reliability["stage_reliability"]["promotion"]["consecutive_failures"] == 0
    assert reliability["last_recovery_at"] == "2026-07-11T06:45:00+08:00"
    assert reliability["advancement_rate_30d"] == 50.0
    assert reliability["advancement_samples_30d"] == 2
    assert reliability["last_advanced_at"] == "2026-07-11T06:45:00+08:00"
    assert reliability["expected_release_samples_30d"] == 1
    assert reliability["expected_release_advanced_30d"] == 1
    assert reliability["expected_release_advance_rate_30d"] == 100.0
    assert reliability["reliability_evidence_status_30d"] == "INSUFFICIENT_EVIDENCE"
    assert reliability["advancement_evidence_status_30d"] == "INSUFFICIENT_EVIDENCE"
    assert reliability["expected_release_evidence_status_30d"] == "INSUFFICIENT_EVIDENCE"
    assert reliability["latest_expected_release_date"] == "2026-07-10"
    assert reliability["latest_expected_release_status"] == "ADVANCED"


def test_expected_release_stays_pending_through_final_grace_day(tmp_path):
    archive = tmp_path / "archive"
    unchanged = _ledger_record("aaii_sentiment", "OK", "2026-07-10T06:45:00+08:00")
    unchanged.update(advanced=False, latest_promoted_as_of="2026-07-03")
    append_source_run(archive, unchanged)

    final_grace_day = source_reliability(
        archive,
        "aaii_sentiment",
        today=pd.Timestamp("2026-07-11").date(),
    )
    after_grace = source_reliability(
        archive,
        "aaii_sentiment",
        today=pd.Timestamp("2026-07-12").date(),
    )

    assert final_grace_day["expected_release_samples_30d"] == 0
    assert final_grace_day["latest_expected_release_status"] == "PENDING"
    assert after_grace["expected_release_samples_30d"] == 1
    assert after_grace["latest_expected_release_status"] == "MISSED"


def test_source_reliability_separates_primary_fallback_and_manual_channels(tmp_path):
    archive = tmp_path / "archive"
    primary = _ledger_record("aaii_sentiment", "OK", "2026-07-10T06:45:00+08:00")
    primary.update(source_channel="public_html", fallback_used=False, primary_failure=None)
    rescued = _ledger_record("aaii_sentiment", "OK", "2026-07-11T06:45:00+08:00")
    rescued.update(
        source_channel="official_insights_rss",
        fallback_used=True,
        primary_failure="blocked",
    )
    manual = _ledger_record("aaii_sentiment", "OK", "2026-07-12T06:45:00+08:00")
    manual.update(source_channel="manual_official_file", fallback_used=False, primary_failure=None)
    for row in (primary, rescued, manual):
        append_source_run(archive, row)

    reliability = source_reliability(
        archive,
        "aaii_sentiment",
        today=pd.Timestamp("2026-07-12").date(),
    )

    assert reliability["channel_successes_30d"] == {
        "manual_official_file": 1,
        "official_insights_rss": 1,
        "public_html": 1,
    }
    assert reliability["fallback_rescues_7d"] == 1
    assert reliability["primary_success_rate_30d"] == 33.33
    assert reliability["primary_samples_30d"] == 3
    assert reliability["latest_source_channel"] == "manual_official_file"
    assert reliability["latest_fallback_used"] is False


def test_source_status_exposes_daily_reliability_metrics(tmp_path):
    target = tmp_path / "soft_history" / "dollar.csv"
    spec = ExternalSourceSpec(source_id="dollar", target_path=target, required_columns=("date", "value"))
    archive = tmp_path / "archive"
    target.parent.mkdir(parents=True)
    target.write_text("date,value\n2026-06-30,1.2\n", encoding="utf-8")
    success = _ledger_record("dollar", "OK", "2026-07-12T06:45:00+08:00")
    success["latest_promoted_as_of"] = "2026-06-30"
    success["canonical_latest_as_of"] = "2026-06-30"
    append_source_run(archive, success)
    append_source_run(archive, _ledger_record("dollar", "FETCH_ERROR", "2026-07-13T07:05:00+08:00"))

    row = source_status(archive, [spec], today=pd.Timestamp("2026-07-13").date())["dollar"]

    assert row["samples_30d"] == 2
    assert row["success_rate_30d"] == 50.0
    assert row["reliability_evidence_status_30d"] == "INSUFFICIENT_EVIDENCE"
    assert row["consecutive_failures"] == 1
    assert row["last_success_at"]


def test_source_reliability_invalidates_same_input_success_rejected_later(tmp_path):
    archive = tmp_path / "archive"
    good = _ledger_record("dollar", "OK", "2026-07-13T06:45:00+08:00")
    good["input_hash"] = "same-raw"
    rejected = _ledger_record("dollar", "PARSE_ERROR", "2026-07-13T07:05:00+08:00")
    rejected["input_hash"] = "same-raw"
    append_source_run(archive, good)
    append_source_run(archive, rejected)

    reliability = source_reliability(archive, "dollar", today=pd.Timestamp("2026-07-13").date())

    assert reliability["success_rate_30d"] == 0.0
    assert reliability["consecutive_failures"] == 1


def test_success_writes_staging_promotes_target_and_records_ledger(tmp_path):
    target = tmp_path / "soft_history" / "dollar.csv"
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
    )

    run = run_external_source_refresh(spec, FakeAdapter(), tmp_path / "archive")

    assert run.status == "OK"
    assert target.read_text(encoding="utf-8").startswith("date,value")
    assert run.raw_path and Path(run.raw_path).exists()
    assert run.normalized_path and Path(run.normalized_path).exists()
    assert latest_source_run(tmp_path / "archive", "dollar")["status"] == "OK"


def test_identical_run_evidence_uses_independent_read_only_copies(tmp_path):
    archive = tmp_path / "archive"
    target = tmp_path / "soft_history" / "dollar.csv"
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
    )
    start = datetime(2026, 7, 16, 1, 0, tzinfo=timezone.utc)

    first = run_external_source_refresh(spec, FakeAdapter(), archive, now=start)
    second = run_external_source_refresh(
        spec,
        FakeAdapter(),
        archive,
        now=start + timedelta(seconds=1),
    )

    assert first.raw_path != second.raw_path
    assert first.normalized_path != second.normalized_path
    assert first.raw_sha256 == second.raw_sha256
    assert first.normalized_sha256 == second.normalized_sha256
    assert first.raw_blob_path == second.raw_blob_path
    assert first.normalized_blob_path == second.normalized_blob_path
    raw_blob = Path(first.raw_blob_path)
    normalized_blob = Path(first.normalized_blob_path)
    assert Path(first.raw_path).stat().st_ino != Path(second.raw_path).stat().st_ino
    assert Path(first.raw_path).stat().st_ino != raw_blob.stat().st_ino
    assert Path(first.normalized_path).stat().st_ino != Path(second.normalized_path).stat().st_ino
    assert Path(first.normalized_path).stat().st_ino != normalized_blob.stat().st_ino
    for path in (
        Path(first.raw_path),
        Path(second.raw_path),
        raw_blob,
        Path(first.normalized_path),
        Path(second.normalized_path),
        normalized_blob,
    ):
        assert stat.S_IMODE(path.stat().st_mode) & 0o222 == 0

    certified_raw = raw_blob.read_bytes()
    os.chmod(first.raw_path, 0o600)
    Path(first.raw_path).write_bytes(b"tampered run evidence")
    assert raw_blob.read_bytes() == certified_raw
    assert Path(second.raw_path).read_bytes() == certified_raw
    blobs = [path for path in (archive / "external_sources/blobs/sha256").rglob("*") if path.is_file()]
    assert len(blobs) == 2


def test_source_input_hash_keeps_row_level_fetched_at_business_field(tmp_path):
    target = tmp_path / "soft_history" / "source.csv"
    spec = ExternalSourceSpec(
        source_id="source",
        target_path=target,
        required_columns=("date", "value"),
    )

    first = run_external_source_refresh(
        spec,
        RowTimestampAdapter("2026-07-13T01:00:00Z"),
        tmp_path / "archive",
    )
    second = run_external_source_refresh(
        spec,
        RowTimestampAdapter("2026-07-13T02:00:00Z"),
        tmp_path / "archive",
    )

    assert first.input_hash != second.input_hash


def test_success_binds_canonical_hash_and_pit_evidence_to_ledger(tmp_path):
    target = tmp_path / "soft_history" / "dollar.csv"
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
        pit_rule="observation_date_plus_one_day",
        source_url="https://example.test/dollar",
    )

    run = run_external_source_refresh(spec, FakeAdapter(), tmp_path / "archive")
    latest = latest_source_run(tmp_path / "archive", "dollar")

    expected_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    assert run.canonical_sha256 == expected_hash
    assert latest["canonical_sha256"] == expected_hash
    assert latest["canonical_latest_as_of"] == "2026-06-30"
    assert latest["fetched_at"]
    assert latest["pit_rule"] == "observation_date_plus_one_day"
    assert latest["source_url"] == "https://example.test/dollar"


def test_success_without_official_file_evidence_does_not_invent_file_metadata(tmp_path):
    target = tmp_path / "soft_history" / "dollar.csv"
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
    )

    run_external_source_refresh(spec, FakeAdapter(), tmp_path / "archive")
    latest = latest_source_run(tmp_path / "archive", "dollar")

    assert latest["official_issue_as_of"] is None
    assert latest["official_file_name"] is None
    assert latest["official_file_sha256"] is None


def test_validation_failure_preserves_existing_target_and_records_error(tmp_path):
    target = tmp_path / "soft_history" / "dollar.csv"
    target.parent.mkdir(parents=True)
    target.write_text("date,value\n2026-06-29,9.9\n", encoding="utf-8")
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
    )

    run = run_external_source_refresh(spec, MissingColumnAdapter(), tmp_path / "archive")

    assert run.status == "VALIDATION_ERROR"
    assert "missing required columns" in str(run.error_message)
    assert target.read_text(encoding="utf-8") == "date,value\n2026-06-29,9.9\n"
    assert latest_source_run(tmp_path / "archive", "dollar")["status"] == "VALIDATION_ERROR"


def test_fetch_error_preserves_existing_target_and_records_error(tmp_path):
    target = tmp_path / "soft_history" / "dollar.csv"
    target.parent.mkdir(parents=True)
    target.write_text("date,value\n2026-06-29,9.9\n", encoding="utf-8")
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
    )

    run = run_external_source_refresh(spec, FetchBoomAdapter(), tmp_path / "archive")

    assert run.status == "FETCH_ERROR"
    assert run.raw_path is None
    assert "network down" in str(run.error_message)
    assert target.read_text(encoding="utf-8") == "date,value\n2026-06-29,9.9\n"
    assert latest_source_run(tmp_path / "archive", "dollar")["status"] == "FETCH_ERROR"


def test_runner_detaches_legacy_hardlinked_blobs_once_under_lock(tmp_path):
    archive = tmp_path / "archive"
    content = b'{"legacy":true}\n'
    digest = hashlib.sha256(content).hexdigest()
    blob = (
        archive
        / "external_sources/blobs/sha256"
        / digest[:2]
        / f"{digest}.json"
    )
    legacy_run = archive / "external_sources/dollar/legacy/raw.json"
    blob.parent.mkdir(parents=True)
    legacy_run.parent.mkdir(parents=True)
    blob.write_bytes(content)
    os.link(blob, legacy_run)
    assert blob.stat().st_ino == legacy_run.stat().st_ino

    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=tmp_path / "soft_history/dollar.csv",
        required_columns=("date", "value"),
    )
    run = run_external_source_refresh(spec, FakeAdapter(), archive)

    marker = archive / "external_sources/blobs/.independent-readonly-v1.json"
    report = json.loads(marker.read_text(encoding="utf-8"))
    assert run.status == "OK"
    assert report["schema_version"] == "hermes-evidence-inode-migration-v1"
    assert report["scanned_blob_count"] == 1
    assert report["detached_blob_count"] == 1
    assert blob.stat().st_ino != legacy_run.stat().st_ino
    assert stat.S_IMODE(blob.stat().st_mode) == 0o444
    legacy_run.chmod(0o644)
    legacy_run.write_bytes(b"mutated legacy run\n")
    assert blob.read_bytes() == content


def test_parse_error_preserves_existing_target_and_records_raw_artifact(tmp_path):
    target = tmp_path / "soft_history" / "dollar.csv"
    target.parent.mkdir(parents=True)
    target.write_text("date,value\n2026-06-29,9.9\n", encoding="utf-8")
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
    )

    run = run_external_source_refresh(spec, ParseBoomAdapter(), tmp_path / "archive")

    assert run.status == "PARSE_ERROR"
    assert run.raw_path and Path(run.raw_path).exists()
    assert run.normalized_path is None
    assert "bad html" in str(run.error_message)
    assert target.read_text(encoding="utf-8") == "date,value\n2026-06-29,9.9\n"
    assert latest_source_run(tmp_path / "archive", "dollar")["status"] == "PARSE_ERROR"


@pytest.mark.parametrize(
    ("adapter", "expected_status"),
    [
        (RoutedParseBoomAdapter(), "PARSE_ERROR"),
        (RoutedMissingColumnAdapter(), "VALIDATION_ERROR"),
    ],
)
def test_failure_after_fetch_keeps_actual_route_and_pit_evidence(tmp_path, adapter, expected_status):
    spec = ExternalSourceSpec(
        source_id="routed",
        target_path=tmp_path / "routed.csv",
        required_columns=("date", "value"),
        pit_rule="artifact_publish_date",
        source_url="https://configured.example.test/landing",
    )

    run = run_external_source_refresh(spec, adapter, tmp_path / "archive")

    assert run.status == expected_status
    assert run.source_url == "https://actual.example.test/feed"
    assert run.pit_rule == "artifact_publish_date"
    assert run.fetched_at


def test_parse_error_persists_official_file_identity_in_ledger(tmp_path):
    target = tmp_path / "soft_history" / "aaii_sentiment.csv"
    spec = ExternalSourceSpec(
        source_id="aaii_sentiment",
        target_path=target,
        required_columns=("date", "value"),
    )

    run = run_external_source_refresh(
        spec,
        OfficialParseBoomAdapter(),
        tmp_path / "archive",
    )

    assert run.status == "PARSE_ERROR"
    assert run.official_file_name == "sentiment.xls"
    assert run.official_file_sha256 == "official-file-sha"
    latest = latest_source_run(tmp_path / "archive", "aaii_sentiment")
    assert latest["official_file_sha256"] == "official-file-sha"


def test_stale_source_frame_preserves_newer_existing_target(tmp_path):
    target = tmp_path / "soft_history" / "dollar.csv"
    target.parent.mkdir(parents=True)
    target.write_text("date,value\n2026-07-07,9.9\n", encoding="utf-8")
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
    )

    run = run_external_source_refresh(spec, FakeAdapter(), tmp_path / "archive")

    assert run.status == "VALIDATION_ERROR"
    assert "older than existing target" in str(run.error_message)
    assert target.read_text(encoding="utf-8") == "date,value\n2026-07-07,9.9\n"
    assert latest_source_run(tmp_path / "archive", "dollar")["status"] == "VALIDATION_ERROR"


def test_same_date_source_records_unchanged_without_replacing_canonical(tmp_path):
    target = tmp_path / "soft_history" / "dollar.csv"
    target.parent.mkdir(parents=True)
    target.write_text("date,value\n2026-06-30,9.9\n", encoding="utf-8")
    before = target.read_bytes()
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
    )

    run = run_external_source_refresh(spec, FakeAdapter(), tmp_path / "archive")

    assert run.status == "OK"
    assert run.promotion_status == "UNCHANGED"
    assert run.advanced is False
    assert run.previous_promoted_as_of == "2026-06-30"
    assert run.latest_promoted_as_of == "2026-06-30"
    assert target.read_bytes() == before


def test_runner_direct_call_honors_pipeline_lock(tmp_path):
    archive = tmp_path / "archive"
    target = tmp_path / "soft_history" / "dollar.csv"
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
    )
    outcome: Queue[BaseException | str] = Queue()

    def attempt_refresh() -> None:
        try:
            run_external_source_refresh(
                spec,
                FakeAdapter(),
                archive,
                lock_timeout=0,
            )
        except BaseException as exc:
            outcome.put(exc)
        else:
            outcome.put("unexpected success")

    lock_path = archive / ".pipeline.lock"
    with pipeline_lock(path=lock_path):
        thread = Thread(target=attempt_refresh)
        thread.start()
        thread.join(timeout=2)

    assert not thread.is_alive()
    assert isinstance(outcome.get_nowait(), PipelineBusy)


def test_source_status_reports_latest_run_and_promoted_date(tmp_path):
    target = tmp_path / "soft_history" / "dollar.csv"
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
    )

    run_external_source_refresh(spec, FakeAdapter(), tmp_path / "archive")
    status = source_status(tmp_path / "archive", [spec])

    assert status["dollar"]["status"] == "OK"
    assert status["dollar"]["latest_promoted_as_of"] == "2026-06-30"
    assert status["dollar"]["evidence_status"] == "MATCH"


def test_source_status_detects_canonical_bytes_changed_after_promotion(tmp_path):
    target = tmp_path / "soft_history" / "dollar.csv"
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
    )
    archive = tmp_path / "archive"
    run_external_source_refresh(spec, FakeAdapter(), archive)

    target.write_text("date,value\n2026-06-30,999\n", encoding="utf-8")
    row = source_status(archive, [spec])["dollar"]

    assert row["evidence_status"] == "EVIDENCE_DRIFT"
    assert "sha256" in row["evidence_detail"]


def test_source_status_blocks_legacy_success_without_canonical_hash(tmp_path):
    target = tmp_path / "soft_history" / "dollar.csv"
    target.parent.mkdir(parents=True)
    target.write_text("date,value\n2026-06-30,999\n", encoding="utf-8")
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
    )
    archive = tmp_path / "archive"
    append_source_run(
        archive,
        {
            "source_id": "dollar",
            "status": "OK",
            "latest_promoted_as_of": "2026-06-30",
        },
    )

    row = source_status(archive, [spec])["dollar"]

    assert row["evidence_status"] == "UNBOUND_LEGACY"
    assert "sha256" in row["evidence_detail"]


def test_source_status_reports_missing_canonical_after_promotion(tmp_path):
    target = tmp_path / "soft_history" / "dollar.csv"
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
    )
    archive = tmp_path / "archive"
    run_external_source_refresh(spec, FakeAdapter(), archive)
    target.unlink()

    row = source_status(archive, [spec])["dollar"]

    assert row["evidence_status"] == "MISSING_CANONICAL"


def test_semantic_validation_failure_preserves_existing_target(tmp_path):
    target = tmp_path / "soft_history" / "dollar.csv"
    target.parent.mkdir(parents=True)
    target.write_text("date,value\n2026-06-29,1.0\n", encoding="utf-8")
    before = target.read_bytes()
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
        semantic_validator=lambda frame: "value outside policy" if frame["value"].max() > 1 else None,
    )

    run = run_external_source_refresh(spec, FakeAdapter(), tmp_path / "archive")

    assert run.status == "VALIDATION_ERROR"
    assert run.error_message == "value outside policy"
    assert target.read_bytes() == before


def test_ledger_commit_failure_restores_previous_canonical(monkeypatch, tmp_path):
    target = tmp_path / "soft_history" / "dollar.csv"
    target.parent.mkdir(parents=True)
    target.write_text("date,value\n2026-06-29,1.0\n", encoding="utf-8")
    target.chmod(0o640)
    before = target.read_bytes()

    def fail_ledger(*_args, **_kwargs):
        raise OSError("ledger unavailable")

    monkeypatch.setattr(
        "hermes_escape_top.core.data.external_sources.runner.append_source_run",
        fail_ledger,
    )
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
    )

    with pytest.raises(OSError, match="ledger unavailable"):
        run_external_source_refresh(spec, FakeAdapter(), tmp_path / "archive")

    assert target.read_bytes() == before
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_source_status_prefers_latest_success_when_latest_attempt_failed(tmp_path):
    target = tmp_path / "soft_history" / "dollar.csv"
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
    )

    run_external_source_refresh(spec, FakeAdapter(), tmp_path / "archive")
    run_external_source_refresh(spec, FetchBoomAdapter(), tmp_path / "archive")
    status = source_status(tmp_path / "archive", [spec])

    assert latest_source_run(tmp_path / "archive", "dollar")["status"] == "FETCH_ERROR"
    assert status["dollar"]["status"] == "OK"
    assert status["dollar"]["latest_promoted_as_of"] == "2026-06-30"
    assert status["dollar"]["latest_attempt_status"] == "FETCH_ERROR"
    assert "network down" in status["dollar"]["latest_attempt_error_message"]


def test_source_status_ignores_success_invalidated_by_later_same_input_failure(tmp_path):
    target = tmp_path / "soft_history" / "dollar.csv"
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
    )

    good_run = run_external_source_refresh(spec, ValueAdapter(1.2), tmp_path / "archive")
    invalidated_run = run_external_source_refresh(spec, ValueAdapter(2.4), tmp_path / "archive")
    failed_rerun = run_external_source_refresh(spec, SameRawParseBoomAdapter(2.4), tmp_path / "archive")
    status = source_status(tmp_path / "archive", [spec])

    assert failed_rerun.status == "PARSE_ERROR"
    assert failed_rerun.input_hash == invalidated_run.input_hash
    assert status["dollar"]["status"] == "OK"
    assert status["dollar"]["input_hash"] == good_run.input_hash
    assert status["dollar"]["input_hash"] != invalidated_run.input_hash
    assert status["dollar"]["latest_attempt_status"] == "PARSE_ERROR"
    assert "same raw rejected" in status["dollar"]["latest_attempt_error_message"]
