from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict

import pandas as pd

from ..features.volatility import volatility_snapshot
from .invariants import assert_not_more_aggressive


@dataclass(frozen=True)
class SizingDecision:
    symbol: str
    sleeve_cap: float
    sell_fraction: float
    reference_target_weight: float
    vol_scaler: float
    gross_scaler: float
    target_weight: float
    clamp_applied: bool
    explain: list[str]

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        for key in ["sleeve_cap", "sell_fraction", "reference_target_weight", "vol_scaler", "gross_scaler", "target_weight"]:
            payload[key] = round(float(payload[key]), 6)
        return payload


def size_position(
    symbol: str,
    history: pd.DataFrame,
    sleeve_cap: float,
    sell_fraction: float,
    config: Dict[str, object],
    gross_scaler: float = 1.0,
) -> SizingDecision:
    reference = max(0.0, float(sleeve_cap) * (1.0 - float(sell_fraction)))
    vol_cfg = config.get("vol_target", {}) if isinstance(config.get("vol_target", {}), dict) else {}
    scaler = 1.0
    explain = []
    if history is not None and not history.empty:
        close = history["Close"] if "Close" in history.columns else history.iloc[:, 0]
        snap = volatility_snapshot(
            close,
            forecast_method=str(vol_cfg.get("forecast", "ewma")),
            baseline_window=int(vol_cfg.get("baseline_window", 252)),
            baseline_stat=str(vol_cfg.get("baseline_stat", "median_20d_realized")),
            floor=float(vol_cfg.get("floor", 0.25)),
        )
        scaler = snap.relative_scaler
        explain.append(
            f"vol_scaler={scaler:.3f} forecast={_fmt_pct(snap.forecast_vol)} baseline={_fmt_pct(snap.baseline_vol)}"
        )
    else:
        explain.append("missing history: neutral vol scaler")

    raw = reference * min(1.0, max(0.0, scaler)) * min(1.0, max(0.0, float(gross_scaler)))
    target = min(reference, float(sleeve_cap), raw)
    assert_not_more_aggressive(reference, target, sleeve_cap_after_sell=reference)
    clamp_applied = target < raw - 1e-12 or target < reference - 1e-12
    if gross_scaler < 1.0:
        explain.append(f"portfolio gross scaler applied: {gross_scaler:.3f}")
    if clamp_applied:
        explain.append("target clamped by volatility/gross risk controls")
    return SizingDecision(
        symbol=symbol,
        sleeve_cap=float(sleeve_cap),
        sell_fraction=float(sell_fraction),
        reference_target_weight=reference,
        vol_scaler=float(scaler),
        gross_scaler=float(gross_scaler),
        target_weight=float(target),
        clamp_applied=clamp_applied,
        explain=explain,
    )


def size_portfolio(
    histories: Dict[str, pd.DataFrame],
    verdicts: Dict[str, object],
    config: Dict[str, object],
    gross_scaler: float = 1.0,
) -> Dict[str, SizingDecision]:
    out = {}
    for symbol, result in sorted(verdicts.items()):
        sleeve_cap = float(config.get("symbols", {}).get(symbol, {}).get("sleeve_cap", 0.0))
        sell_fraction = float(result.sell_fraction)
        out[symbol] = size_position(symbol, histories.get(symbol, pd.DataFrame()), sleeve_cap, sell_fraction, config, gross_scaler)
    return out


def _fmt_pct(value: float | None) -> str:
    return "NA" if value is None else f"{value:.2%}"
