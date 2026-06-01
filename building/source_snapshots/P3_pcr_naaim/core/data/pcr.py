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
            return SoftDataRecord(
                self.name, day, None, "CBOE_PCR", False,
                quality_penalty=2.0, reason="PCR history CSV missing",
            )
        try:
            frame = pd.read_csv(path, parse_dates=["date", "publish_date"])
        except Exception as exc:
            return SoftDataRecord(
                self.name, day, None, "CBOE_PCR", False,
                quality_penalty=2.0, reason=f"PCR CSV read error: {exc}",
            )
        records = [(row["publish_date"].date(), row) for row in frame.to_dict("records")]
        picked = asof_pick(records, day)
        if picked is None:
            return SoftDataRecord(
                self.name, day, None, "CBOE_PCR", False,
                quality_penalty=2.0, reason="no PCR record available as of date",
            )
        equity_pcr = _finite(picked.get("equity_pcr"))
        equity_pcr_pctl = _finite(picked.get("equity_pcr_pctl"))
        available = equity_pcr is not None
        return SoftDataRecord(
            self.name,
            day,
            equity_pcr,
            "CBOE_PCR",
            available,
            is_proxy=False,
            latency_days=max(0, (day - picked["publish_date"].date()).days),
            quality_penalty=_PCR_QUALITY_PENALTY if available else 2.0,
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


def _finite(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
        return f if f == f else None
    except (ValueError, TypeError):
        return None
