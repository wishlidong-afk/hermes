from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib

import pandas as pd

from hermes_escape_top.core.data.market_admission import MarketAdmissionSession
from hermes_escape_top.core.data.market_admission import (
    prepare_market_admission_session,
    read_market_admission_evidence,
    latest_completed_us_market_session,
    validate_market_admission_evidence,
    write_market_admission_evidence,
)


def _candidate(close: float = 100.0, volume: float = 1_000.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [99.0],
            "High": [101.0],
            "Low": [98.0],
            "Close": [close],
            "Adj Close": [close],
            "Volume": [volume],
        },
        index=pd.to_datetime(["2026-07-13"]),
    )


def _witness(close: float = 100.0, volume: float = 1_000.0) -> dict:
    return {
        "t": "2026-07-13T04:00:00Z",
        "o": 99.0,
        "h": 101.0,
        "l": 98.0,
        "c": close,
        "v": volume,
    }


def _btc_witness(close: float = 100.0) -> dict:
    return {
        "t": "2026-07-13T00:00:00Z",
        "o": close - 1.0,
        "h": close + 1.0,
        "l": close - 2.0,
        "c": close,
        "v": 12.5,
    }


def test_market_admission_promotes_only_matching_supported_row() -> None:
    session = MarketAdmissionSession(
        enabled=True,
        witness_bars={"QQQ": [_witness()]},
    )

    admitted, evidence = session.admit("QQQ", _candidate())

    assert list(admitted.index) == [pd.Timestamp("2026-07-13")]
    hashes = {
        "candidate_sha256": evidence[0]["candidate_sha256"],
        "witness_sha256": evidence[0]["witness_sha256"],
    }
    business_evidence = [
        {
            key: value
            for key, value in row.items()
            if key not in {"candidate_sha256", "witness_sha256"}
        }
        for row in evidence
    ]
    assert business_evidence == [
        {
            "symbol": "QQQ",
            "date": "2026-07-13",
            "status": "MATCH",
            "admitted": True,
            "reason": "raw OHLC and volume agree within witness policy",
            "warning_band": False,
            "close_diff_pct": 0.0,
            "max_ohlc_diff_pct": 0.0,
            "volume_diff_pct": 0.0,
        }
    ]
    assert all(len(value) == 64 for value in hashes.values())


def test_market_admission_freezes_price_mismatch() -> None:
    session = MarketAdmissionSession(
        enabled=True,
        witness_bars={"QQQ": [_witness(close=80.0)]},
    )

    admitted, evidence = session.admit("QQQ", _candidate())

    assert admitted.empty
    assert evidence[0]["status"] == "PRICE_MISMATCH"
    assert evidence[0]["admitted"] is False


def test_market_admission_selects_matching_position_when_candidate_dates_repeat() -> None:
    candidate = pd.concat([_candidate(close=100.0), _candidate(close=120.0)])
    session = MarketAdmissionSession(
        enabled=True,
        witness_bars={"QQQ": [_witness(close=100.0)]},
    )

    admitted, evidence = session.admit("QQQ", candidate)

    assert list(admitted["Close"]) == [100.0]
    assert [row["status"] for row in evidence] == ["MATCH", "PRICE_MISMATCH"]


def test_market_admission_freezes_missing_witness() -> None:
    session = MarketAdmissionSession(enabled=True, witness_bars={"QQQ": []})

    admitted, evidence = session.admit("QQQ", _candidate())

    assert admitted.empty
    assert evidence[0]["status"] == "NO_WITNESS"
    assert evidence[0]["admitted"] is False


def test_market_admission_freezes_when_any_ohlc_field_is_not_comparable() -> None:
    witness = _witness()
    witness["h"] = None
    session = MarketAdmissionSession(enabled=True, witness_bars={"QQQ": [witness]})

    admitted, evidence = session.admit("QQQ", _candidate())

    assert admitted.empty
    assert evidence[0]["status"] == "PRICE_MISMATCH"
    assert evidence[0]["reason"] == "all raw OHLC fields must be comparable"


