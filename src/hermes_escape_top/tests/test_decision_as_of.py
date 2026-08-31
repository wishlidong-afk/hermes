from __future__ import annotations

from pathlib import Path

import pytest

from hermes_escape_top.core.data.decision_as_of import (
    DecisionClockUnavailable,
    decision_gating_symbols,
    last_bar_dates,
    latest_common_history_date,
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
        "paths": {
            "history_dir": str(history),
            "legacy_history_dir": str(history / "legacy"),
        },
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


def test_latest_is_unavailable_when_one_required_history_is_missing(tmp_path) -> None:
    for symbol in ("QQQ", "SPY", "MSTR", "FNGU"):
        _write_history(tmp_path, symbol, "2026-07-14")
    config = _config(tmp_path)

    assert latest_common_history_date(config) is None
    with pytest.raises(DecisionClockUnavailable, match="SOXL") as exc_info:
        resolve_decision_as_of("latest", config)

    assert exc_info.value.missing_symbols == ("SOXL",)


def test_latest_is_unavailable_when_every_required_history_is_missing(tmp_path) -> None:
    config = _config(tmp_path)

    assert latest_common_history_date(config) is None
    with pytest.raises(DecisionClockUnavailable) as exc_info:
        resolve_decision_as_of("latest", config)

    assert exc_info.value.missing_symbols == decision_gating_symbols(config)


def test_latest_uses_lagging_required_symbol_only_when_all_are_present(tmp_path) -> None:
    for symbol in ("QQQ", "SPY", "MSTR", "FNGU"):
        _write_history(tmp_path, symbol, "2026-07-13", "2026-07-14")
    _write_history(tmp_path, "SOXL", "2026-07-13")
    config = _config(tmp_path)

    assert resolve_decision_as_of("latest", config) == "2026-07-13"


def test_daily_latest_selection_fails_closed_on_missing_required_history(tmp_path, monkeypatch) -> None:
    for symbol in ("QQQ", "SPY", "MSTR", "FNGU"):
        _write_history(tmp_path, symbol, "2026-07-14")
    config = _config(tmp_path)
    monkeypatch.setattr(rdp, "load_config", lambda: config)

    with pytest.raises(DecisionClockUnavailable, match="SOXL"):
        rdp._latest_available_as_of()


def test_web_latest_normalization_fails_closed_on_missing_required_history(tmp_path, monkeypatch) -> None:
    for symbol in ("QQQ", "SPY", "MSTR", "FNGU"):
        _write_history(tmp_path, symbol, "2026-07-14")
    config = _config(tmp_path)
    monkeypatch.setattr(refresh, "load_config", lambda: config)

    with pytest.raises(DecisionClockUnavailable, match="SOXL"):
        refresh._normalize_as_of("latest")
