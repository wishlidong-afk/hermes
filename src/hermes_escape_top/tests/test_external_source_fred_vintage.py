from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from hermes_escape_top.core.data.external_sources.fred_vintage import (
    FRED_OBSERVATIONS_URL,
    FredVintageAdapter,
    FredVintageNetLiquidityAdapter,
    FredVintagePercentileAdapter,
    build_vintage_net_liquidity_frame,
    build_vintage_percentile_frame,
    fred_vintage_spec,
)
from hermes_escape_top.core.data.external_sources.registry import validate_normalized_frame
from hermes_escape_top.core.data.macro import FredNetLiquiditySource
from hermes_escape_top.core.data.risk_signals import FredPercentileSource


def _event(
    series_id: str,
    observation_date: str,
    vintage_date: str,
    value: float | None,
    *,
    fetched_at: str = "2026-07-14T00:00:00+00:00",
) -> dict:
    return {
        "series_id": series_id,
        "observation_date": observation_date,
        "realtime_start": vintage_date,
        "vintage_date": vintage_date,
        "value": value,
        "is_missing": value is None,
        "fetched_at": fetched_at,
        "source_url": FRED_OBSERVATIONS_URL,
        "response_sha256": "a" * 64,
    }


def _vintage_response(latest: str) -> dict:
    return {
        "count": 1,
        "vintage_dates": [latest],
    }


def test_vintage_adapter_parses_output_type_three_without_leaking_api_key(tmp_path) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def request(endpoint, params):
        calls.append((endpoint, dict(params)))
        if endpoint.endswith("/vintagedates"):
            if params["sort_order"] == "asc":
                return _vintage_response("2020-01-02")
            return _vintage_response("2020-01-03")
        assert params["output_type"] == "3"
        return {
            "count": 2,
            "observations": [
                {"date": "2020-01-01", "TEST_20200102": "1.0"},
                {"date": "2020-01-01", "TEST_20200103": "2.0"},
            ],
        }

    adapter = FredVintageAdapter(
        target_path=tmp_path / "fred_vintages.csv",
        api_key="SECRET_KEY",
        series_starts={"TEST": "2020-01-01"},
        request_json=request,
        now=datetime(2020, 1, 4, tzinfo=timezone.utc),
    )

    raw = adapter.fetch_raw()
    frame = adapter.parse(raw)

    assert list(frame["value"]) == [1.0, 2.0]
    assert list(frame["vintage_date"].astype(str)) == ["2020-01-02", "2020-01-03"]
    assert frame["fetched_at"].nunique() == 1
    assert all(len(value) == 64 for value in frame["response_sha256"])
    raw_text = json.dumps(raw, sort_keys=True)
    assert "SECRET_KEY" not in raw_text
    assert all("api_key" not in params for _endpoint, params in raw["request_evidence"])
    assert any("api_key" in params for _endpoint, params in calls)


def test_vintage_adapter_chunks_long_realtime_period_without_overlap(tmp_path) -> None:
    observation_ranges: list[tuple[str, str]] = []

    def request(endpoint, params):
        if endpoint.endswith("/vintagedates"):
            return _vintage_response(
                "2010-01-01" if params["sort_order"] == "asc" else "2020-01-01"
            )
        observation_ranges.append((params["realtime_start"], params["realtime_end"]))
        return {"count": 0, "observations": []}

    adapter = FredVintageAdapter(
        target_path=tmp_path / "fred_vintages.csv",
        api_key="key",
        series_starts={"TEST": "2000-01-01"},
        request_json=request,
        now=datetime(2020, 1, 2, tzinfo=timezone.utc),
    )

    adapter.fetch_raw()

    assert len(observation_ranges) == 3
    for previous, current in zip(observation_ranges, observation_ranges[1:]):
        assert pd.Timestamp(current[0]) == pd.Timestamp(previous[1]) + pd.Timedelta(days=1)
    assert all(
        (pd.Timestamp(end) - pd.Timestamp(start)).days < 4 * 366
        for start, end in observation_ranges
    )


def test_vintage_adapter_rejects_truncated_observation_response(tmp_path) -> None:
    def request(endpoint, params):
        if endpoint.endswith("/vintagedates"):
            return _vintage_response(
                "2020-01-02" if params["sort_order"] == "asc" else "2020-01-03"
            )
        assert params["limit"] == "100000"
        return {
            "count": 2,
            "observations": [{"date": "2020-01-01", "TEST_20200102": "1.0"}],
        }

    adapter = FredVintageAdapter(
        target_path=tmp_path / "fred_vintages.csv",
        api_key="key",
        series_starts={"TEST": "2000-01-01"},
        request_json=request,
    )

    with pytest.raises(ValueError, match="truncated FRED vintage response"):
        adapter.fetch_raw()


