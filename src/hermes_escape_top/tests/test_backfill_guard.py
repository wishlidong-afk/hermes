"""Download sanity guard (2026-06-12 cross-wired yfinance incident)."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from hermes_escape_top.core.data.market_admission import MarketAdmissionSession
from hermes_escape_top.scripts.backfill_history import (
    _market_admission_start,
    _sanity_check_download,
    backfill,
)


def test_backfill_recovers_history_before_market_admission_network_setup(
    tmp_path, monkeypatch
):
    from hermes_escape_top.scripts import backfill_history as module

    history = tmp_path / "history"
    archive = tmp_path / "archive"
    events = []
    monkeypatch.setattr(
        module,
        "load_config",
        lambda: {
            "features": {
                "use_market_admission_gate": True,
                "use_btc_spot_witness": False,
                "use_cboe_official_indices": False,
            },
            "paths": {
                "history_dir": str(history),
                "archive_dir": str(archive),
            },
        },
    )
    monkeypatch.setattr(
        module,
        "recover_history_transactions",
        lambda *_args, **_kwargs: events.append("recover") or [],
    )

    def fail_prepare(*_args, **_kwargs):
        events.append("prepare")
        raise RuntimeError("witness network unavailable")

    monkeypatch.setattr(module, "prepare_market_admission_session", fail_prepare)

    with pytest.raises(RuntimeError, match="network unavailable"):
        backfill(["QQQ"], store_dir=history)

    assert events == ["recover", "prepare"]


def _frame(closes, start="2026-06-01"):
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({"Close": closes}, index=idx)


def test_backfill_symbols_include_enabled_online_soft_dependencies():
    from hermes_escape_top.scripts.backfill_history import all_backfill_symbols, online_soft_history_symbols
    cfg = {
        "features": {
            "data_credit_etf": False,
            "data_defensive_rotation": True,
            "data_move": False,
        },
        "symbols": {"MSTR": {}, "FNGU": {}, "SOXL": {}},
        "market_symbols": [],
        "radars": {},
        "component_proxies": {},
    }

    defensive_deps = {"XLP", "XLU", "XLV", "XLY", "XLI", "XLF"}

    assert defensive_deps.issubset(set(online_soft_history_symbols(cfg)))
    assert defensive_deps.issubset(set(all_backfill_symbols(cfg)))
    assert "HYG" not in online_soft_history_symbols(cfg)
    assert "^MOVE" not in online_soft_history_symbols(cfg)


def test_web_refresh_flow_symbols_watch_enabled_online_soft_dependencies():
    from hermes_escape_top.web.refresh import _flow_symbols
    cfg = {
        "features": {"data_defensive_rotation": True},
        "symbols": {"MSTR": {}, "FNGU": {}, "SOXL": {}},
        "component_proxies": {"FNGU": ["NVDA", "AAPL"]},
    }

    symbols = _flow_symbols(cfg)

    assert {"MSTR", "FNGU", "SOXL", "NVDA", "AAPL"}.issubset(symbols)
    assert {"XLP", "XLU", "XLV", "XLY", "XLI", "XLF"}.issubset(symbols)


def test_cross_wired_append_rejected():
    existing = _frame([700, 705, 710])
    wrong_ticker = _frame([218, 217, 220], start="2026-06-04")
    ok, why = _sanity_check_download("QQQ", existing, wrong_ticker)
    assert not ok and "boundary jump" in why


def test_normal_append_accepted():
    existing = _frame([700, 705, 710])
    ok, _ = _sanity_check_download("QQQ", existing, _frame([715, 720], start="2026-06-04"))
    assert ok


def test_incomplete_overlap_bar_cannot_erase_cached_close(tmp_path):
    path = tmp_path / "DBMF.csv"
    path.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-06-17,30.68,30.77,30.61,30.67,30.67,1246700\n"
        "2026-06-18,30.73,30.94,30.61,30.82,30.82,1630478\n",
        encoding="utf-8",
    )
    incoming = pd.DataFrame(
        {
            "Open": [30.68, 30.73],
            "High": [30.77, 30.94],
            "Low": [30.61, 30.61],
            "Close": [30.67, float("nan")],
            "Adj Close": [30.67, float("nan")],
            "Volume": [1246700, 1630478],
        },
        index=pd.to_datetime(["2026-06-17", "2026-06-18"]),
    )

    backfill(
        ["DBMF"],
        start="2026-06-17",
        end="2026-06-18",
        store_dir=tmp_path,
        downloader=lambda *_args: incoming,
        repair_overlap_days=3,
    )

    saved = pd.read_csv(path)
    assert saved.loc[saved["date"] == "2026-06-18", "close"].item() == 30.82


def test_tail_fetch_discards_provider_rows_outside_requested_interval(tmp_path):
    path = tmp_path / "QQQ.csv"
    path.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-06-01,99,101,98,100,100,1000\n"
        "2026-06-02,100,102,99,101,101,1100\n",
        encoding="utf-8",
    )
    incoming = pd.DataFrame(
        {
            "Open": [99.5, 101.0],
            "High": [101.5, 103.0],
            "Low": [98.5, 100.0],
            "Close": [100.5, 102.0],
            "Adj Close": [100.5, 102.0],
            "Volume": [1000, 1200],
        },
        index=pd.to_datetime(["2026-06-01", "2026-06-03"]),
    )
    calls = []

    result = backfill(
        ["QQQ"],
        start="2026-01-01",
        end="2026-06-04",
        store_dir=tmp_path,
        downloader=lambda *args: calls.append(args) or incoming,
    )

    saved = pd.read_csv(path)
    assert calls[0][1:] == ("2026-06-03", "2026-06-04")
    assert result["QQQ"].updated is True
    assert saved.loc[saved["date"] == "2026-06-01", "close"].item() == 100.0
    assert saved.loc[saved["date"] == "2026-06-03", "close"].item() == 102.0


def test_backfill_market_admission_freezes_mismatched_candidate(tmp_path):
    path = tmp_path / "QQQ.csv"
    path.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-07-10,99,101,98,100,100,1000\n",
        encoding="utf-8",
    )
    before = path.read_bytes()
    incoming = pd.DataFrame(
        {
            "Open": [99.0],
            "High": [101.0],
            "Low": [98.0],
            "Close": [100.0],
            "Adj Close": [100.0],
            "Volume": [1_000.0],
        },
        index=pd.to_datetime(["2026-07-13"]),
    )
    session = MarketAdmissionSession(
        enabled=True,
        witness_bars={
            "QQQ": [
                {
                    "t": "2026-07-13T04:00:00Z",
                    "o": 79.0,
                    "h": 81.0,
                    "l": 78.0,
                    "c": 80.0,
                    "v": 1_000.0,
                }
            ]
        },
    )

    result = backfill(
        ["QQQ"],
        start="2026-07-10",
        end="2026-07-14",
        store_dir=tmp_path,
        downloader=lambda *_args: incoming,
        admission_session=session,
    )

    assert path.read_bytes() == before
    assert result["QQQ"].updated is False
    assert "market admission froze 1/1 rows" in result["QQQ"].reason


def test_backfill_market_admission_appends_matching_candidate(tmp_path):
    path = tmp_path / "QQQ.csv"
    path.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-07-10,99,101,98,100,100,1000\n",
        encoding="utf-8",
    )
    incoming = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [102.0],
            "Low": [99.0],
            "Close": [101.0],
            "Adj Close": [101.0],
            "Volume": [1_100.0],
        },
        index=pd.to_datetime(["2026-07-13"]),
    )
    session = MarketAdmissionSession(
        enabled=True,
        witness_bars={
            "QQQ": [
                {
                    "t": "2026-07-13T04:00:00Z",
                    "o": 100.0,
                    "h": 102.0,
                    "l": 99.0,
                    "c": 101.0,
                    "v": 1_100.0,
                }
            ]
        },
    )

    result = backfill(
        ["QQQ"],
        start="2026-07-10",
        end="2026-07-14",
        store_dir=tmp_path,
        downloader=lambda *_args: incoming,
        admission_session=session,
    )

    saved = pd.read_csv(path)
    assert result["QQQ"].updated is True
    assert saved["date"].tolist() == ["2026-07-10", "2026-07-13"]
    assert len(session.canonical_files["QQQ.csv"]["sha256"]) == 64
    assert session.canonical_files["QQQ.csv"]["latest_as_of"] == "2026-07-13"


def test_btc_spot_witness_fetches_and_admits_weekend_calendar_days(tmp_path):
    path = tmp_path / "BTC_USD.csv"
    path.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-07-10,99,101,98,100,100,1000\n",
        encoding="utf-8",
    )
    incoming = pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.0],
            "Close": [101.0, 102.0],
            "Adj Close": [101.0, 102.0],
            "Volume": [9e9, 8e9],
        },
        index=pd.to_datetime(["2026-07-11", "2026-07-12"]),
    )
    session = MarketAdmissionSession(
        enabled=True,
        witness_bars={
            "BTC-USD": [
                {"t": "2026-07-11T00:00:00Z", "c": 101.0},
                {"t": "2026-07-12T00:00:00Z", "c": 102.0},
            ]
        },
        btc_spot_witness_enabled=True,
        btc_completed_through="2026-07-12",
        requested_start="2026-07-11",
        requested_end="2026-07-13",
    )
    calls = []

    result = backfill(
        ["BTC-USD"],
        start="2026-07-10",
        end="2026-07-13",
        store_dir=tmp_path,
        downloader=lambda *args: calls.append(args) or incoming,
        admission_session=session,
    )

    assert len(calls) == 1
    assert result["BTC-USD"].updated is True
    assert pd.read_csv(path)["date"].tolist() == [
        "2026-07-10",
        "2026-07-11",
        "2026-07-12",
    ]


def test_btc_spot_witness_weekend_mismatch_preserves_canonical(tmp_path):
    path = tmp_path / "BTC_USD.csv"
    path.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-07-10,99,101,98,100,100,1000\n",
        encoding="utf-8",
    )
    before = path.read_bytes()
    incoming = pd.DataFrame(
        {
            "Open": [119.0],
            "High": [121.0],
            "Low": [118.0],
            "Close": [120.0],
            "Adj Close": [120.0],
            "Volume": [9e9],
        },
        index=pd.to_datetime(["2026-07-11"]),
    )
    session = MarketAdmissionSession(
        enabled=True,
        witness_bars={"BTC-USD": [{"t": "2026-07-11T00:00:00Z", "c": 100.0}]},
        btc_spot_witness_enabled=True,
        btc_completed_through="2026-07-11",
        requested_start="2026-07-11",
        requested_end="2026-07-12",
    )

    result = backfill(
        ["BTC-USD"],
        start="2026-07-10",
        end="2026-07-12",
        store_dir=tmp_path,
        downloader=lambda *_args: incoming,
        admission_session=session,
    )

    assert path.read_bytes() == before
    assert result["BTC-USD"].updated is False
    assert session.payload()["status"] == "BLOCKED"


def test_btc_weekend_interval_keeps_legacy_skip_when_spot_witness_is_off(tmp_path):
    path = tmp_path / "BTC_USD.csv"
    path.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-07-10,99,101,98,100,100,1000\n",
        encoding="utf-8",
    )
    session = MarketAdmissionSession(
        enabled=True,
        witness_bars={},
        btc_spot_witness_enabled=False,
    )
    calls = []

    result = backfill(
        ["BTC-USD"],
        start="2026-07-10",
        end="2026-07-12",
        store_dir=tmp_path,
        downloader=lambda *args: calls.append(args) or pd.DataFrame(),
        admission_session=session,
    )

    assert calls == []
    assert result["BTC-USD"].updated is False
    assert path.read_text(encoding="utf-8").endswith("2026-07-10,99,101,98,100,100,1000\n")


def test_backfill_market_admission_flag_prefetches_and_writes_evidence(tmp_path, monkeypatch):
    from hermes_escape_top.scripts import backfill_history as module

    history = tmp_path / "history"
    archive = tmp_path / "archive"
    history.mkdir()
    (history / "QQQ.csv").write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-07-10,99,101,98,100,100,1000\n",
        encoding="utf-8",
    )
    incoming = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [102.0],
            "Low": [99.0],
            "Close": [101.0],
            "Adj Close": [101.0],
            "Volume": [1_100.0],
        },
        index=pd.to_datetime(["2026-07-13"]),
    )
    prepared = []
    written = []

    def prepare(symbols, start, end, **kwargs):
        prepared.append((list(symbols), start, end, kwargs))
        return MarketAdmissionSession(
            enabled=True,
            witness_bars={
                "QQQ": [
                    {
                        "t": "2026-07-13T04:00:00Z",
                        "o": 100.0,
                        "h": 102.0,
                        "l": 99.0,
                        "c": 101.0,
                        "v": 1_100.0,
                    }
                ]
            },
            requested_start=start,
            requested_end=end,
        )

    monkeypatch.setattr(
        module,
        "load_config",
        lambda: {
            "features": {
                "use_market_admission_gate": True,
                "use_btc_spot_witness": True,
            },
            "paths": {"archive_dir": str(archive)},
        },
    )
    monkeypatch.setattr(module, "_download_yfinance", lambda *_args: incoming)
    monkeypatch.setattr(module, "prepare_market_admission_session", prepare)
    monkeypatch.setattr(
        module,
        "write_market_admission_evidence",
        lambda path, payload: written.append((path, payload)),
    )

    result = backfill(
        ["QQQ"],
        start="2026-07-01",
        end="2026-07-14",
        store_dir=history,
        repair_overlap_days=3,
    )

    assert result["QQQ"].updated is True
    assert prepared == [
        (
            ["QQQ"],
            "2026-07-07",
            "2026-07-14",
            {"btc_spot_witness_enabled": True},
        )
    ]
    assert written[0][0] == archive
    assert written[0][1]["status"] == "OK"


def test_market_admission_daily_range_uses_tail_even_when_head_is_missing(tmp_path):
    (tmp_path / "QQQ.csv").write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-07-10,99,101,98,100,100,1000\n",
        encoding="utf-8",
    )

    start = _market_admission_start(
        ["QQQ"],
        tmp_path,
        "2026-07-01",
        repair_overlap_days=3,
    )

    assert start == "2026-07-07"


def test_market_admission_explicit_repair_includes_missing_history_head(tmp_path):
    (tmp_path / "QQQ.csv").write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-07-10,99,101,98,100,100,1000\n",
        encoding="utf-8",
    )

    start = _market_admission_start(
        ["QQQ"],
        tmp_path,
        "2026-07-01",
        repair_overlap_days=3,
        repair_history_head=True,
    )

    assert start == "2026-07-01"


def test_backfill_daily_tail_does_not_request_prelisting_head(tmp_path, monkeypatch):
    from hermes_escape_top.scripts import backfill_history as module

    history = tmp_path / "history"
    history.mkdir()
    (history / "BOXX.csv").write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-07-10,99,101,98,100,100,1000\n",
        encoding="utf-8",
    )
    calls = []

    monkeypatch.setattr(
        module,
        "load_config",
        lambda: {"features": {"use_market_admission_gate": False}},
    )

    def download(symbol, start, end):
        calls.append((symbol, start, end))
        return pd.DataFrame()

    backfill(
        ["BOXX"],
        start="2018-01-01",
        end="2026-07-14",
        store_dir=history,
        downloader=download,
        repair_overlap_days=3,
    )

    assert calls == [("BOXX", "2026-07-07", "2026-07-14")]


def test_backfill_market_admission_flag_off_does_not_fetch_witness(tmp_path, monkeypatch):
    from hermes_escape_top.scripts import backfill_history as module

    history = tmp_path / "history"
    history.mkdir()
    incoming = pd.DataFrame(
        {
            "Open": [99.0],
            "High": [101.0],
            "Low": [98.0],
            "Close": [100.0],
            "Adj Close": [100.0],
            "Volume": [1_000.0],
        },
        index=pd.to_datetime(["2026-07-13"]),
    )
    monkeypatch.setattr(
        module,
        "load_config",
        lambda: {"features": {"use_market_admission_gate": False}},
    )
    monkeypatch.setattr(module, "_download_yfinance", lambda *_args: incoming)
    monkeypatch.setattr(
        module,
        "prepare_market_admission_session",
        lambda *_args: (_ for _ in ()).throw(AssertionError("witness must stay off")),
    )

    result = backfill(
        ["QQQ"],
        start="2026-07-13",
        end="2026-07-14",
        store_dir=history,
    )

    assert result["QQQ"].updated is True
    assert pd.read_csv(history / "QQQ.csv")["date"].tolist() == ["2026-07-13"]


def test_backfill_market_admission_records_run_failure_in_evidence(tmp_path, monkeypatch):
    from hermes_escape_top.scripts import backfill_history as module

    history = tmp_path / "history"
    archive = tmp_path / "archive"
    history.mkdir()
    qqq = history / "QQQ.csv"
    qqq.write_text("date,close\n2026-07-10,100\n", encoding="utf-8")
    before = qqq.read_bytes()
    captured = []
    session = MarketAdmissionSession(enabled=True, witness_bars={})

    monkeypatch.setattr(
        module,
        "load_config",
        lambda: {
            "features": {"use_market_admission_gate": True},
            "paths": {"archive_dir": str(archive)},
        },
    )
    monkeypatch.setattr(module, "prepare_market_admission_session", lambda *_args: session)
    def partial_write_then_fail(symbol, _start, _end, store, *_args, **_kwargs):
        if symbol == "QQQ":
            (store / "QQQ.csv").write_text(
                "date,close\n2026-07-10,100\n2026-07-13,101\n",
                encoding="utf-8",
            )
            return None
        raise OSError("disk write failed")

    monkeypatch.setattr(module, "_backfill_one", partial_write_then_fail)
    monkeypatch.setattr(
        module,
        "write_market_admission_evidence",
        lambda _path, payload: captured.append(payload),
    )

    try:
        backfill(
            ["QQQ", "SPY"],
            start="2026-07-13",
            end="2026-07-14",
            store_dir=history,
        )
    except OSError as exc:
        assert str(exc) == "disk write failed"
    else:
        raise AssertionError("backfill failure must propagate")

    assert captured[0]["status"] == "ERROR"
    assert captured[0]["run_error"] == "OSError: disk write failed"
    assert qqq.read_bytes() == before


def test_backfill_batch_does_not_publish_first_symbol_when_second_fails(
    tmp_path,
    monkeypatch,
):
    from hermes_escape_top.scripts import backfill_history as module

    history = tmp_path / "history"
    history.mkdir()
    old = (
        "date,open,high,low,close,adj_close,volume\n"
        "2026-07-10,99,101,98,100,100,1000\n"
    )
    for symbol in ("QQQ", "SPY"):
        (history / f"{symbol}.csv").write_text(old, encoding="utf-8")
    before = {symbol: (history / f"{symbol}.csv").read_bytes() for symbol in ("QQQ", "SPY")}
    incoming = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [102.0],
            "Low": [99.0],
            "Close": [101.0],
            "Adj Close": [101.0],
            "Volume": [1_100.0],
        },
        index=pd.to_datetime(["2026-07-13"]),
    )
    original = module._backfill_one

    def fail_second(symbol, *args, **kwargs):
        if symbol == "SPY":
            raise OSError("second symbol failed")
        return original(symbol, *args, **kwargs)

    monkeypatch.setattr(module, "_backfill_one", fail_second)

    try:
        backfill(
            ["QQQ", "SPY"],
            start="2026-07-13",
            end="2026-07-14",
            store_dir=history,
            downloader=lambda *_args: incoming,
        )
    except OSError as exc:
        assert str(exc) == "second symbol failed"
    else:
        raise AssertionError("batch failure must propagate")

    assert {
        symbol: (history / f"{symbol}.csv").read_bytes()
        for symbol in ("QQQ", "SPY")
    } == before


def test_history_transaction_manifest_precedes_market_admission_evidence(
    tmp_path,
    monkeypatch,
):
    from hermes_escape_top.scripts import backfill_history as module

    history = tmp_path / "history"
    archive = tmp_path / "archive"
    history.mkdir()
    (history / "QQQ.csv").write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-07-10,99,101,98,100,100,1000\n",
        encoding="utf-8",
    )
    incoming = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [102.0],
            "Low": [99.0],
            "Close": [101.0],
            "Adj Close": [101.0],
            "Volume": [1_100.0],
        },
        index=pd.to_datetime(["2026-07-13"]),
    )
    session = MarketAdmissionSession(
        enabled=True,
        witness_bars={
            "QQQ": [
                {
                    "t": "2026-07-13T04:00:00Z",
                    "o": 100.0,
                    "h": 102.0,
                    "l": 99.0,
                    "c": 101.0,
                    "v": 1_100.0,
                }
            ]
        },
    )
    observed = []

    def write_evidence(_archive, payload):
        manifests = list((history / ".history_transactions").glob("*/manifest.json"))
        assert len(manifests) == 1
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        observed.append((manifest["state"], payload["status"]))

    monkeypatch.setattr(module, "write_market_admission_evidence", write_evidence)

    backfill(
        ["QQQ"],
        start="2026-07-13",
        end="2026-07-14",
        store_dir=history,
        downloader=lambda *_args: incoming,
        admission_session=session,
        admission_archive=archive,
    )

    assert observed == [("PROMOTING", "OK")]


def test_backfill_market_admission_rolls_back_when_evidence_write_fails(tmp_path, monkeypatch):
    from hermes_escape_top.scripts import backfill_history as module

    history = tmp_path / "history"
    archive = tmp_path / "archive"
    history.mkdir()
    qqq = history / "QQQ.csv"
    qqq.write_text("date,close\n2026-07-10,100\n", encoding="utf-8")
    before = qqq.read_bytes()

    monkeypatch.setattr(
        module,
        "load_config",
        lambda: {
            "features": {"use_market_admission_gate": True},
            "paths": {"archive_dir": str(archive)},
        },
    )
    monkeypatch.setattr(
        module,
        "prepare_market_admission_session",
        lambda *_args: MarketAdmissionSession(enabled=True, witness_bars={}),
    )

    def write_candidate(_symbol, _start, _end, store, *_args, **_kwargs):
        (store / "QQQ.csv").write_text(
            "date,close\n2026-07-10,100\n2026-07-13,101\n",
            encoding="utf-8",
        )
        return None

    monkeypatch.setattr(module, "_backfill_one", write_candidate)
    monkeypatch.setattr(
        module,
        "write_market_admission_evidence",
        lambda *_args: (_ for _ in ()).throw(OSError("evidence disk full")),
    )

    try:
        backfill(
            ["QQQ"],
            start="2026-07-13",
            end="2026-07-14",
            store_dir=history,
        )
    except RuntimeError as exc:
        assert "evidence recovery was incomplete" in str(exc)
    else:
        raise AssertionError("evidence failure must fail the guarded promotion")

    assert qqq.read_bytes() == before


def test_shared_market_admission_session_keeps_batch_evidence_during_self_heal(
    tmp_path,
    monkeypatch,
):
    from hermes_escape_top.scripts import backfill_history as module

    archive = tmp_path / "archive"
    captured = []
    session = MarketAdmissionSession(
        enabled=True,
        witness_bars={
            "QQQ": [
                {
                    "t": "2026-07-13T04:00:00Z",
                    "o": 79.0,
                    "h": 81.0,
                    "l": 78.0,
                    "c": 80.0,
                    "v": 1_000.0,
                }
            ]
        },
    )
    candidate = pd.DataFrame(
        {
            "Open": [99.0],
            "High": [101.0],
            "Low": [98.0],
            "Close": [100.0],
            "Adj Close": [100.0],
            "Volume": [1_000.0],
        },
        index=pd.to_datetime(["2026-07-13"]),
    )
    monkeypatch.setattr(
        module,
        "write_market_admission_evidence",
        lambda _path, payload: captured.append(payload.copy()),
    )

    backfill(
        ["QQQ"],
        start="2026-07-13",
        end="2026-07-14",
        store_dir=tmp_path / "history",
        downloader=lambda *_args: candidate,
        admission_session=session,
        admission_archive=archive,
    )
    backfill(
        ["SPY"],
        start="2026-07-13",
        end="2026-07-14",
        store_dir=tmp_path / "history",
        downloader=lambda *_args: pd.DataFrame(),
        admission_session=session,
        admission_archive=archive,
    )

    assert [payload["status"] for payload in captured] == ["BLOCKED", "BLOCKED"]
    assert captured[-1]["summary"] == {"PRICE_MISMATCH": 1}


def test_backfill_skips_initial_holiday_gap_before_first_cached_bar(tmp_path):
    path = tmp_path / "_VIX.csv"
    path.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2018-01-02,14,15,13,14.0,14.0,0\n",
        encoding="utf-8",
    )
    calls = []

    def downloader(symbol, start, end):
        calls.append((symbol, start, end))
        return pd.DataFrame()

    result = backfill(
        ["^VIX"],
        start="2018-01-01",
        end="2018-01-02",
        store_dir=tmp_path,
        downloader=downloader,
        repair_overlap_days=0,
        repair_history_head=True,
    )

    assert calls == []
    assert result["^VIX"].updated is False
    assert "skipped no trading days" in result["^VIX"].reason


def test_backfill_does_not_skip_federal_holidays_when_market_usually_opens(tmp_path):
    path = tmp_path / "QQQ.csv"
    path.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-11-12,700,701,699,700.0,700.0,100\n",
        encoding="utf-8",
    )
    calls = []

    def downloader(symbol, start, end):
        calls.append((symbol, start, end))
        return pd.DataFrame()

    backfill(
        ["QQQ"],
        start="2026-11-11",
        end="2026-11-12",
        store_dir=tmp_path,
        downloader=downloader,
        repair_overlap_days=0,
        repair_history_head=True,
    )

    assert calls == [("QQQ", "2026-11-11", "2026-11-12")]


def test_vol_index_gets_wider_band_but_still_catches_cross_wiring():
    existing = _frame([15.4])
    ok, _ = _sanity_check_download("^VIX", existing, _frame([38.0], start="2026-06-02"))
    assert ok  # VIX 2.5x in a day is a real regime, not corruption
    ok, why = _sanity_check_download("^VIX", existing, _frame([12906.0], start="2026-06-02"))
    assert not ok  # ^SOX values under a ^VIX name


def test_overlap_anchor_mismatch_rejected():
    existing = _frame([700, 705, 710, 715, 720])
    garbage_repair = _frame([210, 212, 215, 214], start="2026-06-02")
    ok, why = _sanity_check_download("QQQ", existing, garbage_repair)
    assert not ok and "anchor" in why


def test_overlap_anchor_match_accepts_repair():
    existing = _frame([700, 705, 31.4, 715, 720])      # one corrupt mid row
    repair = _frame([705, 708, 712, 718], start="2026-06-02")  # anchors on clean 705
    ok, _ = _sanity_check_download("FNGS", existing, repair)
    assert ok


def test_integrity_scan_flags_cross_wired_file(tmp_path, monkeypatch):
    import importlib
    rdp = importlib.import_module("hermes_escape_top.scripts.run_daily_package")
    hist = tmp_path / "data" / "history"
    hist.mkdir(parents=True)
    (hist / "QQQ.csv").write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-06-04,740,745,738,742,742,1000\n"
        "2026-06-05,741,744,700,705,705,1000\n"
        "2026-06-08,220,221,214,217,217,1000\n")
    (hist / "_VIX.csv").write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-06-04,15,16,14,15.4,15.4,0\n"
        "2026-06-05,20,22,19,21.5,21.5,0\n")
    (hist / "KLAC.csv").write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-06-05,2043,2055,1928,1929.2,1929.2,1000\n"
        "2026-06-08,203,214,200,210.8,210.8,10000\n")
    monkeypatch.setenv("HERMES_DATA_DIR", str(tmp_path))
    from hermes_escape_top.config import load_config
    offenders = rdp._history_integrity_scan(load_config())
    assert any("QQQ.csv" in o for o in offenders)          # cross-wired bar caught
    assert not any("_VIX" in o for o in offenders)          # real VIX spike tolerated
    assert not any("KLAC.csv" in o for o in offenders)      # component split does not block scoring


def test_web_refresh_integrity_scan_flags_cross_wired_file(tmp_path):
    import importlib
    refresh = importlib.import_module("hermes_escape_top.web.refresh")
    hist = tmp_path / "history"
    hist.mkdir()
    (hist / "QQQ.csv").write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-06-04,740,745,738,742,742,1000\n"
        "2026-06-05,741,744,700,705,705,1000\n"
        "2026-06-08,220,221,214,217,217,1000\n",
        encoding="utf-8",
    )
    (hist / "_VIX.csv").write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-06-04,15,16,14,15.4,15.4,0\n"
        "2026-06-05,20,22,19,21.5,21.5,0\n",
        encoding="utf-8",
    )
    (hist / "KLAC.csv").write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-06-05,2043,2055,1928,1929.2,1929.2,1000\n"
        "2026-06-08,203,214,200,210.8,210.8,10000\n",
        encoding="utf-8",
    )

    offenders = refresh._history_integrity_scan({"paths": {"history_dir": str(hist)}})

    assert any("QQQ.csv" in item for item in offenders)
    assert not any("_VIX" in item for item in offenders)
    assert not any("KLAC.csv" in item for item in offenders)


def test_integrity_scans_reject_latest_bar_without_close(tmp_path):
    import importlib
    refresh = importlib.import_module("hermes_escape_top.web.refresh")
    rdp = importlib.import_module("hermes_escape_top.scripts.run_daily_package")
    hist = tmp_path / "history"
    hist.mkdir()
    (hist / "DBMF.csv").write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-06-17,30.68,30.77,30.61,30.67,30.67,1246700\n"
        "2026-06-18,30.73,30.94,30.61,,,1630478\n",
        encoding="utf-8",
    )
    cfg = {"paths": {"history_dir": str(hist)}}

    assert any("DBMF.csv latest row 2026-06-18 missing close" in item
               for item in refresh._history_integrity_scan(cfg))
    assert any("DBMF.csv latest row 2026-06-18 missing close" in item
               for item in rdp._history_integrity_scan(cfg))


def test_web_refresh_aborts_before_scoring_on_integrity_failure(tmp_path, monkeypatch):
    import importlib
    refresh = importlib.import_module("hermes_escape_top.web.refresh")
    cfg = {
        "paths": {
            "archive_dir": str(tmp_path / "archive"),
            "history_dir": str(tmp_path / "history"),
        },
        "symbols": {"MSTR": {}, "FNGU": {}, "SOXL": {}},
        "market_symbols": [],
        "radars": {},
        "component_proxies": {},
    }
    captured = {}

    monkeypatch.setattr(refresh, "load_config", lambda: cfg)
    monkeypatch.setattr(refresh, "latest_history_date", lambda *_args, **_kwargs: "2026-06-11")
    monkeypatch.setattr(refresh, "_history_is_fresh", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(refresh, "_stale_symbols", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(refresh, "_history_integrity_scan", lambda _cfg: ["QQQ.csv 2026-06-05 705.00 -> 2026-06-08 217.00"])
    monkeypatch.setattr(refresh, "_score_pipeline_locked", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("score_pipeline should not run")))

    def fake_write_refresh_run(*_args, **kwargs):
        captured.update(kwargs)
        return {"state_db_path": str(tmp_path / "archive" / "hermes_state.sqlite"), "refresh_run_id": 1}

    monkeypatch.setattr(refresh, "write_refresh_run", fake_write_refresh_run)

    try:
        refresh.refresh_score_with_market_data("latest")
    except RuntimeError as exc:
        assert "history integrity failed" in str(exc)
    else:
        raise AssertionError("refresh should abort on history integrity failure")

    assert captured["status"] == "ERROR"
    assert captured["refresh_status"]["history_integrity"]["offender_count"] == 1


def test_cboe_daily_pcr_parse_and_cross_check():
    from hermes_escape_top.scripts.refresh_cboe_daily_pcr import parse_page, validate
    body = ('x"EQUITY OPTIONS\\":[{\\"name\\":\\"VOLUME\\",\\"call\\":2598064,\\"put\\":1454199,'
            '\\"total\\":4052263}]y\\"selectedDate\\":\\"2026-06-11\\"z'
            '\\"EQUITY PUT/CALL RATIO\\",\\"value\\":\\"0.56\\"w')
    rec = parse_page(body)
    assert rec == {"date": "2026-06-11", "ratio": 0.56,
                   "call_volume": 2598064, "put_volume": 1454199}
    assert validate(rec, "2026-06-10") is None
    assert "not newer" in validate(rec, "2026-06-11")
    bad = dict(rec, ratio=0.90)
    assert "cross-check" in validate(bad, "2026-06-10")


def test_aaii_public_parse_and_validation():
    from datetime import date
    from hermes_escape_top.scripts.refresh_aaii_public import parse_rows, validate
    body = ('<td align="left" class="tableTxt">Jun 10</td>'
            '<td align="right" class="tableTxt">30.4% </td>'
            '<td align="right" class="tableTxt">22.0%</td>'
            '<td align="right" class="tableTxt">47.7% </td>'
            '<td align="left" class="tableTxt">Dec 31</td>'
            '<td align="right" class="tableTxt">40.0% </td>'
            '<td align="right" class="tableTxt">30.0%</td>'
            '<td align="right" class="tableTxt">30.0% </td>')
    rows = parse_rows(body, today=date(2026, 6, 12))
    assert rows[0]["reported"] == date(2026, 6, 10)
    assert rows[1]["reported"] == date(2025, 12, 31)   # year boundary inferred
    assert validate(rows[0]) is None
    assert "sum" in validate({"bull": 0.2, "neutral": 0.2, "bear": 0.2})


def test_ticker_name_mismatch_rejected():
    import pandas as pd
    from hermes_escape_top.scripts.backfill_history import _normalize_download
    idx = pd.bdate_range("2026-06-08", periods=2)
    wrong = pd.DataFrame({("Close", "TSLA"): [700.0, 705.0]}, index=idx)
    try:
        _normalize_download(wrong, expected_symbol="QQQ")
    except ValueError as exc:
        assert "ticker mismatch" in str(exc)
    else:
        raise AssertionError("mismatched ticker must be rejected")
    ok = pd.DataFrame({("Close", "QQQ"): [700.0, 705.0]}, index=idx)
    assert not _normalize_download(ok, expected_symbol="QQQ").empty


def test_anchor_majority_breaks_corrupt_cache_deadlock():
    existing = _frame([31.4, 705, 710, 715, 720])       # corrupt FIRST cached row
    repair = _frame([702, 706, 711, 716], start="2026-06-01")  # good data, anchors 3 oldest
    ok, why = _sanity_check_download("FNGS", existing, repair)
    assert ok, why                                       # 2/3 clean anchors outvote
    garbage = _frame([70, 71, 72, 73], start="2026-06-01")
    ok, why = _sanity_check_download("FNGS", existing, garbage)
    assert not ok and "majority" in why                  # garbage loses every vote


def test_no_advice_state_flag(tmp_path, monkeypatch):
    """critical-missing + flag ON -> NO_ADVICE/sell 0; flag OFF -> legacy."""
    from types import SimpleNamespace
    import hermes_escape_top.core.scoring.scorer as scorer_mod
    # exercise just the override logic via a tiny shim of the construction inputs
    src = open(scorer_mod.__file__).read()
    assert 'use_no_advice_state' in src and 'NO_ADVICE' in src
    # NO_ADVICE must clear hard-valve hits so routing/sizing/reentry treat it as
    # no-action (not a hard EXIT). Pin the clearing so the seam can't reopen.
    assert 'hard_valve_hits=([] if _no_advice else hard.ids)' in src
    # Deployed ON 2026-06-14 (proven no-op: close zero-missing 2018-2026 + the
    # behavioral test in test_phase3_scoring). Pin it ON so an accidental revert
    # to the fake-100-EXIT behavior fails here.
    from hermes_escape_top.config import load_config
    assert load_config()["features"]["use_no_advice_state"] is True


def test_market_admission_gate_defaults_off():
    from hermes_escape_top.config import load_config

    assert load_config()["features"]["use_market_admission_gate"] is False


def test_btc_spot_witness_defaults_off():
    from hermes_escape_top.config import load_config

    assert load_config()["features"]["use_btc_spot_witness"] is False
