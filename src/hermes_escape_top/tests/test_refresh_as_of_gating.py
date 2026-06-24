"""The 更新持仓 (refresh positions) button must score the same trading day as the
official scheduled run. ^VIX and other auxiliary symbols in _critical_symbols
routinely lag a day; gating as_of on them re-scores yesterday with today's
positions, so the fresh-IBKR preview still reads "行情陈旧" (the 2026-06-24
incident: ^VIX stuck at 06-22 dragged the button to 06-22 while the official run
was on 06-23)."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from hermes_escape_top.web import refresh as refresh_mod
from hermes_escape_top.web.refresh import refresh_positions_only


@contextmanager
def _fake_lock(*args, **kwargs):
    yield object()  # stand-in lease; the scoring call is mocked out


def test_refresh_positions_only_gates_as_of_on_scheduled_symbols_not_vix():
    captured = {}

    def fake_latest_history_date(config, symbols):
        captured["symbols"] = list(symbols)
        return "2026-06-23"  # the day QQQ/SPY/trade symbols reached

    with mock.patch.object(refresh_mod, "load_config", return_value={}), \
         mock.patch.object(refresh_mod, "resolve_path", return_value=Path("/tmp")), \
         mock.patch.object(refresh_mod, "pipeline_lock", _fake_lock), \
         mock.patch.object(refresh_mod, "trade_symbols", return_value=["MSTR", "FNGU", "SOXL"]), \
         mock.patch.object(refresh_mod, "latest_history_date", side_effect=fake_latest_history_date), \
         mock.patch.object(refresh_mod, "_score_pipeline_locked", return_value={"as_of": "2026-06-23"}) as score:
        out = refresh_positions_only("latest", blocking=False)

    # gated on exactly the scheduled run's symbols (run_daily_package._last_bar_dates) ...
    assert set(captured["symbols"]) == {"QQQ", "SPY", "MSTR", "FNGU", "SOXL"}
    # ... and NOT on the flaky auxiliary index that would drag as_of back a day
    assert "^VIX" not in captured["symbols"]
    # scored the fresh trading day and returned it
    score.assert_called_once_with("2026-06-23", _lease=mock.ANY)
    assert out["as_of"] == "2026-06-23"
