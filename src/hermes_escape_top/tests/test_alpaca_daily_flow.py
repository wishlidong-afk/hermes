from __future__ import annotations

from pathlib import Path

import pytest

from hermes_escape_top.core.data.alpaca_flow import (
    AlpacaFlowError,
    build_daily_flow_payload,
    estimate_symbol_flow,
    fetch_sip_minute_bars,
    load_daily_flow_snapshot,
    write_daily_flow_snapshot,
)


DAY = "2026-06-17"


def test_estimate_symbol_flow_uses_observed_turnover_and_bounded_split():
    rows = [
        {"t": "2026-06-17T13:30:00Z", "o": 11, "h": 12, "l": 10, "c": 11.5, "v": 100, "vw": 11, "n": 5},
        {"t": "2026-06-17T13:31:00Z", "o": 10, "h": 10, "l": 10, "c": 9, "v": 50, "vw": 10, "n": 3},
    ]

    result = estimate_symbol_flow("TEST", rows, DAY)

    assert result["total_notional"] == pytest.approx(1600)
    assert result["buy_notional"] == pytest.approx(825)
    assert result["sell_notional"] == pytest.approx(775)
    assert result["net_notional"] == pytest.approx(50)
    assert result["trade_count"] == 8
    assert result["bar_count"] == 2


def test_fetch_sip_minute_bars_paginates_without_exposing_credentials():
    calls = []

    def request_json(url, headers):
        calls.append((url, headers))
        if len(calls) == 1:
            return {"bars": {"AAPL": [{"t": "one"}]}, "next_page_token": "next-token"}
        return {"bars": {"AAPL": [{"t": "two"}]}, "next_page_token": None}

    result = fetch_sip_minute_bars(
        ["AAPL"], DAY, {"key": "key-id", "secret": "secret-value"}, request_json=request_json
    )

    assert [row["t"] for row in result["AAPL"]] == ["one", "two"]
    assert "feed=sip" in calls[0][0]
    assert "page_token=next-token" in calls[1][0]
    assert "secret-value" not in calls[0][0]
    assert calls[0][1]["APCA-API-SECRET-KEY"] == "secret-value"


def test_build_and_load_daily_flow_snapshot(tmp_path: Path):
    bars = {
        "MSTR": [{"t": "x", "o": 100, "h": 102, "l": 98, "c": 102, "v": 10, "vw": 100, "n": 4}],
        "NVDA": [{"t": "x", "o": 150, "h": 151, "l": 149, "c": 149, "v": 20, "vw": 150, "n": 6}],
    }
    payload = build_daily_flow_payload(DAY, {"MSTR": ["MSTR"], "FNGU": ["NVDA"]}, bars)

    written = write_daily_flow_snapshot(tmp_path, payload)
    loaded = load_daily_flow_snapshot(tmp_path, DAY)

    assert Path(written["cache_path"]).exists()
    assert loaded is not None
    assert loaded["baskets"]["MSTR"]["direction"] == "NET_BUY"
    assert loaded["baskets"]["FNGU"]["direction"] == "NET_SELL"
    assert loaded["symbols"]["NVDA"]["total_notional"] == pytest.approx(3000)
    assert "APCA_API" not in str(loaded)


def test_empty_session_is_rejected_before_it_can_replace_latest_cache():
    with pytest.raises(AlpacaFlowError, match="no regular-session bars"):
        build_daily_flow_payload(DAY, {"MSTR": ["MSTR"]}, {"MSTR": []})
