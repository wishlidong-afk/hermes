from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict

from ..core.data.base import SymbolSnapshot


@dataclass(frozen=True)
class MirrorLegDecision:
    sleeve: str
    risk_symbol: str
    base_symbol: str
    selected_symbol: str
    sleeve_cap: float
    target_weight: float
    cycle: str
    reason: str

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["sleeve_cap"] = round(float(payload["sleeve_cap"]), 6)
        payload["target_weight"] = round(float(payload["target_weight"]), 6)
        return payload


def build_mirror_plan(snapshots: Dict[str, SymbolSnapshot], config: Dict[str, object]) -> Dict[str, MirrorLegDecision]:
    return {
        "FNGU_QQQ": _paired_leg("FNGU_QQQ", "FNGU", "QQQ", "QQQ", snapshots, 0.20),
        "SOXL_SOXX": _paired_leg("SOXL_SOXX", "SOXL", "SOXX", "SOXX", snapshots, 0.30),
        "MSTR_QQQ": _mstr_leg(snapshots, 0.15),
    }


def _paired_leg(
    sleeve: str,
    risk_symbol: str,
    base_symbol: str,
    radar_symbol: str,
    snapshots: Dict[str, SymbolSnapshot],
    cap: float,
) -> MirrorLegDecision:
    radar = snapshots.get(radar_symbol)
    if radar is None:
        return MirrorLegDecision(sleeve, risk_symbol, base_symbol, "BOXX", cap, cap, "CASH", f"Missing radar {radar_symbol}.")
    close = radar.get("close")
    ema20 = radar.get("ema20")
    ma200 = radar.get("ma200")
    if close is None or ema20 is None or ma200 is None:
        return MirrorLegDecision(sleeve, risk_symbol, base_symbol, "BOXX", cap, cap, "CASH", f"Radar {radar_symbol} lacks close/EMA20/MA200.")
    if close > ema20 and close > ma200:
        return MirrorLegDecision(sleeve, risk_symbol, base_symbol, risk_symbol, cap, cap, "RISK_ON", f"{radar_symbol} above EMA20 and MA200.")
    if close > ma200:
        return MirrorLegDecision(sleeve, risk_symbol, base_symbol, base_symbol, cap, cap, "BASE_DEFENSE", f"{radar_symbol} above MA200 but not above EMA20.")
    return MirrorLegDecision(sleeve, risk_symbol, base_symbol, "BOXX", cap, cap, "CASH", f"{radar_symbol} below MA200.")


def _mstr_leg(snapshots: Dict[str, SymbolSnapshot], cap: float) -> MirrorLegDecision:
    mstr = snapshots.get("MSTR")
    btc = snapshots.get("BTC-USD")
    if mstr is None:
        return MirrorLegDecision("MSTR_QQQ", "MSTR", "QQQ", "BOXX", cap, cap, "CASH", "Missing MSTR snapshot.")
    close = mstr.get("close")
    ma200 = mstr.get("ma200")
    btc_close = btc.get("close") if btc else None
    btc_ma200 = btc.get("ma200") if btc else None
    if close is None or ma200 is None:
        return MirrorLegDecision("MSTR_QQQ", "MSTR", "QQQ", "BOXX", cap, cap, "CASH", "MSTR lacks close/MA200.")
    if close > ma200 and (btc_close is None or btc_ma200 is None or btc_close > btc_ma200):
        return MirrorLegDecision("MSTR_QQQ", "MSTR", "QQQ", "MSTR", cap, cap, "RISK_ON", "MSTR above MA200 and BTC radar is not bearish.")
    return MirrorLegDecision("MSTR_QQQ", "MSTR", "QQQ", "QQQ", cap, cap, "BASE_DEFENSE", "MSTR/BTC radar not risk-on; use QQQ base leg.")
