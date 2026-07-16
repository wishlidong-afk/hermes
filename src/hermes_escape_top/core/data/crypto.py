"""BTC funding-rate / basis / DVOL adapters (N1-T07, N1-T08, N1-T09).

CSV schema (btc_funding_basis.csv):
  date               — measurement date
  publish_date       — same-day (exchange data)
  btc_funding_8h_avg — average 8-hour funding rate
  btc_funding_pctl   — rolling 252-day percentile (0-100)
  btc_basis_annual   — annualised futures basis (proxy)
  btc_basis_pctl     — rolling 252-day percentile (0-100)

Source note: historical funding rows can be momentum-derived proxies; current
funding rows can be certified exchange observations. ``btc_basis_annual`` is
still funding multiplied by three sessions and 365 days, so it is not a traded
futures basis and always retains proxy provenance and penalty.

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
    """BTC funding rate + basis adapter backed by the certified local CSV."""

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
        funding_source, funding_is_proxy = _funding_provenance(picked)
        field_provenance = _field_provenance(
            funding_source=funding_source,
            funding_is_proxy=funding_is_proxy,
        )
        record_source = "BTC_FUNDING_PROXY" if funding_is_proxy else "BTC_MICRO_MIXED"

        return SoftDataRecord(
            self.name, day, fields["btc_funding_8h_avg"], record_source,
            data_available=available,
            is_proxy=True,
            quality_penalty=_FUNDING_QUALITY_PENALTY if available else _FUNDING_QUALITY_PENALTY + 1.0,
            latency_days=0,
            fields={k: v for k, v in fields.items() if v is not None},
            field_provenance=field_provenance,
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


def _funding_provenance(row: Dict[str, Any]) -> tuple[str, bool]:
    raw_marker = row.get("is_proxy")
    marker = "" if pd.isna(raw_marker) else str(raw_marker).strip().lower()
    raw_source = row.get("funding_source")
    source = "" if pd.isna(raw_source) else str(raw_source).strip()
    invalid_sources = {"", "proxy", "unknown", "none", "nan"}
    if marker in {"false", "0", "no"} and source.lower() not in invalid_sources:
        return source.upper(), False
    return "BTC_FUNDING_PROXY", True


def _field_provenance(*, funding_source: str, funding_is_proxy: bool) -> Dict[str, Dict[str, Any]]:
    funding_penalty = _FUNDING_QUALITY_PENALTY if funding_is_proxy else 0.0
    funding = {
        "source": funding_source,
        "is_proxy": funding_is_proxy,
        "quality_penalty": funding_penalty,
    }
    basis = {
        "source": "BTC_BASIS_FROM_FUNDING_PROXY",
        "is_proxy": True,
        "quality_penalty": _FUNDING_QUALITY_PENALTY,
    }
    return {
        "btc_funding_8h_avg": dict(funding),
        "btc_funding_pctl": dict(funding),
        "btc_basis_annual": dict(basis),
        "btc_basis_pctl": dict(basis),
    }
