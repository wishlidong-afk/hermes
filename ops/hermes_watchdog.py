#!/usr/bin/env python3
"""Dead-man switch for the Hermes daily live run."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

WATCHDOG_LOG = Path.home() / ".hermes/logs/watchdog.log"
ALERT_AFTER_TRADING_DAYS = 2
ET = ZoneInfo("America/New_York")


def live_base(home: Path | None = None) -> Path:
    root = home or Path.home()
    return root / ".hermes/skills/investment/escape-top"


def audit_log_candidates(home: Path | None = None) -> list[Path]:
    base = live_base(home)
    return [
        base / "current/hermes_escape_top/data/archive/audit_log.jsonl",
        base / "shared/hermes_escape_top/data/archive/audit_log.jsonl",
        base / "hermes_escape_top/data/archive/audit_log.jsonl",
    ]


def resolve_audit_log(home: Path | None = None) -> Path:
    candidates = audit_log_candidates(home)
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def _observed_fixed_holiday(year: int, month: int, day: int) -> date:
    holiday = date(year, month, day)
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    next_month = date(year + int(month == 12), 1 if month == 12 else month + 1, 1)
    last = next_month - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _easter_date(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    weekday_offset = (32 + 2 * e + 2 * i - h - k) % 7
    correction = (a + 11 * h + 22 * weekday_offset) // 451
    month = (h + weekday_offset - 7 * correction + 114) // 31
    day = ((h + weekday_offset - 7 * correction + 114) % 31) + 1
    return date(year, month, day)


@lru_cache(maxsize=32)
def _nyse_holidays(year: int) -> frozenset[date]:
    holidays = {
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _easter_date(year) - timedelta(days=2),
        _last_weekday(year, 5, 0),
        _observed_fixed_holiday(year, 7, 4),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed_fixed_holiday(year, 12, 25),
    }
    # NYSE does not move a Saturday New Year's Day to the preceding Friday.
    # Sunday New Year's Day is observed on Monday as usual.
    for observed in (_observed_fixed_holiday(year, 1, 1),):
        if observed.year == year:
            holidays.add(observed)
    if year >= 2022:
        holidays.add(_observed_fixed_holiday(year, 6, 19))
    return frozenset(holidays)


def is_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in _nyse_holidays(day.year)


def last_completed_session(now_et: datetime) -> date:
    """Return the latest NYSE session past the 16:30 ET settle buffer."""
    day = now_et.date()
    if now_et.time() < time(16, 30):
        day -= timedelta(days=1)
    while not is_trading_day(day):
        day -= timedelta(days=1)
    return day


def completed_trading_days_after(as_of: date, now_et: datetime) -> int:
    end = last_completed_session(now_et)
    count = 0
    day = as_of + timedelta(days=1)
    while day <= end:
        if is_trading_day(day):
            count += 1
        day += timedelta(days=1)
    return count


def _audit_as_of_from_line(line: str) -> date | None:
    try:
        entry = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(entry, dict):
        return None
    raw = entry.get("as_of")
    if raw is None and isinstance(entry.get("payload"), dict):
        raw = entry["payload"].get("as_of")
    try:
        return date.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None


def latest_audit_as_of(home: Path | None = None) -> date | None:
    audit_log = resolve_audit_log(home)
    if not audit_log.exists():
        return None
    latest = None
    with audit_log.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            parsed = _audit_as_of_from_line(line.strip())
            if parsed is not None:
                latest = parsed
    return latest


def notify(title: str, body: str) -> None:
    subprocess.run(
        [
            "/usr/bin/osascript",
            "-e",
            f'display notification "{body}" with title "{title}" sound name "Basso"',
        ],
        check=False,
    )


def log(message: str) -> None:
    WATCHDOG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with WATCHDOG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")


def self_test() -> int:
    cases = [
        (date(2026, 7, 2), datetime(2026, 7, 6, 21, 0, tzinfo=ET), 1),
        (date(2026, 11, 25), datetime(2026, 11, 27, 21, 0, tzinfo=ET), 1),
        (date(2026, 6, 5), datetime(2026, 6, 7, 21, 0, tzinfo=ET), 0),
        (date(2026, 6, 5), datetime(2026, 6, 10, 21, 0, tzinfo=ET), 3),
        (date(2031, 7, 3), datetime(2031, 7, 7, 21, 0, tzinfo=ET), 1),
        (date(2027, 12, 29), datetime(2028, 1, 3, 21, 0, tzinfo=ET), 3),
    ]
    passed = True
    for as_of, now_et, expected in cases:
        actual = completed_trading_days_after(as_of, now_et)
        status = "ok" if actual == expected else "FAIL"
        passed &= actual == expected
        print(f"[{status}] as_of={as_of} now_et={now_et:%F %H:%M} -> {actual} (want {expected})")
    return 0 if passed else 1


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    now_et = datetime.now(ET)
    audit_log = resolve_audit_log()
    as_of = latest_audit_as_of()
    if as_of is None:
        if audit_log.exists() and audit_log.stat().st_size > 0:
            notify("Hermes watchdog", "audit_log has no valid as_of records")
            log("ALERT audit_log invalid")
        else:
            notify("Hermes watchdog", "audit_log missing or empty - daily run state unknown")
            log("ALERT audit_log missing/empty")
        return 0

    lag = completed_trading_days_after(as_of, now_et)
    if lag > ALERT_AFTER_TRADING_DAYS:
        notify("Hermes daily run STALE", f"last scored {as_of} - {lag} trading days behind")
        log(f"ALERT as_of={as_of} lag={lag}")
    else:
        log(f"ok as_of={as_of} lag={lag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
