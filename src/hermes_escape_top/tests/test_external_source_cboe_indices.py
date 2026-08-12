from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from hermes_escape_top.core.data.external_sources.ledger import source_status
from hermes_escape_top.core.data.external_sources.runner import run_external_source_refresh
from hermes_escape_top.core.data.external_sources.cboe_indices import (
    CBOE_INDEX_DEFINITIONS,
    CboeVolatilityIndexAdapter,
    cboe_index_spec,
    parse_cboe_index_csv,
)
from hermes_escape_top.scripts import refresh_external
from hermes_escape_top.scripts import backfill_history
from hermes_escape_top.scripts.backfill_history import all_backfill_symbols


OHLC_CSV = """DATE,OPEN,HIGH,LOW,CLOSE
07/09/2026,16.58,17.27,15.76,15.84
07/10/2026,16.06,16.16,14.96,15.03
07/13/2026,16.32,17.41,16.03,17.16
"""

CLOSE_ONLY_CSV = """DATE,VVIX
07/09/2026,88.78
07/10/2026,87.28
07/13/2026,95.28
"""


def _witness(date: str = "2026-07-13", close: float = 17.16) -> pd.DataFrame:
    return pd.DataFrame(
        {"Close": [close]},
        index=pd.DatetimeIndex([pd.Timestamp(date)], name="Date"),
    )


def _validation_evidence(run) -> dict[str, object]:
    assert run.validation_path is not None
    return json.loads(Path(run.validation_path).read_text(encoding="utf-8"))


def test_parse_cboe_ohlc_and_close_only_files_into_history_schema():
    vix = parse_cboe_index_csv(CBOE_INDEX_DEFINITIONS["cboe_vix"], OHLC_CSV)
    vvix = parse_cboe_index_csv(CBOE_INDEX_DEFINITIONS["cboe_vvix"], CLOSE_ONLY_CSV)

    assert list(vix.columns) == ["date", "open", "high", "low", "close", "adj_close", "volume"]
    assert vix.iloc[-1].to_dict() == {
        "date": "2026-07-13",
        "open": 16.32,
        "high": 17.41,
        "low": 16.03,
        "close": 17.16,
        "adj_close": 17.16,
        "volume": 0.0,
    }
    assert vvix.iloc[-1][["open", "high", "low", "close", "adj_close"]].tolist() == [
        95.28,
        95.28,
        95.28,
        95.28,
        95.28,
    ]


def test_parse_repairs_invalid_official_ohlc_from_same_rows_official_close():
    frame = parse_cboe_index_csv(
        CBOE_INDEX_DEFINITIONS["cboe_vix"],
        "DATE,OPEN,HIGH,LOW,CLOSE\n02/08/2006,41.60,13.61,12.76,12.83\n",
    )

    assert frame.iloc[0][["open", "high", "low", "close"]].tolist() == [
        12.83,
        12.83,
        12.83,
        12.83,
    ]
    assert frame.attrs["ohlc_repair_count"] == 1


def test_adapter_filters_unfinished_session_and_binds_official_file_evidence():
    csv_text = OHLC_CSV + "07/14/2026,18.00,19.00,17.00,18.50\n"
    adapter = CboeVolatilityIndexAdapter(
        CBOE_INDEX_DEFINITIONS["cboe_vix"],
        fetch_text=lambda _url: csv_text,
        fetch_witness=lambda *_args: _witness(),
        now=datetime(2026, 7, 14, 15, 0, tzinfo=timezone.utc),
    )

    raw = adapter.fetch_raw()
    frame = adapter.parse(raw)

    assert frame["date"].tolist() == ["2026-07-09", "2026-07-10", "2026-07-13"]
    assert raw["file_name"] == "VIX_History.csv"
    assert len(raw["content_sha256"]) == 64
    assert raw["completed_through"] == "2026-07-13"
    assert raw["provenance"] == {
        "source": "cboe_official_history",
        "primary_source": "cboe_official_history",
        "fallback_used": False,
        "primary_failure": None,
    }


def test_adapter_handles_witness_older_than_official_history_without_crashing():
    adapter = CboeVolatilityIndexAdapter(
        CBOE_INDEX_DEFINITIONS["cboe_vix"],
        fetch_text=lambda _url: OHLC_CSV,
        fetch_witness=lambda *_args: _witness(date="2000-01-03", close=20.0),
        now=datetime(2026, 7, 14, 2, 0, tzinfo=timezone.utc),
    )

    frame = adapter.parse(adapter.fetch_raw())

    assert frame.empty
    assert frame.attrs["unconfirmed_tail_trimmed"] is True


