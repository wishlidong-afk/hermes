from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date
from typing import Dict, Iterable, Optional


@dataclass(frozen=True)
class OptionsRiskRecord:
    name: str
    as_of: date
    value: Optional[float]
    source: str
    data_available: bool
    is_proxy: bool = False
    quality_penalty: float = 0.0
    reason: str = ""

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["as_of"] = self.as_of.isoformat()
        return payload


def black_scholes_gamma(spot: float, strike: float, rate: float, vol: float, time_to_expiry_years: float) -> float:
    if spot <= 0 or strike <= 0 or vol <= 0 or time_to_expiry_years <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * time_to_expiry_years) / (vol * math.sqrt(time_to_expiry_years))
    pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    return pdf / (spot * vol * math.sqrt(time_to_expiry_years))


def gex_proxy(option_rows: Iterable[Dict[str, float]], spot: float, as_of: str) -> OptionsRiskRecord:
    total = 0.0
    available = False
    for row in option_rows:
        gamma = black_scholes_gamma(
            spot=spot,
            strike=float(row.get("strike", 0.0)),
            rate=float(row.get("rate", 0.0)),
            vol=float(row.get("iv", 0.0)),
            time_to_expiry_years=float(row.get("tte", 0.0)),
        )
        oi = float(row.get("open_interest", 0.0))
        sign = 1.0 if str(row.get("type", "call")).lower() == "call" else -1.0
        total += sign * gamma * oi
        available = True
    return OptionsRiskRecord("gex_proxy", date.fromisoformat(str(as_of)[:10]), total if available else None, "options_contract", available, is_proxy=True, quality_penalty=3.0 if available else 0.0)


def skew_record(put_iv: Optional[float], call_iv: Optional[float], as_of: str) -> OptionsRiskRecord:
    day = date.fromisoformat(str(as_of)[:10])
    if put_iv is None or call_iv is None:
        return OptionsRiskRecord("skew_25d", day, None, "options_contract", False, reason="missing put/call IV")
    return OptionsRiskRecord("skew_25d", day, float(put_iv) - float(call_iv), "options_contract", True)