def test_vintage_adapter_incremental_no_change_preserves_seed(tmp_path) -> None:
    target = tmp_path / "fred_vintages.csv"
    seed = pd.DataFrame([_event("TEST", "2020-01-01", "2020-01-02", 1.0)])
    seed.to_csv(target, index=False)
    observation_calls = 0

    def request(endpoint, params):
        nonlocal observation_calls
        if endpoint.endswith("/vintagedates"):
            return _vintage_response("2020-01-02")
        observation_calls += 1
        return {"count": 0, "observations": []}

    adapter = FredVintageAdapter(
        target_path=target,
        api_key="key",
        series_starts={"TEST": "2000-01-01"},
        request_json=request,
    )

    frame = adapter.parse(adapter.fetch_raw())

    assert observation_calls == 0
    pd.testing.assert_frame_equal(
        frame.reset_index(drop=True),
        seed.assign(value=seed["value"].astype(float)).reset_index(drop=True),
        check_dtype=False,
    )


def test_vintage_adapter_rejects_conflicting_overlap(tmp_path) -> None:
    target = tmp_path / "fred_vintages.csv"
    pd.DataFrame([_event("TEST", "2020-01-01", "2020-01-02", 1.0)]).to_csv(
        target, index=False
    )

    def request(endpoint, params):
        if endpoint.endswith("/vintagedates"):
            return _vintage_response("2020-01-03")
        return {
            "count": 1,
            "observations": [{"date": "2020-01-01", "TEST_20200102": "9.0"}],
        }

    adapter = FredVintageAdapter(
        target_path=target,
        api_key="key",
        series_starts={"TEST": "2000-01-01"},
        request_json=request,
    )

    with pytest.raises(ValueError, match="conflicting ALFRED event"):
        adapter.parse(adapter.fetch_raw())


def test_vintage_adapter_requires_key_and_composite_key_validation(tmp_path) -> None:
    with pytest.raises(ValueError, match="FRED API key"):
        FredVintageAdapter(
            target_path=tmp_path / "fred_vintages.csv",
            api_key=None,
            series_starts={"TEST": "2000-01-01"},
        ).fetch_raw()

    spec = fred_vintage_spec(target_path=tmp_path / "fred_vintages.csv")
    valid = pd.DataFrame(
        [
            _event("A", "2020-01-01", "2020-01-02", 1.0),
            _event("B", "2020-01-01", "2020-01-02", 2.0),
        ]
    )
    assert validate_normalized_frame(spec, valid) is None
    duplicated = pd.concat([valid, valid.iloc[[0]]], ignore_index=True)
    assert "duplicate ALFRED event keys" in validate_normalized_frame(spec, duplicated)


def test_vintage_percentile_replay_applies_revision_only_after_vintage_date() -> None:
    events = pd.DataFrame(
        [
            _event("TEST", "2020-01-01", "2020-01-02", 10.0),
            _event("TEST", "2020-01-02", "2020-01-03", 20.0),
            _event("TEST", "2020-01-01", "2020-01-04", 100.0),
        ]
    )

    frame = build_vintage_percentile_frame(
        events,
        series_id="TEST",
        field="test_value",
        window=2,
        min_periods=1,
    )

    before = frame.loc[frame["publish_date"] == "2020-01-03"].iloc[0]
    after = frame.loc[frame["publish_date"] == "2020-01-04"].iloc[0]
    assert before["date"] == "2020-01-02"
    assert before["test_value"] == 20.0
    assert before["test_value_pctl"] == 100.0
    assert after["date"] == "2020-01-02"
    assert after["test_value"] == 20.0
    assert after["test_value_pctl"] == 50.0
    assert list(frame["vintage_date"]) == list(frame["publish_date"])