def test_market_admission_freezes_when_volume_is_not_comparable() -> None:
    witness = _witness()
    witness["v"] = None
    session = MarketAdmissionSession(enabled=True, witness_bars={"QQQ": [witness]})

    admitted, evidence = session.admit("QQQ", _candidate())

    assert admitted.empty
    assert evidence[0]["status"] == "VOLUME_MISMATCH"
    assert evidence[0]["reason"] == "raw volume must be comparable"


def test_market_admission_does_not_gate_unsupported_index() -> None:
    session = MarketAdmissionSession(enabled=True, witness_bars={})

    admitted, evidence = session.admit("^VIX", _candidate())

    assert list(admitted.index) == [pd.Timestamp("2026-07-13")]
    assert evidence[0]["status"] == "NOT_APPLICABLE"
    assert evidence[0]["admitted"] is True


def test_btc_spot_witness_admits_close_match_without_comparing_volume() -> None:
    session = MarketAdmissionSession(
        enabled=True,
        witness_bars={"BTC-USD": [_btc_witness(close=100.6)]},
        btc_spot_witness_enabled=True,
        btc_completed_through="2026-07-13",
    )

    admitted, evidence = session.admit("BTC-USD", _candidate(close=100.0, volume=9e9))

    assert list(admitted.index) == [pd.Timestamp("2026-07-13")]
    assert evidence[0]["status"] == "MATCH"
    assert evidence[0]["warning_band"] is True
    assert evidence[0]["witness_source"] == "COINBASE_EXCHANGE_BTC_USD_1DAY"
    assert "volume_diff_pct" not in evidence[0]


def test_btc_spot_witness_freezes_close_mismatch() -> None:
    session = MarketAdmissionSession(
        enabled=True,
        witness_bars={"BTC-USD": [_btc_witness(close=97.0)]},
        btc_spot_witness_enabled=True,
        btc_completed_through="2026-07-13",
    )

    admitted, evidence = session.admit("BTC-USD", _candidate(close=100.0))

    assert admitted.empty
    assert evidence[0]["status"] == "PRICE_MISMATCH"
    assert evidence[0]["admitted"] is False
    assert session.payload()["status"] == "BLOCKED"


def test_btc_spot_witness_selects_matching_position_when_candidate_dates_repeat() -> None:
    candidate = pd.concat([_candidate(close=100.0), _candidate(close=120.0)])
    session = MarketAdmissionSession(
        enabled=True,
        witness_bars={"BTC-USD": [_btc_witness(close=100.0)]},
        btc_spot_witness_enabled=True,
        btc_completed_through="2026-07-13",
    )

    admitted, evidence = session.admit("BTC-USD", candidate)

    assert list(admitted["Close"]) == [100.0]
    assert [row["status"] for row in evidence] == ["MATCH", "PRICE_MISMATCH"]


def test_btc_spot_witness_defers_open_utc_day_without_blocking_health() -> None:
    candidate = _candidate(close=100.0)
    candidate.index = pd.to_datetime(["2026-07-14"])
    session = MarketAdmissionSession(
        enabled=True,
        witness_bars={"BTC-USD": []},
        btc_spot_witness_enabled=True,
        btc_completed_through="2026-07-13",
    )

    admitted, evidence = session.admit("BTC-USD", candidate)
    payload = session.payload()

    assert admitted.empty
    assert evidence[0]["status"] == "DEFERRED_UNFINALIZED"
    assert evidence[0]["blocking"] is False
    assert payload["status"] == "OK"
    assert payload["rejected_rows"] == 0
    assert payload["deferred_rows"] == 1