def test_yahoo_witness_mismatch_freezes_previous_canonical_and_records_failure(tmp_path):
    target = tmp_path / "history" / "_VIX.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-07-10,16.06,16.16,14.96,15.03,15.03,0\n",
        encoding="utf-8",
    )
    before = target.read_bytes()
    definition = CBOE_INDEX_DEFINITIONS["cboe_vix"]
    adapter = CboeVolatilityIndexAdapter(
        definition,
        fetch_text=lambda _url: OHLC_CSV,
        fetch_witness=lambda *_args: _witness(close=30.0),
        now=datetime(2026, 7, 14, 2, 0, tzinfo=timezone.utc),
        seed_path=target,
    )

    run = run_external_source_refresh(
        cboe_index_spec(definition, target, min_rows=1),
        adapter,
        tmp_path / "archive",
        now=datetime(2026, 7, 14, 2, 1, tzinfo=timezone.utc),
    )

    assert run.status == "VALIDATION_ERROR"
    assert "Yahoo witness mismatch" in str(run.error_message)
    assert target.read_bytes() == before


def test_lagging_yahoo_witness_trims_unconfirmed_official_tail(tmp_path):
    target = tmp_path / "history" / "_VIX.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-07-09,16.58,17.27,15.76,15.84,15.84,0\n"
        "2026-07-10,16.06,16.16,14.96,15.03,15.03,0\n",
        encoding="utf-8",
    )
    adapter = CboeVolatilityIndexAdapter(
        CBOE_INDEX_DEFINITIONS["cboe_vix"],
        fetch_text=lambda _url: OHLC_CSV,
        fetch_witness=lambda *_args: _witness(date="2026-07-10", close=15.03),
        now=datetime(2026, 7, 14, 2, 0, tzinfo=timezone.utc),
        seed_path=target,
    )

    run = run_external_source_refresh(
        cboe_index_spec(CBOE_INDEX_DEFINITIONS["cboe_vix"], target, min_rows=1),
        adapter,
        tmp_path / "archive",
    )

    assert run.status == "OK"
    assert run.latest_promoted_as_of == "2026-07-10"
    assert pd.read_csv(target)["date"].astype(str).tolist() == [
        "2026-07-09",
        "2026-07-10",
    ]


def test_regressed_yahoo_witness_preserves_matching_certified_tail(tmp_path):
    target = tmp_path / "history" / "_VIX3M.csv"
    target.parent.mkdir(parents=True)
    csv_text = (
        "DATE,OPEN,HIGH,LOW,CLOSE\n"
        "07/09/2026,16,16,16,16\n"
        "07/10/2026,15,15,15,15\n"
        "07/13/2026,17,17,17,17\n"
        "07/14/2026,18,18,18,18\n"
        "07/15/2026,19,19,19,19\n"
        "07/16/2026,20,20,20,20\n"
        "07/17/2026,21,21,21,21\n"
    )
    definition = CBOE_INDEX_DEFINITIONS["cboe_vix3m"]
    parse_cboe_index_csv(definition, csv_text).to_csv(target, index=False)
    before = target.read_bytes()
    adapter = CboeVolatilityIndexAdapter(
        definition,
        fetch_text=lambda _url: csv_text,
        fetch_witness=lambda *_args: _witness(date="2026-07-10", close=15.0),
        now=datetime(2026, 7, 18, 22, 0, tzinfo=timezone.utc),
        seed_path=target,
    )

    run = run_external_source_refresh(
        cboe_index_spec(definition, target, min_rows=1),
        adapter,
        tmp_path / "archive",
    )

    assert run.status == "OK"
    assert run.latest_promoted_as_of == "2026-07-17"
    assert run.advanced is False
    assert target.read_bytes() == before


