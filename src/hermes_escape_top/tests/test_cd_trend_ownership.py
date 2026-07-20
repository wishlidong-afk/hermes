from __future__ import annotations

from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.scoring.module_c import module_c_factors
from hermes_escape_top.core.scoring.module_d import module_d_factors
from hermes_escape_top.core.scoring.registry import FactorContext, FactorRegistry


def _snapshot(symbol: str, **values: float) -> SymbolSnapshot:
    as_of = "2026-07-17"
    return SymbolSnapshot(
        symbol=symbol,
        as_of=as_of,
        fields={name: Field(name, value, "unit", as_of) for name, value in values.items()},
    )


def _snapshots() -> dict[str, SymbolSnapshot]:
    return {
        "MSTR": _snapshot(
            "MSTR",
            close=80.0,
            ema50=90.0,
            ma50=95.0,
            ma150=98.0,
            ma200=100.0,
            ma220=110.0,
            drawdown_60d_high_pct=-0.30,
        ),
        "BTC-USD": _snapshot("BTC-USD", close=120.0, ma200=100.0),
    }


def _scores(factors, config: dict) -> dict[str, object]:
    rows = FactorRegistry(factors).evaluate(
        FactorContext(symbol="MSTR", snapshots=_snapshots(), config=config)
    )
    return {row.factor_id: row for row in rows}


def test_flag_off_preserves_d1_d2_scores() -> None:
    config = {"features": {"use_cd_trend_dedup": False}}

    rows = _scores(module_d_factors("MSTR", config), config)

    assert rows["D1_ASSET_MA200_BREAK"].score == 5.0
    assert rows["D2_ASSET_MA220_BREAK"].score == 3.0


def test_flag_on_keeps_d1_d2_as_zero_point_audit_rows() -> None:
    config = {"features": {"use_cd_trend_dedup": True}}

    rows = _scores(module_d_factors("MSTR", config), config)

    for factor_id in ("D1_ASSET_MA200_BREAK", "D2_ASSET_MA220_BREAK"):
        assert rows[factor_id].score == 0.0
        assert rows[factor_id].missing_fields == []
        assert "Module C owns" in rows[factor_id].explain


def test_dedup_does_not_change_c_or_other_d_factors() -> None:
    off = {"features": {"use_cd_trend_dedup": False}}
    on = {"features": {"use_cd_trend_dedup": True}}

    c_off = _scores(module_c_factors(), off)
    c_on = _scores(module_c_factors(), on)
    d_off = _scores(module_d_factors("MSTR", off), off)
    d_on = _scores(module_d_factors("MSTR", on), on)

    assert c_on["C10_MACRO_TREND_STRUCTURE"].score == c_off["C10_MACRO_TREND_STRUCTURE"].score
    assert c_on["C11_MA220_REBUILD_GAP"].score == c_off["C11_MA220_REBUILD_GAP"].score
    assert d_on["D3_TRAILING_PEAK_DAMAGE"].score == d_off["D3_TRAILING_PEAK_DAMAGE"].score
    assert d_on["D4_RADAR_CONFIRMATION"].score == d_off["D4_RADAR_CONFIRMATION"].score