def test_btc_spot_witness_flag_off_preserves_legacy_bypass_payload() -> None:
    session = MarketAdmissionSession(
        enabled=True,
        witness_bars={"BTC-USD": [_btc_witness()]},
        btc_spot_witness_enabled=False,
    )

    admitted, evidence = session.admit("BTC-USD", _candidate())
    payload = session.payload(generated_at="2026-07-14T03:00:00+00:00")

    assert list(admitted.index) == [pd.Timestamp("2026-07-13")]
    assert evidence[0] == {
        "symbol": "BTC-USD",
        "date": "2026-07-13",
        "status": "NOT_APPLICABLE",
        "admitted": True,
        "reason": "Alpaca SIP admission does not apply",
    }
    assert payload["schema_version"] == "hermes-market-admission-v1"
    assert payload["source"] == "YAHOO_PLUS_ALPACA_SIP"
    assert "btc_spot_witness" not in payload
    assert "deferred_rows" not in payload


def test_prepare_market_admission_keeps_alpaca_evidence_when_coinbase_fails() -> None:
    def alpaca_transport(_url, _headers):
        return {"bars": {"QQQ": [_witness()]}, "next_page_token": None}

    def coinbase_transport(_url, _headers):
        raise TimeoutError("Coinbase unavailable")

    session = prepare_market_admission_session(
        ["QQQ", "BTC-USD"],
        "2026-07-10",
        "2026-07-14",
        credentials={"key": "key", "secret": "secret"},
        request_json=alpaca_transport,
        btc_spot_witness_enabled=True,
        coinbase_request_json=coinbase_transport,
        now=datetime(2026, 7, 14, 5, 0, tzinfo=timezone.utc),
    )

    qqq, qqq_evidence = session.admit("QQQ", _candidate())
    btc, btc_evidence = session.admit("BTC-USD", _candidate())
    payload = session.payload()

    assert list(qqq.index) == [pd.Timestamp("2026-07-13")]
    assert qqq_evidence[0]["status"] == "MATCH"
    assert btc.empty
    assert btc_evidence[0]["status"] == "NO_WITNESS"
    assert payload["status"] == "FETCH_ERROR"
    assert "Coinbase unavailable" in payload["fetch_error"]
    assert payload["btc_spot_witness"]["completed_through"] == "2026-07-13"


def test_prepare_market_admission_keeps_partial_coinbase_failure_provenance() -> None:
    calls = 0

    def coinbase_transport(_url, _headers):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise TimeoutError("second chunk failed")
        return []

    session = prepare_market_admission_session(
        ["BTC-USD"],
        "2025-01-01",
        "2026-07-01",
        btc_spot_witness_enabled=True,
        coinbase_request_json=coinbase_transport,
        now=datetime(2026, 7, 2, 5, 0, tzinfo=timezone.utc),
    )

    provenance = session.payload()["btc_spot_witness"]["provenance"]
    assert len(provenance["requests"]) == 2
    assert provenance["requests"][-1]["status"] == "ERROR"


def test_coinbase_failure_is_not_misattributed_to_a_missing_alpaca_row() -> None:
    session = MarketAdmissionSession(
        enabled=True,
        witness_bars={"QQQ": [], "BTC-USD": []},
        btc_spot_witness_enabled=True,
        btc_completed_through="2026-07-13",
        witness_errors={"coinbase": "TimeoutError: Coinbase unavailable"},
        fetch_error="COINBASE: TimeoutError: Coinbase unavailable",
    )

    _admitted, evidence = session.admit("QQQ", _candidate())

    assert evidence[0]["status"] == "NO_WITNESS"
    assert "fetch_error" not in evidence[0]


def test_market_admission_fetch_failure_becomes_blocking_evidence() -> None:
    def fail(_url, _headers):
        raise TimeoutError("Alpaca unavailable")

    session = prepare_market_admission_session(
        ["QQQ"],
        "2026-07-10",
        "2026-07-14",
        credentials={"key": "key", "secret": "secret"},
        request_json=fail,
    )

    admitted, evidence = session.admit("QQQ", _candidate())

    assert admitted.empty
    assert session.fetch_error == "TimeoutError: Alpaca unavailable"
    assert evidence[0]["status"] == "NO_WITNESS"
    assert evidence[0]["fetch_error"] == "TimeoutError: Alpaca unavailable"
    assert session.payload()["status"] == "FETCH_ERROR"


