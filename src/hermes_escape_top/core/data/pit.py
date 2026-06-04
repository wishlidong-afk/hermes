from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable, Optional, TypeVar


T = TypeVar("T")


def asof_pick(records: Iterable[tuple[date | datetime | str, T]], as_of: date | datetime | str, *, publish_lag_days: int = 0) -> Optional[T]:
    """Pick the latest record whose publish date is available at as_of.

    Low-frequency datasets must pass publish dates, not statistical period
    dates. `publish_lag_days` is an extra conservative delay when a source only
    supplies period dates.
    """
    cutoff = _to_date(as_of)
    lag = timedelta(days=int(publish_lag_days))
    best_date: Optional[date] = None
    best_value: Optional[T] = None
    for raw_date, value in records:
        publish_date = _to_date(raw_date) + lag
        if publish_date <= cutoff and (best_date is None or publish_date > best_date):
            best_date = publish_date
            best_value = value
    return best_value


def _to_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])
