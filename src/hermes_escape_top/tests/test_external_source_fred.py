from __future__ import annotations

import builtins
import json
import subprocess
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from hermes_escape_top.core.data.macro import fetch_fred_graph_csv
from hermes_escape_top.core.data.external_sources.fred import (
    FredNetLiquidityAdapter,
    fred_net_liquidity_spec,
    FredPercentileAdapter,
    fred_percentile_spec,
)
from hermes_escape_top.core.data.external_sources.ledger import latest_source_run
from hermes_escape_top.core.data.external_sources.runner import run_external_source_refresh


def test_fetch_fred_graph_csv_prefers_curl_and_does_not_require_requests(monkeypatch):
    original_import = builtins.__import__

    def import_without_requests(name, *args, **kwargs):
        if name == "requests":
            raise ModuleNotFoundError("No module named 'requests'")
        return original_import(name, *args, **kwargs)

    calls = []
    urlopen_called = False

    def fake_run(command, check, capture_output, text, timeout):
        calls.append((command, check, capture_output, text, timeout))
        return SimpleNamespace(
            stdout="observation_date,WALCL\n2026-06-01,100.5\n2026-06-02,.\n2026-06-03,101.5\n",
            stderr="",
        )

    def fail_urlopen(request, timeout=30):
        nonlocal urlopen_called
        urlopen_called = True
        raise AssertionError("curl should be attempted before urllib")

    monkeypatch.setattr(builtins, "__import__", import_without_requests)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)

    series = fetch_fred_graph_csv("WALCL", start="2026-06-01", end="2026-06-03")

    assert calls
    command = calls[0][0]
    assert command[:4] == ["curl", "--fail", "--location", "--silent"]
    assert "id=WALCL" in command[-1]
    assert "cosd=2026-06-01" in command[-1]
    assert "coed=2026-06-03" in command[-1]
    assert urlopen_called is False
    assert series.index.astype(str).tolist() == ["2026-06-01", "2026-06-03"]
    assert series.tolist() == [100.5, 101.5]


def test_fetch_fred_graph_csv_falls_back_to_urllib_when_curl_fails(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"observation_date,WALCL\n2026-06-01,100.5\n2026-06-02,101.5\n"

    calls = []

    def failing_run(command, check, capture_output, text, timeout):
        calls.append((command, check, capture_output, text, timeout))
        raise FileNotFoundError("curl")

    def fake_urlopen(request, timeout=30):
        calls.append((request.full_url, timeout))
        return Response()

    monkeypatch.setattr(subprocess, "run", failing_run)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    series = fetch_fred_graph_csv("WALCL", start="2026-06-01")

    assert calls
    assert calls[0][0][:4] == ["curl", "--fail", "--location", "--silent"]
    assert "id=WALCL" in calls[1][0]
    assert series.index.astype(str).tolist() == ["2026-06-01", "2026-06-02"]
    assert series.tolist() == [100.5, 101.5]


def test_fred_percentile_adapter_promotes_existing_soft_history_shape(tmp_path):
    def fetch_frame(series_id, start="1990-01-01", end=None, config=None):
        assert series_id == "DTWEXBGS"
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"]),
                "publish_date": pd.to_datetime(["2026-06-02", "2026-06-03", "2026-06-04"]),
                "value": [100.0, 101.0, 102.0],
            }
        )
        frame.attrs["fred_metadata"] = {
            "series_id": series_id,
            "transport": "fred_observations_api",
            "realtime_start": "2026-07-13",
            "realtime_end": "2026-07-13",
            "fetched_at": "2026-07-13T01:00:00+00:00",
            "pit_rule": "observation_date_plus_one_day",
        }
        return frame

    target = tmp_path / "soft_history" / "dollar.csv"
    spec = fred_percentile_spec(
        source_id="dollar",
        target_path=target,
        field="dollar_broad",
    )
    adapter = FredPercentileAdapter(
        series_id="DTWEXBGS",
        field="dollar_broad",
        window=2,
        min_periods=1,
        fetch_frame=fetch_frame,
    )

    run = run_external_source_refresh(spec, adapter, tmp_path / "archive")

    out = pd.read_csv(target)
    assert run.status == "OK"
    assert list(out.columns) == ["date", "publish_date", "dollar_broad", "dollar_broad_pctl"]
    assert out["publish_date"].tolist() == ["2026-06-02", "2026-06-03", "2026-06-04"]
    assert out["dollar_broad"].tolist() == [100.0, 101.0, 102.0]
    assert out["dollar_broad_pctl"].round(2).tolist() == [100.0, 100.0, 100.0]
    assert latest_source_run(tmp_path / "archive", "dollar")["latest_promoted_as_of"] == "2026-06-03"
    raw = json.loads(Path(run.raw_path).read_text(encoding="utf-8"))
    assert raw["metadata"]["realtime_start"] == "2026-07-13"
    assert raw["metadata"]["realtime_end"] == "2026-07-13"
    assert raw["metadata"]["fetched_at"] == "2026-07-13T01:00:00+00:00"
    assert raw["metadata"]["pit_rule"] == "observation_date_plus_one_day"
    assert len(raw["rows"]) == 3