def test_market_admission_writes_atomic_summary(tmp_path) -> None:
    session = MarketAdmissionSession(
        enabled=True,
        witness_bars={"QQQ": [_witness(close=80.0)]},
        requested_start="2026-07-10",
        requested_end="2026-07-14",
    )
    session.admit("QQQ", _candidate())

    payload = session.payload(generated_at="2026-07-14T03:00:00+00:00")
    path = write_market_admission_evidence(tmp_path, payload)

    assert payload["status"] == "BLOCKED"
    assert payload["summary"] == {"PRICE_MISMATCH": 1}
    assert payload["admitted_rows"] == 0
    assert payload["rejected_rows"] == 1
    assert path == tmp_path / "market_admission_latest.json"
    assert path.exists()
    assert (tmp_path / "market_admission_2026-07-14.json").exists()
    assert read_market_admission_evidence(tmp_path) == payload


def test_market_admission_dated_evidence_uses_shanghai_operating_day(tmp_path) -> None:
    session = MarketAdmissionSession(enabled=True, witness_bars={})
    payload = session.payload(generated_at="2026-07-13T22:45:00+00:00")

    write_market_admission_evidence(tmp_path, payload)

    assert (tmp_path / "market_admission_2026-07-14.json").exists()
    assert not (tmp_path / "market_admission_2026-07-13.json").exists()


def test_market_admission_v2_validator_checks_provenance_and_row_consistency(tmp_path) -> None:
    history = tmp_path / "history"
    history.mkdir()
    (history / "BTC_USD.csv").write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-07-13,99,101,98,100,100,1000\n",
        encoding="utf-8",
    )
    session = MarketAdmissionSession(
        enabled=True,
        witness_bars={"BTC-USD": [_btc_witness()]},
        btc_spot_witness_enabled=True,
        btc_completed_through="2026-07-13",
        requested_start="2026-07-13",
        requested_end="2026-07-14",
        completed_through="2026-07-13",
        witness_provenance={
            "coinbase": {
                "source": "COINBASE_EXCHANGE_BTC_USD_1DAY",
                "source_url": "https://api.exchange.coinbase.com/products/BTC-USD/candles",
                "fetched_at": "2026-07-14T00:01:00+00:00",
                "requested_start": "2026-07-13",
                "requested_end": "2026-07-14",
                "requests": [{
                    "url": "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400",
                    "start": "2026-07-13",
                    "end": "2026-07-14",
                    "status": "OK",
                    "row_count": 1,
                    "content_sha256": "a" * 64,
                }],
            }
        },
    )
    session.admit("BTC-USD", _candidate())
    session.bind_canonical_files(history, ["BTC-USD"])
    valid = session.payload(generated_at="2026-07-14T00:02:00+00:00")

    checked = validate_market_admission_evidence(
        valid,
        history,
        as_of="2026-07-13",
    )
    assert checked["status"] == "OK"

    corruptions = []
    missing_provenance = copy.deepcopy(valid)
    missing_provenance["btc_spot_witness"]["provenance"] = {}
    corruptions.append(missing_provenance)
    inconsistent_row = copy.deepcopy(valid)
    inconsistent_row["rows"][0]["admitted"] = False
    corruptions.append(inconsistent_row)
    inconsistent_summary = copy.deepcopy(valid)
    inconsistent_summary["summary"] = {"MATCH": 2}
    corruptions.append(inconsistent_summary)
    inconsistent_status = copy.deepcopy(valid)
    inconsistent_status["status"] = "BLOCKED"
    corruptions.append(inconsistent_status)
    missing_canonical = copy.deepcopy(valid)
    missing_canonical["canonical_files"] = {
        "DOES_NOT_EXIST.csv": {"sha256": None, "latest_as_of": None}
    }
    corruptions.append(missing_canonical)

    for corrupted in corruptions:
        checked = validate_market_admission_evidence(
            corrupted,
            history,
            as_of="2026-07-13",
        )
        assert checked["status"] == "EVIDENCE_DRIFT"