def test_regressed_yahoo_witness_rejects_changed_certified_tail(tmp_path):
    target = tmp_path / "history" / "_VIX3M.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-07-09,16,16,16,16,16,0\n"
        "2026-07-10,15,15,15,15,15,0\n"
        "2026-07-13,17,17,17,17,17,0\n",
        encoding="utf-8",
    )
    before = target.read_bytes()
    csv_text = (
        "DATE,OPEN,HIGH,LOW,CLOSE\n"
        "07/09/2026,16,16,16,16\n"
        "07/10/2026,15,15,15,15\n"
        "07/13/2026,17.5,17.5,17.5,17.5\n"
    )
    definition = CBOE_INDEX_DEFINITIONS["cboe_vix3m"]
    adapter = CboeVolatilityIndexAdapter(
        definition,
        fetch_text=lambda _url: csv_text,
        fetch_witness=lambda *_args: _witness(date="2026-07-10", close=15.0),
        now=datetime(2026, 7, 14, 22, 0, tzinfo=timezone.utc),
        seed_path=target,
    )

    run = run_external_source_refresh(
        cboe_index_spec(definition, target, min_rows=1),
        adapter,
        tmp_path / "archive",
    )

    assert run.status == "VALIDATION_ERROR"
    assert "changed existing row 2026-07-13" in str(run.error_message)
    assert target.read_bytes() == before


def test_empty_yahoo_witness_freezes_previous_canonical(tmp_path):
    target = tmp_path / "history" / "_VIX.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-07-10,16.06,16.16,14.96,15.03,15.03,0\n",
        encoding="utf-8",
    )
    before = target.read_bytes()
    adapter = CboeVolatilityIndexAdapter(
        CBOE_INDEX_DEFINITIONS["cboe_vix"],
        fetch_text=lambda _url: OHLC_CSV,
        fetch_witness=lambda *_args: pd.DataFrame(),
        now=datetime(2026, 7, 14, 2, 0, tzinfo=timezone.utc),
    )

    run = run_external_source_refresh(
        cboe_index_spec(CBOE_INDEX_DEFINITIONS["cboe_vix"], target, min_rows=1),
        adapter,
        tmp_path / "archive",
    )

    assert run.status == "VALIDATION_ERROR"
    assert "Yahoo witness unavailable" in str(run.error_message)
    assert target.read_bytes() == before


def test_truncated_official_history_cannot_replace_longer_canonical(tmp_path):
    target = tmp_path / "history" / "_VIX.csv"
    target.parent.mkdir(parents=True)
    dates = pd.bdate_range("2026-01-02", periods=100)
    existing = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "open": 20.0,
            "high": 20.0,
            "low": 20.0,
            "close": 20.0,
            "adj_close": 20.0,
            "volume": 0.0,
        }
    )
    existing.to_csv(target, index=False)
    before = target.read_bytes()
    incoming_dates = dates[-60:]
    csv_text = "DATE,OPEN,HIGH,LOW,CLOSE\n" + "".join(
        f"{day.strftime('%m/%d/%Y')},20,20,20,20\n" for day in incoming_dates
    )
    adapter = CboeVolatilityIndexAdapter(
        CBOE_INDEX_DEFINITIONS["cboe_vix"],
        fetch_text=lambda _url: csv_text,
        fetch_witness=lambda *_args: _witness(
            date=incoming_dates[-1].strftime("%Y-%m-%d"),
            close=20.0,
        ),
        now=datetime(2026, 7, 14, 22, 0, tzinfo=timezone.utc),
    )

    run = run_external_source_refresh(
        cboe_index_spec(CBOE_INDEX_DEFINITIONS["cboe_vix"], target, min_rows=1),
        adapter,
        tmp_path / "archive",
    )

    assert run.status == "VALIDATION_ERROR"
    assert "history continuity" in str(run.error_message)
    assert target.read_bytes() == before


def test_official_history_missing_existing_middle_date_is_rejected(tmp_path):
    target = tmp_path / "history" / "_VIX.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-07-09,16,16,16,16,16,0\n"
        "2026-07-10,15,15,15,15,15,0\n"
        "2026-07-13,17,17,17,17,17,0\n",
        encoding="utf-8",
    )
    before = target.read_bytes()
    csv_text = (
        "DATE,OPEN,HIGH,LOW,CLOSE\n"
        "07/09/2026,16,16,16,16\n"
        "07/13/2026,17,17,17,17\n"
    )
    adapter = CboeVolatilityIndexAdapter(
        CBOE_INDEX_DEFINITIONS["cboe_vix"],
        fetch_text=lambda _url: csv_text,
        fetch_witness=lambda *_args: _witness(date="2026-07-13", close=17.0),
        now=datetime(2026, 7, 14, 22, 0, tzinfo=timezone.utc),
        seed_path=target,
    )

    run = run_external_source_refresh(
        cboe_index_spec(CBOE_INDEX_DEFINITIONS["cboe_vix"], target, min_rows=1),
        adapter,
        tmp_path / "archive",
    )

    assert run.status == "VALIDATION_ERROR"
    assert "missing 1 existing dates" in str(run.error_message)
    assert target.read_bytes() == before


