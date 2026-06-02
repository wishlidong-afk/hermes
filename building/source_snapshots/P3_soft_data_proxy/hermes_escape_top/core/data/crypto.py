"""BTC funding-rate / basis / DVOL adapters (N1-T07, N1-T08, N1-T09).

CSV schema (btc_funding_basis.csv):
  date               — measurement date
  publish_date       — same-day (exchange data)
  btc_funding_8h_avg — average 8-hour funding rate (proxy: momentum-derived)
  btc_funding_pctl   — rolling 252-day percentile (0-100)
  btc_basis_annual   — annualised futures basis (proxy)
  btc_basis_pctl     — rolling 252-day percentile (0-100)

Source note: fields are momentum-derived proxies from BTC-USD price history.
quality_penalty = 2 per BUILD_TICKETS N1-T07/T08 (no deep history fallback).
is_proxy = True. All values tagged in SoftDataRecord.

Usage:
  from hermes_escape_top.core.data.crypto import CryptoFundingSource
  rec = CryptoFundingSource().fetch(as_of="2026-06-01", config={})
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from ...config import resolve_path
from .adapters import SoftDataRecord
from .pit import asof_pick

_FUNDING_QUALITY_PENALTY = 2.0   # proxy, no real 8h exchange data
_BASIS_QUALITY_PENALTY = 2.0

SOFT_HISTORY = Path(__file__).resolve().parents[3] / "data" / "soft_history"


@dataclass(frozen=True)
class CryptoMicroRecord:
    name: str
    as_of: date
    value: Optional[float]
    source: str
    data_available: bool
    latency_days: int = 0
    reason: str = ""

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["as_of"] = self.as_of.isoformat()
        return payload


def annualized_basis(
    future_price: Optional[float],
    spot_price: Optional[float],
    days_to_expiry: int,
    as_of: str,
) -> CryptoMicroRecord:
    """Compute annualised basis from live futures/spot prices."""
    day = date.fromisoformat(str(as_of)[:10])
    if future_price is None or spot_price is None or spot_price <= 0 or days_to_expiry <= 0:
        return CryptoMicroRecord(
            "btc_basis_annualized", day, None, "crypto_contract", False,
            reason="missing futures/spot input",
        )
    basis = (float(future_price) / float(spot_price) - 1.0) * 365.0 / float(days_to_expiry)
    return CryptoMicroRecord("btc_basis_annualized", day, basis, "crypto_contract", True)


class CryptoFundingSource:
    """BTC funding rate + basis adapter backed by local proxy CSV (N1-T07/T08).

    The CSV contains momentum-derived proxies. quality_penalty=2 per spec.
    is_proxy=True. Offline-safe: no network calls.
    """

    name = "btc_funding_basis"
    feature_flag = "data_btc_funding"

    def collect(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        if not bool(config.get("features", {}).get(self.feature_flag, True)):
            return SoftDataRecord(
                self.name, day, None, "BTC_FUNDING_PROXY", False,
                reason=f"feature disabled: {self.feature_flag}",
            )
        return self.fetch(as_of, config)

    def fetch(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        path = self._history_path(config)

        if not path.exists():
            return SoftDataRecord(
                self.name, day, None, "BTC_FUNDING_PROXY", False,
                quality_penalty=_FUNDING_QUALITY_PENALTY,
                reason="btc_funding_basis.csv missing",
            )
        try:
            frame = pd.read_csv(path, parse_dates=["date", "publish_date"])
        except Exception as exc:
            return SoftDataRecord(
                self.name, day, None, "BTC_FUNDING_PROXY", False,
                quality_penalty=_FUNDING_QUALITY_PENALTY,
                reason=f"CSV read error: {exc}",
            )

        records = [(row["publish_date"].date(), row) for row in frame.to_dict("records")]
        picked = asof_pick(records, day)
        if picked is None:
            return SoftDataRecord(
                self.name, day, None, "BTC_FUNDING_PROXY", False,
                quality_penalty=_FUNDING_QUALITY_PENALTY,
                reason="no BTC funding record as of date",
            )

        fields = {
            "btc_funding_8h_avg": _finite(picked.get("btc_funding_8h_avg")),
            "btc_funding_pctl": _finite(picked.get("btc_funding_pctl")),
            "btc_basis_annual": _finite(picked.get("btc_basis_annual")),
            "btc_basis_pctl": _finite(picked.get("btc_basis_pctl")),
        }
        available = fields["btc_funding_8h_avg"] is not None

        return SoftDataRecord(
            self.name, day, fields["btc_funding_8h_avg"], "BTC_FUNDING_PROXY",
            data_available=available,
            is_proxy=True,
            quality_penalty=_FUNDING_QUALITY_PENALTY if available else _FUNDING_QUALITY_PENALTY + 1,
            latency_days=0,
            fields={k: v for k, v in fields.items() if v is not None},
        )

    @staticmethod
    def _history_path(config: Dict[str, Any]) -> Path:
        try:
            base = resolve_path(config, "soft_history_dir")
            return base / "btc_funding_basis.csv"
        except Exception:
            return SOFT_HISTORY / "btc_funding_basis.csv"


def _finite(val: Any) -> Optional[float]:
    try:
        f = float(val)
        return f if (f == f) else None  # NaN check
    except (TypeError, ValueError):
        return None
