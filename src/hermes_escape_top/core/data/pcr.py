"""CBOE Equity Put/Call Ratio source (N1-T03).

CSV schema: date, publish_date, equity_pcr, equity_pcr_pctl
  date          — survey/measurement date (YYYY-MM-DD)
  publish_date  — date the value was publicly available (for PIT alignment)
  equity_pcr    — CBOE equity-only put/call ratio (e.g. 0.62)
  equity_pcr_pctl — rolling 252-day percentile of equity_pcr (0–100)

The CBOE provides free historical equity PCR data.  Run
``scripts/backfill_pcr.py`` to populate the local CSV.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from ...config import resolve_path
from .adapters import SoftDataRecord
from .pit import asof_pick

_PCR_QUALITY_PENALTY = 1.0  # per BUILD_TICKETS N1-T03


class PutCallSource:
    name = "cboe_pcr"
    feature_flag = "data_cboe_pcr"

    def collect(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        if not bool(config.get("features", {}).get(self.feature_flag, False)):
            return SoftDataRecord(
                self.name, day, None, "CBOE_PCR", False,
                reason=f"feature disabled: {self.feature_flag}",
            )
        return self.fetch(as_of, config)

    def fetch(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        path = self.history_path(config)
        if not path.exists():
            proxy = _fresh_vix_proxy(day, config, "PCR history CSV missing")
            if proxy is not None:
                return proxy
            return SoftDataRecord(self.name, day, None, "CBOE_PCR", False, quality_penalty=2.0, reason="PCR history CSV missing")
        try:
            frame = pd.read_csv(path, parse_dates=["date", "publish_date"])
        except Exception as exc:
            proxy = _fresh_vix_proxy(day, config, f"PCR CSV read error: {exc}")
            if proxy is not None:
                return proxy
            return SoftDataRecord(self.name, day, None, "CBOE_PCR", False, quality_penalty=2.0, reason=f"PCR CSV read error: {exc}")
        records = [(row["publish_date"].date(), row) for row in frame.to_dict("records")]
        picked = asof_pick(records, day)
        if picked is None:
            proxy = _fresh_vix_proxy(day, config, "no PCR record available as of date")
            if proxy is not None:
                return proxy
            return SoftDataRecord(self.name, day, None, "CBOE_PCR", False, quality_penalty=2.0, reason="no PCR record available as of date")
        equity_pcr = _finite(picked.get("equity_pcr"))
        equity_pcr_pctl = _finite(picked.get("equity_pcr_pctl"))
        available = equity_pcr is not None
        # Read per-row is_proxy flag; VIX-derived proxy rows get higher penalty
        row_is_proxy = bool(picked.get("is_proxy", True))
        stale_days = max(0, (day - picked["publish_date"].date()).days)
        if row_is_proxy and stale_days > 2:
            proxy = _fresh_vix_proxy(day, config, f"cached PCR proxy stale by {stale_days} days")
            if proxy is not None:
                return proxy
        source_label = "CBOE_PCR" if not row_is_proxy else "PCR_VIX_PROXY"
        # Real PCR: penalty per spec (1.0); VIX-proxy: slightly higher (1.5)
        # Note: VVIX from CboeIndicesSource (penalty=0.0) covers same signal space
        penalty = (_PCR_QUALITY_PENALTY if not row_is_proxy else 1.5) if available else 2.0
        return SoftDataRecord(
            self.name,
            day,
            equity_pcr,
            source_label,
            available,
            is_proxy=row_is_proxy,
            latency_days=stale_days,
            quality_penalty=penalty,
            reason="" if available else "equity_pcr unavailable",
            fields={
                "equity_pcr": equity_pcr,
                "equity_pcr_pctl": equity_pcr_pctl,
            },
        )

    def history_path(self, config: Dict[str, Any]) -> Path:
        if config.get("paths", {}).get("soft_history_dir"):
            base = resolve_path(config, "soft_history_dir")
        else:
            base = Path("data/soft_history")
        return base / "cboe_equity_pcr.csv"


def _fresh_vix_proxy(day: date, config: Dict[str, Any], reason: str) -> Optional[SoftDataRecord]:
    try:
        from .store import LocalStore

        history = LocalStore(config).load_history("^VIX")
    except Exception:
        return None
    if history is None or history.empty or "Close" not in history:
        return None
    frame = history.loc[history.index <= pd.Timestamp(day.isoformat())].tail(252)
    close = pd.to_numeric(frame["Close"], errors="coerce").dropna()
    if len(close) < 60:
        return None
    picked_date = close.index[-1].date()
    vix_pctl = float((close <= float(close.iloc[-1])).mean() * 100.0)
    # VIX percentile is a conservative same-day proxy for equity PCR percentile:
    # low VIX generally maps to low put/call protection demand, which is exactly
    # the euphoria condition the score uses. It is explicitly tagged as proxy.
    equity_pcr = max(0.50, min(1.10, 0.55 + 0.40 * (vix_pctl / 100.0)))
    return SoftDataRecord(
        "cboe_pcr",
        day,
        round(equity_pcr, 4),
        "PCR_VIX_LIVE_PROXY",
        True,
        is_proxy=True,
        latency_days=max(0, (day - picked_date).days),
        quality_penalty=1.5,
        reason=f"{reason}; derived fresh proxy from VIX percentile",
        fields={
            "equity_pcr": round(equity_pcr, 4),
            "equity_pcr_pctl": round(vix_pctl, 2),
        },
    )


def _finite(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
        return f if f == f else None
    except (ValueError, TypeError):
        return None
