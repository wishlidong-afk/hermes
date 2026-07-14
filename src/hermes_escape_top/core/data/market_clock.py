from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def latest_completed_us_market_session(now: datetime | None = None) -> date:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    eastern = value.astimezone(ZoneInfo("America/New_York"))
    day = eastern.date()
    if day.weekday() < 5 and eastern.time() >= time(16, 15):
        return day
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day
