"""Regression guard for the 2026-06-13 FRED publish_date outage.

A change that set ``publish_date`` from the FRED API's ``realtime_start`` looked
PIT-richer but was wrong: on the standard observations endpoint ``realtime_start``
is the *query* date, returned identically for every observation (the current
vintage). So every row got one publish_date in the (then-)future, ``asof_pick``
saw every value as published after the as_of, and real_rate/dollar silently went
missing — live AND across the whole backtest (PIT destroyed, A10/A11 = 0
everywhere). The fix: publish_date = observation date + 1 (next-day release),
per row. These tests lock that invariant in.
"""
from __future__ import annotations

import json

from hermes_escape_top.core.data import risk_signals


class _FakeResp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def test_fred_publish_date_is_per_row_not_constant_realtime_start(monkeypatch) -> None:
    # The real FRED observations endpoint returns the SAME realtime_start (the
    # query date) for every observation. Trusting it collapses publish_date to a
    # single future date — the exact 2026-06-13 regression.
    obs = {"observations": [
        {"date": "2020-01-02", "realtime_start": "2026-06-13", "value": "1.00"},
        {"date": "2020-01-03", "realtime_start": "2026-06-13", "value": "1.10"},
        {"date": "2020-01-06", "realtime_start": "2026-06-13", "value": "1.20"},
    ]}
    monkeypatch.setattr(risk_signals, "fred_api_key", lambda config=None: "TESTKEY")
    monkeypatch.setattr(
        risk_signals, "urlopen",
        lambda url, timeout=30: _FakeResp(json.dumps(obs).encode("utf-8")),
    )

    frame = risk_signals.fetch_fred_series_frame("DFII10")

    # publish_date must be per-row, NOT the constant realtime_start stamp.
    assert frame["publish_date"].nunique() == len(frame), (
        "FRED publish_date collapsed to a constant (realtime_start) — "
        "asof_pick PIT regression (2026-06-13)"
    )
    # Each row publishes the next day, and no row may claim a publish date far
    # after its own observation (catches any 'stamp with today' variant).
    lags = (frame["publish_date"] - frame["date"]).dt.days
    assert (lags == 1).all()
    assert int(lags.max()) <= 5


def test_fred_no_key_fallback_also_per_row(monkeypatch) -> None:
    # The no-key fredgraph fallback must keep the same per-row date+1 contract.
    import pandas as pd

    series = pd.Series(
        [1.0, 1.1, 1.2],
        index=pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"]),
    )
    monkeypatch.setattr(risk_signals, "fred_api_key", lambda config=None: None)
    monkeypatch.setattr(risk_signals, "fetch_fred_graph_csv",
                        lambda series_id, start="1990-01-01", end=None: series)

    frame = risk_signals.fetch_fred_series_frame("DFII10")

    assert frame["publish_date"].nunique() == len(frame)
    assert ((frame["publish_date"] - frame["date"]).dt.days == 1).all()
