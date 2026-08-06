from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from hermes_escape_top.core.data.market_third_source import (
    collect_market_admission_third_source_shadow,
    fetch_alpha_vantage_daily_bar,
    load_alpha_vantage_api_key,
    write_market_admission_third_source_shadow,
)


def _alpha_response(*, volume: int = 3_697_372) -> dict:
    return {
        "Meta Data": {"2. Symbol": "BRK-B"},
        "Time Series (Daily)": {
            "2026-08-05": {
                "1. open": "519.0000",
                "2. high": "519.7677",
                "3. low": "512.2000",
                "4. close": "518.8500",
                "5. volume": str(volume),
            }
        },
    }


def _blocked_payload() -> dict:
    return {
        "operation_id": "op-1",
        "generated_at": "2026-08-06T00:10:00+00:00",
        "completed_through": "2026-08-05",
        "status": "BLOCKED",
        "rows": [
            {
                "symbol": "BRK.B",
                "date": "2026-08-05",
                "status": "VOLUME_MISMATCH",
                "admitted": False,
                "price_evidence_status": "MATCH",
                "volume_evidence_status": "MISMATCH",
                "raw_comparison": {
                    "candidate": {
                        "bar": {
                            "date": "2026-08-05",
                            "open": 519.0,
                            "high": 519.7677,
                            "low": 512.2,
                            "close": 518.85,
                            "volume": 2_389_999,
                        }
                    },
                    "witness": {
                        "bar": {
                            "date": "2026-08-05",
                            "timestamp": "2026-08-05T04:00:00Z",
                            "open": 519.0,
                            "high": 519.7677,
                            "low": 512.2,
                            "close": 518.85,
                            "volume": 3_758_684,
                        }
                    },
                },
            },
            {
                "symbol": "BTC-USD",
                "date": "2026-08-05",
                "status": "DEFERRED_UNFINALIZED",
                "admitted": False,
                "blocking": False,
            },
        ],
    }


def test_alpha_vantage_daily_bar_uses_raw_compact_and_brkb_dash_symbol() -> None:
    seen = {}

    def request_json(url: str) -> dict:
        seen.update(parse_qs(urlparse(url).query))
        return _alpha_response()

    result = fetch_alpha_vantage_daily_bar(
        "BRK.B",
        "2026-08-05",
        "secret-key",
        request_json=request_json,
    )

    assert seen == {
        "function": ["TIME_SERIES_DAILY"],
        "symbol": ["BRK-B"],
        "outputsize": ["compact"],
        "apikey": ["secret-key"],
    }
    assert result["bar"] == {
        "date": "2026-08-05",
        "open": 519.0,
        "high": 519.7677,
        "low": 512.2,
        "close": 518.85,
        "volume": 3_697_372.0,
    }
    assert "secret-key" not in json.dumps(result)


def test_shadow_arbitration_supports_witness_without_changing_admission() -> None:
    calls = []

    def request_json(url: str) -> dict:
        calls.append(url)
        return _alpha_response()

    result = collect_market_admission_third_source_shadow(
        _blocked_payload(),
        api_key="secret-key",
        request_json=request_json,
        fetched_at="2026-08-06T01:00:00+00:00",
    )

    assert result["status"] == "OK"
    assert result["research_only"] is True
    assert result["requested_rows"] == 1
    assert len(calls) == 1
    row = result["rows"][0]
    assert row["symbol"] == "BRK.B"
    assert row["admission_status_unchanged"] == "VOLUME_MISMATCH"
    assert row["third_source_support"] == "ALPACA_WITNESS"
    assert row["candidate_vs_third"]["volume_evidence_status"] == "MISMATCH"
    assert row["witness_vs_third"]["volume_evidence_status"] == "MATCH"
    assert row["candidate_vs_third"]["price_evidence_status"] == "MATCH"
    assert row["witness_vs_third"]["price_evidence_status"] == "MATCH"


def test_shadow_deduplicates_repeated_symbol_date_before_fetch() -> None:
    payload = _blocked_payload()
    payload["rows"].insert(1, dict(payload["rows"][0]))
    calls = []

    result = collect_market_admission_third_source_shadow(
        payload,
        api_key="secret-key",
        request_json=lambda url: calls.append(url) or _alpha_response(),
    )

    assert result["requested_rows"] == 1
    assert len(result["rows"]) == 1
    assert len(calls) == 1


def test_shadow_no_rejection_does_not_load_credentials_or_fetch() -> None:
    called = False

    def request_json(_url: str) -> dict:
        nonlocal called
        called = True
        raise AssertionError("must not fetch")

    result = collect_market_admission_third_source_shadow(
        {"status": "OK", "rows": []},
        request_json=request_json,
    )

    assert result["status"] == "NOT_NEEDED"
    assert called is False


def test_shadow_fetch_error_redacts_api_key_from_persisted_evidence() -> None:
    def request_json(_url: str) -> dict:
        raise RuntimeError(
            "GET https://www.alphavantage.co/query?symbol=BRK-B&apikey=secret-key failed"
        )

    result = collect_market_admission_third_source_shadow(
        _blocked_payload(),
        api_key="secret-key",
        request_json=request_json,
    )

    encoded = json.dumps(result)
    assert result["status"] == "ERROR"
    assert "secret-key" not in encoded
    assert "apikey=[REDACTED]" in encoded


def test_alpha_vantage_key_loader_reads_private_env_file(tmp_path: Path) -> None:
    path = tmp_path / "alpha_vantage.env"
    path.write_text("# local only\nALPHA_VANTAGE_API_KEY=test-key\n", encoding="utf-8")

    assert load_alpha_vantage_api_key(path) == "test-key"


def test_shadow_writer_is_separate_from_canonical_admission_evidence(tmp_path: Path) -> None:
    payload = collect_market_admission_third_source_shadow(
        _blocked_payload(),
        api_key="secret-key",
        request_json=lambda _url: _alpha_response(),
        fetched_at="2026-08-06T01:00:00+00:00",
    )

    written = write_market_admission_third_source_shadow(tmp_path, payload)

    exact = tmp_path / "market_admission_third_source_2026-08-06.json"
    latest = tmp_path / "market_admission_third_source_latest.json"
    assert exact.exists()
    assert latest.exists()
    assert written["cache_path"] == str(exact)
    assert not (tmp_path / "market_admission_2026-08-06.json").exists()
