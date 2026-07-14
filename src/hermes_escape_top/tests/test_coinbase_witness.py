from __future__ import annotations

from datetime import datetime, timezone
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

import hermes_escape_top.core.data.coinbase_witness as coinbase_module
from hermes_escape_top.core.data.coinbase_witness import (
    compare_btc_spot_close,
    fetch_coinbase_daily_bar_range,
    latest_completed_utc_day,
)


def _candle(day_epoch: int, close: float = 100.0) -> list[float]:
    return [day_epoch, close - 3.0, close + 2.0, close - 1.0, close, 12.5]


def test_latest_completed_utc_day_never_admits_the_open_bucket() -> None:
    assert latest_completed_utc_day(
        datetime(2026, 7, 14, 0, 1, tzinfo=timezone.utc)
    ).isoformat() == "2026-07-13"
    assert latest_completed_utc_day(
        datetime(2026, 7, 14, 23, 59, tzinfo=timezone.utc)
    ).isoformat() == "2026-07-13"


def test_coinbase_range_normalizes_reverse_rows_and_filters_extra_buckets() -> None:
    seen: list[str] = []

    def transport(url, _headers):
        seen.append(url)
        return [
            _candle(1783987200, 105.0),  # 2026-07-14, end-exclusive
            _candle(1783900800, 104.0),  # 2026-07-13
            _candle(1783814400, 103.0),  # 2026-07-12
            _candle(1783555200, 99.0),   # 2026-07-09, before start
        ]

    result = fetch_coinbase_daily_bar_range(
        "2026-07-10",
        "2026-07-14",
        request_json=transport,
    )

    assert [row["t"][:10] for row in result["bars"]] == [
        "2026-07-12",
        "2026-07-13",
    ]
    assert result["bars"][-1] == {
        "t": "2026-07-13T00:00:00Z",
        "o": 103.0,
        "h": 106.0,
        "l": 101.0,
        "c": 104.0,
        "v": 12.5,
    }
    assert result["source"] == "COINBASE_EXCHANGE_BTC_USD_1DAY"
    assert len(result["requests"]) == 1
    assert len(result["requests"][0]["content_sha256"]) == 64
    assert "granularity=86400" in seen[0]


def test_coinbase_range_chunks_requests_below_the_300_candle_limit() -> None:
    ranges: list[tuple[str, str]] = []

    def transport(url, _headers):
        query = parse_qs(urlparse(url).query)
        ranges.append((query["start"][0], query["end"][0]))
        return []

    result = fetch_coinbase_daily_bar_range(
        "2025-01-01",
        "2026-07-01",
        request_json=transport,
    )

    assert len(ranges) == 2
    assert ranges[0][0].startswith("2025-01-01")
    assert ranges[-1][1].startswith("2026-07-01")
    assert result["bars"] == []
    assert len(result["requests"]) == 2


def test_btc_close_match_ignores_volume_and_exposes_warning_band() -> None:
    comparison = compare_btc_spot_close(
        {
            "date": "2026-07-13",
            "close": 61950.98046875,
            "volume": 37_680_570_368,
        },
        {
            "t": "2026-07-13T00:00:00Z",
            "c": 62264.94,
            "v": 9591.1892568,
        },
    )

    assert comparison["status"] == "MATCH"
    assert comparison["warning_band"] is True
    assert 0.5 < comparison["close_diff_pct"] < 1.0
    assert "volume_diff_pct" not in comparison
    assert len(comparison["local_sha256"]) == 64
    assert len(comparison["witness_sha256"]) == 64


def test_btc_close_difference_above_one_percent_is_rejected() -> None:
    comparison = compare_btc_spot_close(
        {"date": "2026-07-13", "close": 100.0},
        {"t": "2026-07-13T00:00:00Z", "c": 98.0},
    )

    assert comparison["status"] == "PRICE_MISMATCH"
    assert comparison["close_diff_pct"] > 1.0


def test_btc_close_requires_same_date_and_a_witness() -> None:
    no_witness = compare_btc_spot_close(
        {"date": "2026-07-13", "close": 100.0},
        None,
    )
    wrong_date = compare_btc_spot_close(
        {"date": "2026-07-13", "close": 100.0},
        {"t": "2026-07-12T00:00:00Z", "c": 100.0},
    )

    assert no_witness["status"] == "NO_WITNESS"
    assert "Coinbase" in no_witness["reason"]
    assert wrong_date["status"] == "DATE_MISMATCH"


def test_coinbase_transport_retries_two_transient_network_failures(monkeypatch) -> None:
    attempts = 0
    delays: list[float] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"[]"

    def open_request(_request, timeout):
        nonlocal attempts
        assert timeout == 30
        attempts += 1
        if attempts < 3:
            raise URLError("temporary")
        return Response()

    monkeypatch.setattr(coinbase_module, "urlopen", open_request)
    monkeypatch.setattr(coinbase_module.time, "sleep", delays.append)

    assert coinbase_module._request_json("https://example.test", {}) == []
    assert attempts == 3
    assert delays == [1.0, 2.0]
