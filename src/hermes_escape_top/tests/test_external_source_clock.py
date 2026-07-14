from __future__ import annotations

from datetime import date, datetime, timezone

from hermes_escape_top.core.data.external_sources.clock import (
    shanghai_today,
    timestamp_to_shanghai_date,
)


def test_shanghai_today_crosses_utc_date_boundary() -> None:
    now = datetime(2026, 7, 12, 16, 30, tzinfo=timezone.utc)

    assert shanghai_today(now) == date(2026, 7, 13)


def test_timestamp_to_shanghai_date_normalizes_ledger_timestamp() -> None:
    assert timestamp_to_shanghai_date("2026-07-12T23:05:00Z") == date(2026, 7, 13)
    assert timestamp_to_shanghai_date("not-a-time") is None
