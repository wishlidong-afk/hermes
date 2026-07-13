from __future__ import annotations

from pathlib import Path
import hashlib

import pandas as pd

from hermes_escape_top.core.data.external_sources.ledger import (
    append_source_run,
    latest_source_run,
    source_reliability,
    source_status,
)
from hermes_escape_top.core.data.external_sources.registry import ExternalSourceSpec
from hermes_escape_top.core.data.external_sources.runner import run_external_source_refresh


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


def _ledger_record(source_id: str, status: str, when: str) -> dict:
    return {
        "source_id": source_id,
        "status": status,
        "started_at": when,
        "finished_at": when,
    }


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