def test_vintage_net_liquidity_replay_recomputes_after_old_revision() -> None:
    events = pd.DataFrame(
        [
            _event("WALCL", "2020-01-01", "2020-01-02", 100.0),
            _event("WTREGEN", "2020-01-01", "2020-01-02", 10.0),
            _event("RRPONTSYD", "2020-01-01", "2020-01-02", 5.0),
            _event("WALCL", "2020-01-08", "2020-01-09", 110.0),
            _event("WTREGEN", "2020-01-08", "2020-01-09", 10.0),
            _event("RRPONTSYD", "2020-01-08", "2020-01-09", 5.0),
            _event("WALCL", "2020-01-01", "2020-01-10", 200.0),
        ]
    )

    frame = build_vintage_net_liquidity_frame(
        events,
        percentile_window=2,
        min_periods=1,
        change_periods=1,
    )

    before = frame.loc[frame["publish_date"] == "2020-01-09"].iloc[0]
    after = frame.loc[frame["publish_date"] == "2020-01-10"].iloc[0]
    assert before["date"] == "2020-01-08"
    assert before["net_liq"] == 95.0
    assert before["net_liq_chg10"] == 10.0
    assert before["net_liq_chg10_pctl"] == 100.0
    assert after["date"] == "2020-01-08"
    assert after["net_liq"] == 95.0
    assert after["net_liq_chg10"] == -90.0
    assert after["net_liq_chg10_pctl"] == 100.0
    assert after["walcl_realtime_start"] == "2020-01-09"


def test_vintage_net_liquidity_forward_fills_weekly_components_to_daily_rrp() -> None:
    events = pd.DataFrame(
        [
            _event("WALCL", "2020-01-01", "2020-01-02", 100.0),
            _event("WTREGEN", "2020-01-01", "2020-01-02", 10.0),
            _event("RRPONTSYD", "2020-01-01", "2020-01-02", 5.0),
            _event("RRPONTSYD", "2020-01-02", "2020-01-03", 6.0),
        ]
    )

    frame = build_vintage_net_liquidity_frame(
        events,
        percentile_window=2,
        min_periods=1,
        change_periods=1,
    )

    current = frame.iloc[-1]
    assert current["date"] == "2020-01-02"
    assert current["walcl"] == 100.0
    assert current["wtregen"] == 10.0
    assert current["rrp"] == 6.0
    assert current["net_liq"] == 84.0
    assert current["net_liq_chg10"] == -1.0
    assert current["walcl_realtime_start"] == "2020-01-02"
    assert current["rrp_realtime_start"] == "2020-01-03"


def test_derived_adapters_verify_sha_bound_vintage_store(tmp_path) -> None:
    path = tmp_path / "fred_vintages.csv"
    events = pd.DataFrame(
        [
            _event("TEST", "2020-01-01", "2020-01-02", 10.0),
            _event("TEST", "2020-01-02", "2020-01-03", 20.0),
        ]
    )
    events.to_csv(path, index=False)
    adapter = FredVintagePercentileAdapter(
        vintage_path=path,
        series_id="TEST",
        field="test_value",
        window=2,
        min_periods=1,
    )
    raw = adapter.fetch_raw()
    frame = adapter.parse(raw)
    assert frame.iloc[-1]["test_value"] == 20.0

    path.write_text(path.read_text() + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA256"):
        adapter.parse(raw)

    net = FredVintageNetLiquidityAdapter(vintage_path=path)
    assert net.vintage_path == path


def test_scoring_consumers_select_exact_canonical_only_when_flag_is_on(tmp_path) -> None:
    base = {"paths": {"soft_history_dir": str(tmp_path)}, "features": {}}
    exact = {
        "paths": {"soft_history_dir": str(tmp_path)},
        "features": {"use_fred_vintage_pit": True},
    }
    dollar = FredPercentileSource("dollar", "data_dollar", "DTWEXBGS", "dollar_broad")
    net = FredNetLiquiditySource()

    assert dollar.history_path(base).name == "dollar.csv"
    assert dollar.history_path(exact).name == "dollar_vintage.csv"
    assert net.history_path(base).name == "fred_net_liquidity.csv"
    assert net.history_path(exact).name == "fred_net_liquidity_vintage.csv"


def test_scoring_consumers_do_not_backfill_legacy_data_into_missing_exact_path(tmp_path) -> None:
    config = {
        "paths": {"soft_history_dir": str(tmp_path)},
        "features": {
            "use_fred_vintage_pit": True,
            "data_dollar": True,
            "data_net_liquidity": True,
        },
    }
    dollar = FredPercentileSource("dollar", "data_dollar", "DTWEXBGS", "dollar_broad")
    net = FredNetLiquiditySource()

    dollar_record = dollar.collect("2026-07-14", config)
    net_record = net.collect("2026-07-14", config)

    assert dollar_record.data_available is False
    assert "exact-vintage canonical missing" in dollar_record.reason
    assert net_record.data_available is False
    assert "exact-vintage net-liquidity canonical missing" in net_record.reason
    assert not (tmp_path / "dollar_vintage.csv").exists()
    assert not (tmp_path / "fred_net_liquidity_vintage.csv").exists()
