from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier

import pandas as pd

from hermes_escape_top.core.data.market_witness import (
    build_market_witness_payload,
    fetch_alpaca_daily_bar_range,
    fetch_alpaca_daily_bars,
    refresh_market_witness,
    write_market_witness,
)
from hermes_escape_top.core.safe_io import PipelineBusy
from hermes_escape_top.scripts import check_market_witness as cli_mod


def _local(close: float = 100.0, volume: float = 1_000.0) -> dict:
    return {
        "date": "2026-07-10",
        "open": close - 1,
        "high": close + 1,
        "low": close - 2,
        "close": close,
        "volume": volume,
    }


def _alpaca(close: float = 100.1, volume: float = 1_020.0) -> dict:
    return {
        "t": "2026-07-10T04:00:00Z",
        "o": close - 1,
        "h": close + 1,
        "l": close - 2,
        "c": close,
        "v": volume,
    }


def test_market_witness_matches_close_and_volume_within_policy() -> None:
    payload = build_market_witness_payload(
        "2026-07-10",
        ["MSTR"],
        {"MSTR": _local()},
        {"MSTR": [_alpaca()]},
    )

    row = payload["symbols"]["MSTR"]
    assert payload["status"] == "OK"
    assert row["status"] == "MATCH"
    assert row["close_diff_pct"] < 0.5
    assert row["volume_diff_pct"] < 10.0


def test_shadow_market_witness_preserves_legacy_match_when_volume_is_missing() -> None:
    witness = _alpaca()
    witness["v"] = None

    payload = build_market_witness_payload(
        "2026-07-10",
        ["MSTR"],
        {"MSTR": _local()},
        {"MSTR": [witness]},
    )

    assert payload["status"] == "OK"
    assert payload["symbols"]["MSTR"]["status"] == "MATCH"


def test_market_witness_reports_mismatch_without_promoting_it() -> None:
    payload = build_market_witness_payload(
        "2026-07-10",
        ["MSTR"],
        {"MSTR": _local()},
        {"MSTR": [_alpaca(close=80.0, volume=400.0)]},
    )

    assert payload["status"] == "WARN"
    assert payload["symbols"]["MSTR"]["status"] == "PRICE_MISMATCH"


def test_market_witness_reports_date_mismatch_before_price_comparison() -> None:
    witness = _alpaca()
    witness["t"] = "2026-07-09T04:00:00Z"

    payload = build_market_witness_payload(
        "2026-07-10",
        ["MSTR"],
        {"MSTR": _local()},
        {"MSTR": [witness]},
    )

    assert payload["symbols"]["MSTR"]["status"] == "DATE_MISMATCH"


def test_market_witness_marks_indices_as_no_witness() -> None:
    payload = build_market_witness_payload(
        "2026-07-10",
        ["^VIX"],
        {"^VIX": _local()},
        {},
    )

    assert payload["symbols"]["^VIX"]["status"] == "NO_WITNESS"
    assert payload["summary"]["NO_WITNESS"] == 1


def test_fetch_alpaca_daily_bars_uses_raw_sip_daily_endpoint() -> None:
    seen = {}

    def transport(url, headers):
        seen["url"] = url
        seen["headers"] = headers
        return {"bars": {"MSTR": [_alpaca()]}, "next_page_token": None}

    rows = fetch_alpaca_daily_bars(
        ["MSTR"],
        "2026-07-10",
        {"key": "key", "secret": "secret"},
        request_json=transport,
    )

    assert rows["MSTR"][0]["c"] == 100.1
    assert "timeframe=1Day" in seen["url"]
    assert "feed=sip" in seen["url"]
    assert "adjustment=raw" in seen["url"]
    assert seen["headers"]["APCA-API-KEY-ID"] == "key"


def test_fetch_alpaca_daily_bar_range_uses_requested_window() -> None:
    seen = {}

    def transport(url, headers):
        seen["url"] = url
        return {"bars": {"MSTR": [_alpaca()]}, "next_page_token": None}

    rows = fetch_alpaca_daily_bar_range(
        ["MSTR"],
        "2026-07-10",
        "2026-07-14",
        {"key": "key", "secret": "secret"},
        request_json=transport,
    )

    assert rows["MSTR"][0]["c"] == 100.1
    assert "start=2026-07-10T00%3A00%3A00Z" in seen["url"]
    assert "end=2026-07-14T00%3A00%3A00Z" in seen["url"]
    assert "timeframe=1Day" in seen["url"]
    assert "feed=sip" in seen["url"]
    assert "adjustment=raw" in seen["url"]


