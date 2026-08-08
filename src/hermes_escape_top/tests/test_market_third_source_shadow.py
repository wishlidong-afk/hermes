from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from hermes_escape_top.core.data.market_third_source import (
    SCHEMA_VERSION,
    collect_market_admission_third_source_shadow,
    fetch_alpha_vantage_daily_bar,
    load_alpha_vantage_api_key,
    read_matching_market_admission_third_source_shadow,
    retry_market_admission_third_source_shadow,
    write_market_admission_third_source_shadow,
)
from hermes_escape_top.core.safe_io import PipelineBusy
from hermes_escape_top.scripts import retry_market_third_source as retry_script
from hermes_escape_top.scripts.retry_market_third_source import run_retry


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


def test_shadow_reader_requires_matching_operation_and_completed_through(tmp_path: Path) -> None:
    admission = _blocked_payload()
    shadow = collect_market_admission_third_source_shadow(
        admission,
        api_key="secret-key",
        request_json=lambda _url: _alpha_response(),
        fetched_at="2026-08-06T01:00:00+00:00",
    )
    write_market_admission_third_source_shadow(tmp_path, shadow)

    assert read_matching_market_admission_third_source_shadow(tmp_path, admission) == shadow
    assert read_matching_market_admission_third_source_shadow(
        tmp_path,
        {**admission, "operation_id": "op-2"},
    ) is None
    assert read_matching_market_admission_third_source_shadow(
        tmp_path,
        {**admission, "completed_through": "2026-08-06"},
    ) is None


def test_shadow_reader_rejects_untyped_or_non_research_evidence(tmp_path: Path) -> None:
    admission = _blocked_payload()
    path = tmp_path / "market_admission_third_source_latest.json"
    base = {
        "schema_version": SCHEMA_VERSION,
        "research_only": True,
        "admission_operation_id": admission["operation_id"],
        "completed_through": admission["completed_through"],
        "status": "OK",
        "rows": [],
    }
    path.write_text(json.dumps({**base, "schema_version": "unknown"}), encoding="utf-8")
    assert read_matching_market_admission_third_source_shadow(tmp_path, admission) is None

    path.write_text(json.dumps({**base, "research_only": False}), encoding="utf-8")
    assert read_matching_market_admission_third_source_shadow(tmp_path, admission) is None


def test_retry_replaces_unavailable_shadow_without_writing_admission(tmp_path: Path) -> None:
    admission = _blocked_payload()
    unavailable = collect_market_admission_third_source_shadow(
        admission,
        api_key="secret-key",
        request_json=lambda _url: {"Time Series (Daily)": {}},
        fetched_at="2026-08-06T00:10:00+00:00",
    )
    write_market_admission_third_source_shadow(tmp_path, unavailable)

    result = retry_market_admission_third_source_shadow(
        tmp_path,
        admission_payload=admission,
        api_key="secret-key",
        request_json=lambda _url: _alpha_response(),
        fetched_at="2026-08-06T01:02:00+00:00",
    )

    assert result["status"] == "OK"
    assert result["rows"][0]["third_source_support"] == "ALPACA_WITNESS"
    assert read_matching_market_admission_third_source_shadow(tmp_path, admission)["status"] == "OK"
    assert not (tmp_path / "market_admission_latest.json").exists()


def test_retry_skips_network_when_matching_shadow_is_already_available(tmp_path: Path) -> None:
    admission = _blocked_payload()
    available = collect_market_admission_third_source_shadow(
        admission,
        api_key="secret-key",
        request_json=lambda _url: _alpha_response(),
        fetched_at="2026-08-06T00:10:00+00:00",
    )
    write_market_admission_third_source_shadow(tmp_path, available)

    result = retry_market_admission_third_source_shadow(
        tmp_path,
        admission_payload=admission,
        request_json=lambda _url: (_ for _ in ()).throw(AssertionError("must not fetch")),
    )

    assert result["status"] == "OK"
    assert result["retry_status"] == "ALREADY_AVAILABLE"


def test_retry_script_resolves_archive_without_entering_scoring(tmp_path: Path) -> None:
    seen = []
    lock_calls = []

    @contextmanager
    def fake_lock(**kwargs):
        lock_calls.append(kwargs)
        yield

    result = run_retry(
        config={"paths": {"archive_dir": str(tmp_path)}},
        retry_fn=lambda archive: seen.append(Path(archive)) or {"status": "NOT_NEEDED"},
        lock_fn=fake_lock,
        lock_timeout=12.0,
    )

    assert seen == [tmp_path]
    assert lock_calls == [
        {
            "blocking": True,
            "timeout": 12.0,
            "path": tmp_path / ".pipeline.lock",
        }
    ]
    assert result == {"status": "NOT_NEEDED"}


def test_retry_script_reports_pipeline_busy_without_writing(
    monkeypatch,
    capsys,
) -> None:
    def busy_retry(**_kwargs):
        raise PipelineBusy("pipeline busy (test)")

    monkeypatch.setattr(retry_script, "run_retry", busy_retry)

    assert retry_script.main(["--lock-timeout", "0"]) == 75
    assert json.loads(capsys.readouterr().out) == {
        "status": "BUSY",
        "error": "pipeline busy (test)",
    }
