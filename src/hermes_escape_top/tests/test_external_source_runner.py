from __future__ import annotations

from pathlib import Path

import pandas as pd

from hermes_escape_top.core.data.external_sources.ledger import latest_source_run, source_status
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
