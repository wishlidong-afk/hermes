from __future__ import annotations

from datetime import date

from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.data.risk_signals import OnchainMstrSource, risk_sources
from hermes_escape_top.core.scoring.module_d import module_d_factors
from hermes_escape_top.core.scoring.registry import FactorContext, FactorRegistry


DAY = date(2024, 3, 27)


def _snap(symbol: str, values: dict[str, float | None]) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        as_of=DAY,
        fields={name: Field(name=name, value=value, source="unit", as_of=DAY) for name, value in values.items()},
    )


def _cfg(tmp_path, *, flag: bool = True, candidate: str = "CM_EXCHANGE_INFLOW_PRESSURE") -> dict:
    return {
        "paths": {
            "history_dir": str(tmp_path / "history"),
            "legacy_history_dir": str(tmp_path / "legacy_history"),
            "archive_dir": str(tmp_path / "archive"),
            "soft_history_dir": str(tmp_path / "soft_history"),
        },
        "features": {"data_onchain_mstr": flag},
        "onchain_mstr": {"candidate": candidate},
    }


def _write_onchain(tmp_path) -> None:
    soft = tmp_path / "soft_history"
    soft.mkdir()
    (soft / "onchain_mstr_features.csv").write_text(
        "date,flow_in_ex_mcap_z90,flow_net_ex_mcap_z90\n"
        "2024-03-26,2.40,1.20\n"
        "2024-03-27,2.60,2.80\n",
        encoding="utf-8",
    )


def test_onchain_source_only_registers_when_data_flag_on(tmp_path):
    off = risk_sources(_cfg(tmp_path, flag=False))
    on = risk_sources(_cfg(tmp_path, flag=True))

    assert all(getattr(source, "name", None) != "onchain_mstr" for source in off)
    assert any(getattr(source, "name", None) == "onchain_mstr" for source in on)


def test_onchain_source_reads_pit_exchange_pressure_fields(tmp_path):
    _write_onchain(tmp_path)
    record = OnchainMstrSource().collect("2024-03-27", _cfg(tmp_path, flag=True))

    assert record.data_available is True
    assert record.fields["cm_exchange_inflow_pressure"] == 2.60
    assert record.fields["cm_exchange_netflow_pressure"] == 2.80


def test_onchain_candidate_stays_inside_d_m3_four_point_budget(tmp_path):
    cfg = _cfg(tmp_path, flag=True, candidate="CM_EXCHANGE_INFLOW_PRESSURE")
    snapshots = {
        "MSTR": _snap("MSTR", {"close": 100.0, "ma200": 80.0, "ma220": 78.0, "ema50": 90.0, "drawdown_60d_high_pct": -0.05}),
        "BTC-USD": _snap("BTC-USD", {"close": 100000.0, "ma200": 70000.0, "realized_vol20": 0.30, "return_10d": 0.02, "drawdown_60d_high_pct": -0.03}),
        "SOFT": _snap("SOFT", {"cm_exchange_inflow_pressure": 2.2}),
    }
    factors = FactorRegistry(module_d_factors("MSTR", cfg)).evaluate(
        FactorContext(symbol="MSTR", snapshots=snapshots, config=cfg)
    )
    d_m3 = next(factor for factor in factors if factor.factor_id == "D_M3_BTC_RISK_COMPOSITE")

    assert d_m3.max_score == 4.0
    assert d_m3.score == 4.0