def test_market_admission_append_only_history_marks_old_evidence_superseded(tmp_path) -> None:
    history = tmp_path / "history"
    history.mkdir()
    canonical = history / "QQQ.csv"
    canonical.write_text("date,close\n2026-07-13,100\n", encoding="utf-8")
    evidence = {
        "mode": "enforce_consensus",
        "status": "OK",
        "generated_at": "2026-07-14T00:05:00+00:00",
        "completed_through": "2026-07-13",
        "operation_id": "official-run",
        "canonical_files": {
            "QQQ.csv": {
                "sha256": hashlib.sha256(canonical.read_bytes()).hexdigest(),
                "latest_as_of": "2026-07-13",
            }
        },
    }
    canonical.write_text(
        "date,close\n2026-07-13,100\n2026-07-14,101\n",
        encoding="utf-8",
    )

    checked = validate_market_admission_evidence(
        evidence,
        history,
        as_of="2026-07-13",
    )

    assert checked["status"] == "SUPERSEDED_BY_NEWER_DATA"
    assert checked["superseded_files"] == ["QQQ.csv"]


def test_market_admission_changed_history_remains_evidence_drift(tmp_path) -> None:
    history = tmp_path / "history"
    history.mkdir()
    canonical = history / "QQQ.csv"
    canonical.write_text("date,close\n2026-07-13,100\n", encoding="utf-8")
    evidence = {
        "mode": "enforce_consensus",
        "status": "OK",
        "generated_at": "2026-07-14T00:05:00+00:00",
        "completed_through": "2026-07-13",
        "operation_id": "official-run",
        "canonical_files": {
            "QQQ.csv": {
                "sha256": hashlib.sha256(canonical.read_bytes()).hexdigest(),
                "latest_as_of": "2026-07-13",
            }
        },
    }
    canonical.write_text(
        "date,close\n2026-07-13,999\n2026-07-14,101\n",
        encoding="utf-8",
    )

    checked = validate_market_admission_evidence(evidence, history, as_of="2026-07-13")

    assert checked["status"] == "EVIDENCE_DRIFT"


def test_market_admission_rejects_unfinalized_market_session() -> None:
    candidate = _candidate()
    candidate.index = pd.to_datetime(["2026-07-14"])
    witness = _witness()
    witness["t"] = "2026-07-14T04:00:00Z"
    session = MarketAdmissionSession(
        enabled=True,
        witness_bars={"QQQ": [witness]},
        completed_through="2026-07-13",
    )

    admitted, evidence = session.admit("QQQ", candidate)

    assert admitted.empty
    assert evidence[0]["status"] == "UNFINALIZED_SESSION"


def test_market_admission_rejects_candidate_outside_witness_window() -> None:
    session = MarketAdmissionSession(
        enabled=True,
        witness_bars={"QQQ": [_witness()]},
        requested_start="2026-07-14",
        requested_end="2026-07-15",
        completed_through="2026-07-14",
    )

    admitted, evidence = session.admit("QQQ", _candidate())

    assert admitted.empty
    assert evidence[0]["status"] == "OUTSIDE_WITNESS_WINDOW"


def test_latest_completed_market_session_waits_for_regular_close() -> None:
    assert latest_completed_us_market_session(
        datetime(2026, 7, 14, 19, 30, tzinfo=timezone.utc)
    ).isoformat() == "2026-07-13"
    assert latest_completed_us_market_session(
        datetime(2026, 7, 14, 20, 20, tzinfo=timezone.utc)
    ).isoformat() == "2026-07-14"
    assert latest_completed_us_market_session(
        datetime(2026, 7, 19, 16, 0, tzinfo=timezone.utc)
    ).isoformat() == "2026-07-17"