def test_controlled_initial_rebaseline_is_explicit_in_ledger_pit_rule(tmp_path):
    target = tmp_path / "history" / "_VIX.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-07-09,16,16,16,16,16,0\n"
        "2026-07-10,15,15,15,15,15,0\n"
        "2026-07-13,17,17,17,17,17,0\n",
        encoding="utf-8",
    )
    csv_text = (
        "DATE,OPEN,HIGH,LOW,CLOSE\n"
        "07/09/2026,16,16,16,16\n"
        "07/13/2026,17,17,17,17\n"
    )
    definition = CBOE_INDEX_DEFINITIONS["cboe_vix"]
    adapter = CboeVolatilityIndexAdapter(
        definition,
        fetch_text=lambda _url: csv_text,
        fetch_witness=lambda *_args: _witness(date="2026-07-13", close=17.0),
        now=datetime(2026, 7, 14, 22, 0, tzinfo=timezone.utc),
    )

    run = run_external_source_refresh(
        cboe_index_spec(
            definition,
            target,
            min_rows=1,
            allow_initial_rebaseline=True,
        ),
        adapter,
        tmp_path / "archive",
    )

    assert run.status == "OK"
    assert run.pit_rule == "controlled_initial_rebaseline_then_daily_witness"
    assert pd.read_csv(target)["date"].astype(str).tolist() == [
        "2026-07-09",
        "2026-07-13",
    ]


def test_daily_continuity_rejects_changed_existing_cboe_row(tmp_path):
    target = tmp_path / "history" / "_VIX.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-07-09,16,16,16,16,16,0\n"
        "2026-07-10,15,15,15,15,15,0\n",
        encoding="utf-8",
    )
    before = target.read_bytes()
    csv_text = (
        "DATE,OPEN,HIGH,LOW,CLOSE\n"
        "07/09/2026,16.5,16.5,16.5,16.5\n"
        "07/10/2026,15,15,15,15\n"
    )
    definition = CBOE_INDEX_DEFINITIONS["cboe_vix"]
    adapter = CboeVolatilityIndexAdapter(
        definition,
        fetch_text=lambda _url: csv_text,
        fetch_witness=lambda *_args: _witness(date="2026-07-10", close=15.0),
        now=datetime(2026, 7, 14, 2, 0, tzinfo=timezone.utc),
        seed_path=target,
    )

    run = run_external_source_refresh(
        cboe_index_spec(definition, target, min_rows=1),
        adapter,
        tmp_path / "archive",
    )

    assert run.status == "VALIDATION_ERROR"
    assert "changed existing row" in str(run.error_message)
    assert target.read_bytes() == before


def test_historical_ohlc_revision_is_quarantined_while_new_tail_advances(tmp_path):
    target = tmp_path / "history" / "_VIX3M.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2013-10-30,15.13,15.13,15.13,15.13,15.13,0\n"
        "2026-07-22,18,18,18,18,18,0\n",
        encoding="utf-8",
    )
    csv_text = (
        "DATE,OPEN,HIGH,LOW,CLOSE\n"
        "10/30/2013,14.68,15.45,14.68,15.13\n"
        "07/22/2026,18,18,18,18\n"
        "07/23/2026,19,19,19,19\n"
        "07/24/2026,20,20,20,20\n"
    )
    definition = CBOE_INDEX_DEFINITIONS["cboe_vix3m"]
    adapter = CboeVolatilityIndexAdapter(
        definition,
        fetch_text=lambda _url: csv_text,
        fetch_witness=lambda *_args: _witness(date="2026-07-24", close=20.0),
        now=datetime(2026, 7, 25, 22, 0, tzinfo=timezone.utc),
        seed_path=target,
    )

    run = run_external_source_refresh(
        cboe_index_spec(definition, target, min_rows=1),
        adapter,
        tmp_path / "archive",
    )

    canonical = pd.read_csv(target)
    old_row = canonical[canonical["date"] == "2013-10-30"].iloc[0]
    evidence = _validation_evidence(run)["history_revision"]
    status = source_status(
        tmp_path / "archive",
        [cboe_index_spec(definition, target, min_rows=1)],
    )["cboe_vix3m"]
    assert run.status == "OK"
    assert run.advanced is True
    assert run.latest_promoted_as_of == "2026-07-24"
    assert run.history_revision_status == "QUARANTINED"
    assert run.history_revision_count == 3
    assert status["history_revision_status"] == "QUARANTINED"
    assert status["history_revision_count"] == 3
    assert status["history_revision_fingerprint"] == evidence["fingerprint"]
    assert old_row[["open", "high", "low", "close"]].tolist() == [
        15.13,
        15.13,
        15.13,
        15.13,
    ]
    assert canonical["date"].tolist()[-2:] == ["2026-07-23", "2026-07-24"]
    assert evidence["status"] == "QUARANTINED"
    assert evidence["changed_dates"] == ["2013-10-30"]
    assert evidence["appended_dates"] == ["2026-07-23", "2026-07-24"]


