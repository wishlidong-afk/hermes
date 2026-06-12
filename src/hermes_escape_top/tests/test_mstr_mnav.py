from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.data.risk_signals import MstrMnavSource, risk_sources
from hermes_escape_top.core.scoring.module_b import module_b_factors
from hermes_escape_top.core.scoring.registry import FactorContext, FactorRegistry


DAY = date(2021, 4, 22)


def _snap(symbol: str, values: dict[str, float | None]) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        as_of=DAY,
        fields={name: Field(name=name, value=value, source="unit", as_of=DAY) for name, value in values.items()},
    )


def _cfg(tmp_path, *, data_flag: bool = True, use_flag: bool = False) -> dict:
    return {
        "paths": {
            "history_dir": str(tmp_path / "history"),
            "legacy_history_dir": str(tmp_path / "legacy_history"),
            "archive_dir": str(tmp_path / "archive"),
            "soft_history_dir": str(tmp_path / "soft_history"),
        },
        "features": {
            "data_mstr_mnav": data_flag,
            "use_b6_mnav_valuation": use_flag,
        },
    }


def _write_mnav_inputs(tmp_path) -> str:
    cfg = _cfg(tmp_path)
    history = tmp_path / "history"
    soft = tmp_path / "soft_history"
    history.mkdir()
    soft.mkdir()
    dates = pd.date_range("2021-01-01", periods=80, freq="B")
    pd.DataFrame(
        {
            "date": dates,
            "close": [10.0 + i for i in range(len(dates))],
            "market_cap_usd": [1_000_000.0 + i * 10_000.0 for i in range(len(dates))],
        }
    ).to_csv(history / "MSTR.csv", index=False)
    pd.DataFrame(
        {
            "date": dates,
            "close": [10_000.0 for _ in range(len(dates))],
        }
    ).to_csv(history / "BTC_USD.csv", index=False)
    (soft / "mstr_btc_holdings.csv").write_text(
        "# official reported total\n"
        "date,btc_count\n"
        "2020-08-10,50\n"
        "2021-01-01,100\n",
        encoding="utf-8",
    )
    return dates[-1].date().isoformat()


def _b6_factor(config: dict):
    snapshots = {
        "MSTR": _snap("MSTR", {"rsi14": 50.0, "close": 100.0, "ma200": 100.0, "drawdown_60d_high_pct": -0.05}),
        "SOFT": _snap("SOFT", {"MSTR_valuation_pctl": 96.0}),
    }
    factors = FactorRegistry(module_b_factors("MSTR", config)).evaluate(
        FactorContext(symbol="MSTR", snapshots=snapshots, config=config)
    )
    return next(factor for factor in factors if factor.factor_id == "B6_VALUATION_HEAT")


def test_mstr_mnav_source_parses_holdings_and_rolls_percentile(tmp_path):
    as_of = _write_mnav_inputs(tmp_path)
    record = MstrMnavSource().collect(as_of, _cfg(tmp_path, data_flag=True))

    assert record.data_available is True
    assert record.name == "mstr_mnav"
    assert record.fields["mstr_btc_holdings"] == pytest.approx(100.0)
    assert record.fields["btc_price_usd"] == pytest.approx(10_000.0)
    assert record.fields["mstr_market_cap_usd"] == pytest.approx(1_790_000.0)
    assert record.fields["mnav"] == pytest.approx(1.79)
    assert record.fields["mnav_premium_pctl_252"] == pytest.approx(100.0)
    assert record.fields["MSTR_valuation_pctl"] == pytest.approx(100.0)
    assert "holdings_asof=2021-01-01" in record.reason


def test_mstr_mnav_source_not_registered_when_data_flag_off(tmp_path):
    off = risk_sources(_cfg(tmp_path, data_flag=False))
    on = risk_sources(_cfg(tmp_path, data_flag=True))

    assert all(getattr(source, "name", None) != "mstr_mnav" for source in off)
    assert any(getattr(source, "name", None) == "mstr_mnav" for source in on)


def test_b6_mstr_mnav_requires_consumption_flag_even_if_field_exists(tmp_path):
    off = _b6_factor(_cfg(tmp_path, data_flag=True, use_flag=False))
    on = _b6_factor(_cfg(tmp_path, data_flag=True, use_flag=True))

    assert off.score == 0.0
    assert off.missing_fields == ["B6 valuation"]
    assert on.score == 5.0
    assert on.missing_fields == []
