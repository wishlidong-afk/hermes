"""Self-heal: a rate-limited symbol that lags its peers must be re-fetched
individually so it cannot silently pin as_of a day behind (2026-06-17 MSTR:
batch backfill left MSTR at 06-15 while QQQ/SPY/SOXL reached 06-16, holding the
whole run a day stale)."""
from __future__ import annotations

import types
from datetime import date

from hermes_escape_top.scripts import run_daily_package as rdp

D15, D16 = date(2026, 6, 15), date(2026, 6, 16)


def _feed_dates(monkeypatch, *snapshots):
    """Feed _last_bar_dates a sequence of snapshots (the last one repeats)."""
    box = list(snapshots)
    monkeypatch.setattr(rdp, "_last_bar_dates", lambda: box.pop(0) if len(box) > 1 else dict(box[0]))


def _capture_backfills(monkeypatch):
    calls = []
    monkeypatch.setattr(
        rdp.subprocess, "run",
        lambda cmd, **kw: calls.append(cmd) or types.SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    return calls


def test_heal_refetches_only_the_laggard(monkeypatch):
    # MSTR lags at 06-15 while peers have 06-16; after re-fetch it catches up.
    _feed_dates(
        monkeypatch,
        {"QQQ": D16, "SPY": D16, "MSTR": D15, "FNGU": D16, "SOXL": D16},
        {"QQQ": D16, "SPY": D16, "MSTR": D16, "FNGU": D16, "SOXL": D16},
    )
    calls = _capture_backfills(monkeypatch)
    rdp._heal_lagging_symbols("2026-06-17")
    # exactly MSTR was re-fetched, individually; no peer was touched
    assert len([c for c in calls if "--symbols" in c and "MSTR" in c]) == 1
    assert not any(s in c for c in calls for s in ("QQQ", "SPY", "FNGU", "SOXL"))


def test_heal_is_noop_when_all_aligned(monkeypatch):
    # weekend/holiday or genuine vendor gap: all share a date -> no laggards.
    _feed_dates(monkeypatch, {"QQQ": D16, "SPY": D16, "MSTR": D16, "FNGU": D16, "SOXL": D16})
    calls = _capture_backfills(monkeypatch)
    rdp._heal_lagging_symbols("2026-06-17")
    assert calls == []  # never re-fetches when nothing lags (no fabrication)


def test_heal_is_bounded_when_vendor_truly_lacks_bar(monkeypatch):
    # MSTR can never advance (vendor genuinely lacks it): retries are bounded,
    # then it gives up — as_of correctly holds back rather than looping forever.
    monkeypatch.setattr(
        rdp, "_last_bar_dates",
        lambda: {"QQQ": D16, "SPY": D16, "MSTR": D15, "FNGU": D16, "SOXL": D16},
    )
    calls = _capture_backfills(monkeypatch)
    rdp._heal_lagging_symbols("2026-06-17", max_passes=2, delay_s=0)
    assert len([c for c in calls if "MSTR" in c]) == 2  # one per pass, no more


def test_heal_never_raises(monkeypatch):
    # any internal failure must not break the daily run.
    def boom():
        raise RuntimeError("store down")
    monkeypatch.setattr(rdp, "_last_bar_dates", boom)
    rdp._heal_lagging_symbols("2026-06-17")  # must not raise