def test_lagging_witness_quarantines_revision_without_rewriting_certified_tail(
    tmp_path,
):
    target = tmp_path / "history" / "_VIX3M.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2013-10-30,15.13,15.13,15.13,15.13,15.13,0\n"
        "2026-07-17,17,17,17,17,17,0\n"
        "2026-07-22,18,18,18,18,18,0\n",
        encoding="utf-8",
    )
    before = target.read_bytes()
    csv_text = (
        "DATE,OPEN,HIGH,LOW,CLOSE\n"
        "10/30/2013,14.68,15.45,14.68,15.13\n"
        "07/17/2026,17,17,17,17\n"
        "07/22/2026,18,18,18,18\n"
        "07/23/2026,19,19,19,19\n"
        "07/24/2026,20,20,20,20\n"
    )
    definition = CBOE_INDEX_DEFINITIONS["cboe_vix3m"]
    adapter = CboeVolatilityIndexAdapter(
        definition,
        fetch_text=lambda _url: csv_text,
        fetch_witness=lambda *_args: _witness(date="2026-07-17", close=17.0),
        now=datetime(2026, 7, 25, 22, 0, tzinfo=timezone.utc),
        seed_path=target,
    )

    run = run_external_source_refresh(
        cboe_index_spec(definition, target, min_rows=1),
        adapter,
        tmp_path / "archive",
    )

    evidence = _validation_evidence(run)["history_revision"]
    assert run.status == "OK"
    assert run.promotion_status == "UNCHANGED"
    assert run.advanced is False
    assert run.history_revision_status == "QUARANTINED"
    assert run.history_revision_count == 3
    assert evidence["changed_dates"] == ["2013-10-30"]
    assert evidence["appended_dates"] == []
    assert target.read_bytes() == before


def test_historical_close_revision_is_blocked_and_canonical_is_unchanged(tmp_path):
    target = tmp_path / "history" / "_VIX3M.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2013-10-30,15.13,15.13,15.13,15.13,15.13,0\n"
        "2026-07-22,18,18,18,18,18,0\n",
        encoding="utf-8",
    )
    before = target.read_bytes()
    csv_text = (
        "DATE,OPEN,HIGH,LOW,CLOSE\n"
        "10/30/2013,15.14,15.14,15.14,15.14\n"
        "07/22/2026,18,18,18,18\n"
        "07/23/2026,19,19,19,19\n"
    )
    definition = CBOE_INDEX_DEFINITIONS["cboe_vix3m"]
    adapter = CboeVolatilityIndexAdapter(
        definition,
        fetch_text=lambda _url: csv_text,
        fetch_witness=lambda *_args: _witness(date="2026-07-23", close=19.0),
        now=datetime(2026, 7, 24, 22, 0, tzinfo=timezone.utc),
        seed_path=target,
    )

    run = run_external_source_refresh(
        cboe_index_spec(definition, target, min_rows=1),
        adapter,
        tmp_path / "archive",
    )

    evidence = _validation_evidence(run)["history_revision"]
    assert run.status == "VALIDATION_ERROR"
    assert "certified close revision" in str(run.error_message)
    assert run.history_revision_status == "BLOCKED"
    assert evidence["status"] == "BLOCKED"
    assert target.read_bytes() == before


