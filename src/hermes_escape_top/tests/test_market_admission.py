from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from hermes_escape_top.core.data.market_admission import MarketAdmissionSession
from hermes_escape_top.core.data.market_admission import (
    prepare_market_admission_session,
    read_market_admission_evidence,
    latest_completed_us_market_session,
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