def test_fetch_alpaca_daily_bar_range_clips_future_end_behind_free_sip_delay() -> None:
    seen = {}

    def transport(url, _headers):
        seen["url"] = url
        return {"bars": {"MSTR": [_alpaca()]}, "next_page_token": None}

    rows = fetch_alpaca_daily_bar_range(
        ["MSTR"],
        "2026-07-10",
        "2026-07-15",
        {"key": "key", "secret": "secret"},
        request_json=transport,
        now=datetime(2026, 7, 14, 23, 10, tzinfo=timezone.utc),
    )

    assert rows["MSTR"][0]["c"] == 100.1
    assert "end=2026-07-14T22%3A50%3A00Z" in seen["url"]


def test_fetch_alpaca_daily_bar_range_rejects_repeated_page_token() -> None:
    calls = []

    def transport(url, _headers):
        calls.append(url)
        return {"bars": {}, "next_page_token": "stuck"}

    try:
        fetch_alpaca_daily_bar_range(
            ["MSTR"],
            "2026-07-10",
            "2026-07-14",
            {"key": "key", "secret": "secret"},
            request_json=transport,
        )
    except RuntimeError as exc:
        assert "repeated page token" in str(exc)
    else:
        raise AssertionError("repeated Alpaca page token must fail closed")

    assert len(calls) == 2


def test_refresh_market_witness_writes_archive_only(tmp_path: Path) -> None:
    history = tmp_path / "history"
    archive = tmp_path / "archive"
    history.mkdir()
    canonical = history / "MSTR.csv"
    pd.DataFrame([_local()]).to_csv(canonical, index=False)
    before = canonical.read_bytes()

    payload = refresh_market_witness(
        "2026-07-10",
        {
            "paths": {
                "history_dir": str(history),
                "archive_dir": str(archive),
            }
        },
        credentials={"key": "key", "secret": "secret"},
        request_json=lambda _url, _headers: {
            "bars": {"MSTR": [_alpaca()]},
            "next_page_token": None,
        },
        symbols=["MSTR"],
    )

    assert payload["status"] == "OK"
    assert canonical.read_bytes() == before
    exact = archive / "market_witness_2026-07-10.json"
    assert json.loads(exact.read_text(encoding="utf-8"))["symbols"]["MSTR"]["status"] == "MATCH"


def test_market_witness_fetch_error_preserves_canonical_and_writes_evidence(tmp_path: Path) -> None:
    history = tmp_path / "history"
    archive = tmp_path / "archive"
    history.mkdir()
    canonical = history / "MSTR.csv"
    pd.DataFrame([_local()]).to_csv(canonical, index=False)
    before = canonical.read_bytes()

    def fail(_url, _headers):
        raise TimeoutError("witness timeout")

    payload = refresh_market_witness(
        "2026-07-10",
        {"paths": {"history_dir": str(history), "archive_dir": str(archive)}},
        credentials={"key": "key", "secret": "secret"},
        request_json=fail,
        symbols=["MSTR"],
    )

    assert payload["status"] == "FETCH_ERROR"
    assert payload["error_type"] == "TimeoutError"
    assert canonical.read_bytes() == before
    assert (archive / "market_witness_2026-07-10.json").exists()


def test_market_witness_cli_returns_busy_without_calling_writer(monkeypatch, capsys) -> None:
    called = []

    @contextmanager
    def busy_lock(**_kwargs):
        raise PipelineBusy("pipeline busy")
        yield

    monkeypatch.setattr(cli_mod, "pipeline_lock", busy_lock, raising=False)
    monkeypatch.setattr(cli_mod, "refresh_market_witness", lambda *_args, **_kwargs: called.append(True))
    result = cli_mod.main(["--as-of", "2026-07-10", "--lock-timeout", "0"])

    assert result == 75
    assert called == []
    assert json.loads(capsys.readouterr().out)["busy"] is True


def test_market_witness_latest_write_uses_unique_atomic_temp_files(monkeypatch, tmp_path: Path) -> None:
    barrier = Barrier(2)
    original_replace = Path.replace

    def synchronized_replace(path: Path, target: Path):
        if Path(target).name == "market_witness_latest.json":
            barrier.wait(timeout=5)
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", synchronized_replace)
    payloads = [
        {"as_of": "2026-07-09", "status": "OK", "summary": {"MATCH": 1}},
        {"as_of": "2026-07-10", "status": "WARN", "summary": {"PRICE_MISMATCH": 1}},
    ]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda payload: write_market_witness(tmp_path, payload), payloads))

    assert {result["as_of"] for result in results} == {"2026-07-09", "2026-07-10"}
    assert (tmp_path / "market_witness_2026-07-09.json").exists()
    assert (tmp_path / "market_witness_2026-07-10.json").exists()
    latest = json.loads((tmp_path / "market_witness_latest.json").read_text(encoding="utf-8"))
    assert latest["as_of"] in {"2026-07-09", "2026-07-10"}