def test_unchanged_official_history_records_no_revision_and_does_not_rewrite(tmp_path):
    target = tmp_path / "history" / "_VIX3M.csv"
    target.parent.mkdir(parents=True)
    csv_text = (
        "DATE,OPEN,HIGH,LOW,CLOSE\n"
        "07/21/2026,17,17,17,17\n"
        "07/22/2026,18,18,18,18\n"
    )
    definition = CBOE_INDEX_DEFINITIONS["cboe_vix3m"]
    parse_cboe_index_csv(definition, csv_text).to_csv(target, index=False)
    before = target.read_bytes()
    adapter = CboeVolatilityIndexAdapter(
        definition,
        fetch_text=lambda _url: csv_text,
        fetch_witness=lambda *_args: _witness(date="2026-07-22", close=18.0),
        now=datetime(2026, 7, 23, 2, 0, tzinfo=timezone.utc),
        seed_path=target,
    )

    run = run_external_source_refresh(
        cboe_index_spec(definition, target, min_rows=1),
        adapter,
        tmp_path / "archive",
    )

    evidence = _validation_evidence(run)["history_revision"]
    assert run.status == "OK"
    assert run.promotion_status == "UNCHANGED"
    assert run.advanced is False
    assert run.history_revision_status == "NONE"
    assert evidence["status"] == "NONE"
    assert target.read_bytes() == before


def test_valid_cboe_promotion_is_bound_to_canonical_hash_and_latest_date(tmp_path):
    target = tmp_path / "history" / "_VIX.csv"
    definition = CBOE_INDEX_DEFINITIONS["cboe_vix"]
    adapter = CboeVolatilityIndexAdapter(
        definition,
        fetch_text=lambda _url: OHLC_CSV,
        fetch_witness=lambda *_args: _witness(),
        now=datetime(2026, 7, 14, 2, 0, tzinfo=timezone.utc),
    )
    spec = cboe_index_spec(
        definition,
        target,
        min_rows=1,
        allow_initial_rebaseline=True,
    )

    run = run_external_source_refresh(spec, adapter, tmp_path / "archive")
    status = source_status(tmp_path / "archive", [spec])["cboe_vix"]

    assert run.status == "OK"
    assert run.latest_promoted_as_of == "2026-07-13"
    assert run.official_file_name == "VIX_History.csv"
    assert run.official_file_sha256
    assert status["evidence_status"] == "MATCH"

    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    drifted = source_status(tmp_path / "archive", [spec])["cboe_vix"]
    assert drifted["evidence_status"] == "EVIDENCE_DRIFT"


def test_deleted_canonical_cannot_be_silently_recreated_by_daily_spec(tmp_path):
    target = tmp_path / "history" / "_VIX.csv"
    definition = CBOE_INDEX_DEFINITIONS["cboe_vix"]
    adapter = CboeVolatilityIndexAdapter(
        definition,
        fetch_text=lambda _url: OHLC_CSV,
        fetch_witness=lambda *_args: _witness(),
        now=datetime(2026, 7, 14, 2, 0, tzinfo=timezone.utc),
    )
    archive = tmp_path / "archive"
    initial = run_external_source_refresh(
        cboe_index_spec(
            definition,
            target,
            min_rows=1,
            allow_initial_rebaseline=True,
        ),
        adapter,
        archive,
    )
    assert initial.status == "OK"
    target.unlink()

    retry = run_external_source_refresh(
        cboe_index_spec(definition, target, min_rows=1),
        adapter,
        archive,
    )

    assert retry.status == "VALIDATION_ERROR"
    assert "canonical missing" in str(retry.error_message)
    assert not target.exists()


@pytest.mark.parametrize(
    "corrupt_content",
    [
        "date,open,high,low,close,adj_close,volume\n",
        (
            "date,open,high,low,close,adj_close,volume\n"
            "not-a-date,16,16,16,16,16,0\n"
        ),
    ],
)
def test_empty_or_unparseable_canonical_requires_controlled_rebaseline(
    tmp_path,
    corrupt_content,
):
    target = tmp_path / "history" / "_VIX.csv"
    definition = CBOE_INDEX_DEFINITIONS["cboe_vix"]
    adapter = CboeVolatilityIndexAdapter(
        definition,
        fetch_text=lambda _url: OHLC_CSV,
        fetch_witness=lambda *_args: _witness(),
        now=datetime(2026, 7, 14, 2, 0, tzinfo=timezone.utc),
    )
    archive = tmp_path / "archive"
    initial = run_external_source_refresh(
        cboe_index_spec(
            definition,
            target,
            min_rows=1,
            allow_initial_rebaseline=True,
        ),
        adapter,
        archive,
    )
    assert initial.status == "OK"
    target.write_text(corrupt_content, encoding="utf-8")
    before = target.read_bytes()

    retry = run_external_source_refresh(
        cboe_index_spec(definition, target, min_rows=1),
        adapter,
        archive,
    )

    assert retry.status == "VALIDATION_ERROR"
    assert "no valid dates" in str(retry.error_message)
    assert target.read_bytes() == before


