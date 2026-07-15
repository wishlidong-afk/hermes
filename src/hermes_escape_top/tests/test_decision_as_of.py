from __future__ import annotations

from pathlib import Path

from hermes_escape_top.core.data.decision_as_of import (
    decision_gating_symbols,
    last_bar_dates,
    resolve_decision_as_of,
)
from hermes_escape_top.scripts import run_daily_package as rdp
from hermes_escape_top.web import refresh


def _write_history(root: Path, symbol: str, *days: str) -> None:
    name = symbol.replace("^", "_").replace("-", "_").replace(".", "_")
    rows = ["date,open,high,low,close,adj_close,volume"]
    rows.extend(f"{day},100,101,99,100,100,1000" for day in days)
    (root / f"{name}.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _config(history: Path) -> dict:
    return {
        "paths": {"history_dir": str(history)},
        "symbols": {"MSTR": {}, "FNGU": {}, "SOXL": {}},
    }


def test_decision_as_of_ignores_lagging_auxiliary_indices(tmp_path) -> None:
    for symbol in ("QQQ", "SPY", "MSTR", "FNGU", "SOXL"):
        _write_history(tmp_path, symbol, "2026-07-13", "2026-07-14")
    _write_history(tmp_path, "^VIX", "2026-07-13")
    _write_history(tmp_path, "SOXX", "2026-07-13")
    config = _config(tmp_path)

    assert decision_gating_symbols(config) == ("FNGU", "MSTR", "QQQ", "SOXL", "SPY")
    assert resolve_decision_as_of("latest", config) == "2026-07-14"
    assert set(last_bar_dates(config)) == set(decision_gating_symbols(config))


def test_daily_and_web_use_the_same_decision_clock(tmp_path, monkeypatch) -> None:
    for symbol in ("QQQ", "SPY", "MSTR", "FNGU", "SOXL"):
        _write_history(tmp_path, symbol, "2026-07-13", "2026-07-14")
    _write_history(tmp_path, "^VIX", "2026-07-13")
    config = _config(tmp_path)
    monkeypatch.setattr(rdp, "load_config", lambda: config)

    assert rdp._latest_available_as_of() == "2026-07-14"
    assert refresh._critical_symbols(config) == set(decision_gating_symbols(config))
    assert refresh.latest_history_date(config, refresh._critical_symbols(config)) == "2026-07-14"


def test_explicit_as_of_is_never_rewritten(tmp_path) -> None:
    config = _config(tmp_path)

    assert resolve_decision_as_of("2020-03-12", config) == "2020-03-12"
