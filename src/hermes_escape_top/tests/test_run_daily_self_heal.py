"""Self-heal: a rate-limited symbol that lags its peers must be re-fetched
individually so it cannot silently pin as_of a day behind (2026-06-17 MSTR:
batch backfill left MSTR at 06-15 while QQQ/SPY/SOXL reached 06-16, holding the
whole run a day stale)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from hermes_escape_top.core.data.market_admission import MarketAdmissionSession
from hermes_escape_top.scripts import run_daily_package as rdp
from hermes_escape_top.core.safe_io import pipeline_lock

D15, D16 = date(2026, 6, 15), date(2026, 6, 16)


def test_refresh_history_reuses_daily_lease_without_child_lock(tmp_path, monkeypatch):
    archive = tmp_path / "archive"
    history = tmp_path / "history"
    report = tmp_path / "N0.md"
    cfg = {"paths": {"archive_dir": str(archive), "history_dir": str(history)}}
    calls = []
    monkeypatch.setattr(rdp, "load_config", lambda: cfg)
    monkeypatch.setattr(rdp, "all_backfill_symbols", lambda _cfg: ["QQQ"])
    monkeypatch.setattr(
        rdp,
        "backfill",
        lambda symbols, **kwargs: calls.append((symbols, kwargs)) or {},
    )
    monkeypatch.setattr(rdp, "write_coverage_report", lambda _results, _path: report)
    session = MarketAdmissionSession(enabled=True, witness_bars={})

    lock_path = archive / ".pipeline.lock"
    with pipeline_lock(path=lock_path) as lease:
        rdp.refresh_history(
            "2026-06-18",
            _lease=lease,
            admission_session=session,
        )

    assert calls[0][0] == ["QQQ"]
    assert calls[0][1]["store_dir"] == history
    assert calls[0][1]["admission_session"] is session
    assert calls[0][1]["admission_archive"] == archive


def _feed_dates(monkeypatch, *snapshots):
    """Feed _last_bar_dates a sequence of snapshots (the last one repeats)."""
    box = list(snapshots)
    monkeypatch.setattr(rdp, "_last_bar_dates", lambda: box.pop(0) if len(box) > 1 else dict(box[0]))


def _capture_backfills(monkeypatch):
    calls = []
    monkeypatch.setattr(rdp, "load_config", lambda: {"paths": {"history_dir": "/tmp/history"}})
    monkeypatch.setattr(rdp, "resolve_path", lambda _cfg, _key: Path("/tmp/history"))
    monkeypatch.setattr(rdp, "assert_pipeline_lease", lambda *_args, **_kwargs: None)

    def fake_backfill(symbols, **_kwargs):
        calls.append(list(symbols))
        return {symbol: type("Result", (), {"updated": True})() for symbol in symbols}

    monkeypatch.setattr(rdp, "backfill", fake_backfill)
    return calls


def test_heal_refetches_only_the_laggard(monkeypatch):
    # MSTR lags at 06-15 while peers have 06-16; after re-fetch it catches up.
    _feed_dates(
        monkeypatch,
        {"QQQ": D16, "SPY": D16, "MSTR": D15, "FNGU": D16, "SOXL": D16},
        {"QQQ": D16, "SPY": D16, "MSTR": D16, "FNGU": D16, "SOXL": D16},
    )
    calls = _capture_backfills(monkeypatch)
    rdp._heal_lagging_symbols("2026-06-17", _lease=object())
    # exactly MSTR was re-fetched, individually; no peer was touched
    assert calls == [["MSTR"]]


def test_heal_reuses_batch_market_admission_session(monkeypatch, tmp_path):
    _feed_dates(
        monkeypatch,
        {"QQQ": D16, "MSTR": D15},
        {"QQQ": D16, "MSTR": D16},
    )
    session = MarketAdmissionSession(enabled=True, witness_bars={})
    calls = []
    archive = tmp_path / "archive"
    history = tmp_path / "history"
    monkeypatch.setattr(
        rdp,
        "load_config",
        lambda: {"paths": {"archive_dir": str(archive), "history_dir": str(history)}},
    )
    monkeypatch.setattr(rdp, "assert_pipeline_lease", lambda *_args, **_kwargs: None)

    def fake_backfill(symbols, **kwargs):
        calls.append((list(symbols), kwargs))
        return {symbol: type("Result", (), {"updated": True})() for symbol in symbols}

    monkeypatch.setattr(rdp, "backfill", fake_backfill)

    rdp._heal_lagging_symbols(
        "2026-06-17",
        _lease=object(),
        admission_session=session,
    )

    assert calls[0][0] == ["MSTR"]
    assert calls[0][1]["admission_session"] is session
    assert calls[0][1]["admission_archive"] == archive


def test_heal_is_noop_when_all_aligned(monkeypatch):
    # weekend/holiday or genuine vendor gap: all share a date -> no laggards.
    _feed_dates(monkeypatch, {"QQQ": D16, "SPY": D16, "MSTR": D16, "FNGU": D16, "SOXL": D16})
    calls = _capture_backfills(monkeypatch)
    rdp._heal_lagging_symbols("2026-06-17", _lease=object())
    assert calls == []  # never re-fetches when nothing lags (no fabrication)


def test_heal_is_bounded_when_vendor_truly_lacks_bar(monkeypatch):
    # MSTR can never advance (vendor genuinely lacks it): retries are bounded,
    # then it gives up — as_of correctly holds back rather than looping forever.
    monkeypatch.setattr(
        rdp, "_last_bar_dates",
        lambda: {"QQQ": D16, "SPY": D16, "MSTR": D15, "FNGU": D16, "SOXL": D16},
    )
    calls = _capture_backfills(monkeypatch)
    rdp._heal_lagging_symbols("2026-06-17", _lease=object(), max_passes=2, delay_s=0)
    assert calls == [["MSTR"], ["MSTR"]]  # one per pass, no more


def test_heal_never_raises(monkeypatch):
    # any internal failure must not break the daily run.
    def boom():
        raise RuntimeError("store down")
    monkeypatch.setattr(rdp, "_last_bar_dates", boom)
    monkeypatch.setattr(rdp, "assert_pipeline_lease", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(rdp, "load_config", lambda: {})
    monkeypatch.setattr(rdp, "resolve_path", lambda _cfg, _key: Path("/tmp/history"))
    rdp._heal_lagging_symbols("2026-06-17", _lease=object())  # must not raise