def test_cboe_official_flag_moves_all_five_symbols_out_of_yahoo_writer():
    base = {
        "symbols": {"MSTR": {}},
        "market_symbols": ["^VIX", "^VIX3M"],
        "radars": {},
        "component_proxies": {},
        "features": {"use_cboe_official_indices": False},
    }
    off = all_backfill_symbols(base)
    on = all_backfill_symbols(
        {**base, "features": {"use_cboe_official_indices": True}}
    )

    assert {"^VIX", "^VIX3M", "^VIX9D", "^SKEW", "^VVIX"}.issubset(off)
    assert {"^VIX", "^VIX3M", "^VIX9D", "^SKEW", "^VVIX"}.isdisjoint(on)


def test_explicit_backfill_cannot_bypass_cboe_single_writer(monkeypatch, tmp_path):
    target = tmp_path / "_VIX.csv"
    target.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-07-10,16,16,15,15.03,15.03,0\n",
        encoding="utf-8",
    )
    before = target.read_bytes()
    calls: list[str] = []

    def downloader(symbol: str, _start: str, _end: str | None):
        calls.append(symbol)
        return pd.DataFrame(
            {"Close": [99.0]},
            index=pd.DatetimeIndex([pd.Timestamp("2026-07-13")]),
        )

    monkeypatch.setattr(
        backfill_history,
        "load_config",
        lambda: {"features": {"use_cboe_official_indices": True}},
    )

    with pytest.raises(PermissionError, match="CBOE official writer owns"):
        backfill_history.backfill(
            ["^VIX"],
            start="2026-07-10",
            end="2026-07-14",
            store_dir=tmp_path,
            downloader=downloader,
        )

    assert calls == []
    assert target.read_bytes() == before


def test_refresh_lanes_split_cboe_decision_and_auxiliary_sources(monkeypatch, tmp_path):
    calls: list[str] = []

    def fake_refresh(source_id, _config, **_kwargs):
        calls.append(source_id)
        return {"source_id": source_id, "status": "OK"}

    monkeypatch.setattr(refresh_external, "refresh_source", fake_refresh)
    base = {
        "paths": {"history_dir": str(tmp_path / "history")},
        "features": {"use_cboe_official_indices": False},
    }
    refresh_external.refresh_all_sources(base)
    assert not set(refresh_external.CBOE_INDEX_SOURCE_IDS).intersection(calls)

    calls.clear()
    enabled = {**base, "features": {"use_cboe_official_indices": True}}
    refresh_external.refresh_all_sources(enabled, lane="decision")
    assert set(refresh_external.CBOE_INDEX_SOURCE_IDS) - {"cboe_vix9d"} <= set(calls)
    assert "cboe_vix9d" not in calls

    calls.clear()
    refresh_external.refresh_all_sources(enabled, lane="shadow")
    assert set(refresh_external.CBOE_INDEX_SOURCE_IDS).intersection(calls) == {
        "cboe_vix9d"
    }


def test_direct_cboe_refresh_is_rejected_while_feature_is_off(monkeypatch, tmp_path):
    config = {
        "paths": {
            "history_dir": str(tmp_path / "history"),
            "archive_dir": str(tmp_path / "archive"),
        },
        "features": {"use_cboe_official_indices": False},
    }
    factory_calls: list[str] = []

    def forbidden_factory(_config):
        factory_calls.append("called")
        raise AssertionError("disabled source factory must not be constructed")

    monkeypatch.setattr(
        refresh_external,
        "source_factories",
        lambda: {"cboe_vix": forbidden_factory},
    )

    with pytest.raises(ValueError, match="disabled by config"):
        refresh_external.refresh_source("cboe_vix", config)

    assert factory_calls == []
    assert not (tmp_path / "history" / "_VIX.csv").exists()
    assert not (tmp_path / "archive" / "external_sources" / "external_source_runs.jsonl").exists()