def test_fred_source_input_hash_ignores_retrieval_timestamp(tmp_path):
    fetched_at = ["2026-07-13T01:00:00+00:00"]

    def fetch_frame(series_id, start="1990-01-01", end=None, config=None):
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-01"]),
                "publish_date": pd.to_datetime(["2026-06-02"]),
                "value": [100.0],
            }
        )
        frame.attrs["fred_metadata"] = {
            "series_id": series_id,
            "realtime_start": "2026-07-13",
            "realtime_end": "2026-07-13",
            "fetched_at": fetched_at[0],
            "pit_rule": "observation_date_plus_one_day",
        }
        return frame

    target = tmp_path / "soft_history" / "dollar.csv"
    spec = fred_percentile_spec(source_id="dollar", target_path=target, field="dollar_broad")
    adapter = FredPercentileAdapter(
        series_id="DTWEXBGS",
        field="dollar_broad",
        min_periods=1,
        fetch_frame=fetch_frame,
    )
    first = run_external_source_refresh(spec, adapter, tmp_path / "archive")
    fetched_at[0] = "2026-07-13T02:00:00+00:00"
    second = run_external_source_refresh(spec, adapter, tmp_path / "archive")

    assert first.input_hash == second.input_hash


def test_fred_net_liquidity_adapter_promotes_existing_soft_history_shape(tmp_path):
    dates = pd.date_range("2026-01-01", periods=70, freq="D")

    def fetch_series(series_id, start="2015-01-01", end=None):
        base = {"WALCL": 8_000_000, "WTREGEN": 500_000, "RRPONTSYD": 1_000_000}[series_id]
        return pd.Series([base + i * 1000 for i in range(len(dates))], index=dates)

    target = tmp_path / "soft_history" / "fred_net_liquidity.csv"
    spec = fred_net_liquidity_spec(target_path=target)
    adapter = FredNetLiquidityAdapter(fetch_series=fetch_series, percentile_window=60, start="2026-01-01")

    run = run_external_source_refresh(spec, adapter, tmp_path / "archive")

    out = pd.read_csv(target)
    assert run.status == "OK"
    assert list(out.columns) == [
        "date",
        "publish_date",
        "walcl",
        "wtregen",
        "rrp",
        "net_liq",
        "net_liq_chg10",
        "net_liq_chg10_pctl",
    ]
    assert out["publish_date"].iloc[-1] == "2026-03-12"
    assert out["net_liq"].iloc[-1] > 0
    assert latest_source_run(tmp_path / "archive", "fred_net_liquidity")["latest_promoted_as_of"] == "2026-03-11"
    raw = json.loads(Path(run.raw_path).read_text(encoding="utf-8"))
    assert raw["metadata"]["pit_rule"] == "observation_date_plus_one_day"
    assert set(raw["metadata"]["series_ids"]) == {"walcl", "wtregen", "rrp"}
