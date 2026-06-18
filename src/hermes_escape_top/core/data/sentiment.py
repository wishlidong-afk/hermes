from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from ...config import resolve_path
from ..safe_io import atomic_write_csv
from .adapters import SoftDataRecord
from .pit import asof_pick


class AaiiSource:
    name = "aaii"
    feature_flag = "data_aaii"

    def collect(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        if not bool(config.get("features", {}).get(self.feature_flag, False)):
            return SoftDataRecord(self.name, day, None, "AAII", False, reason=f"feature disabled: {self.feature_flag}")
        csv_path = self.history_path(config)
        if not csv_path.exists() and not config.get("runtime", {}).get("offline_replay_mode", False):
            try:
                self.backfill(config=config)
            except Exception as exc:
                return SoftDataRecord(self.name, day, None, "AAII", False, quality_penalty=5.0, reason=f"AAII parse/backfill failed: {exc}")
        return self.fetch(as_of, config)

    def backfill(self, config: Dict[str, Any]) -> Path:
        xls_path = self.source_path(config)
        if not xls_path.exists():
            raise FileNotFoundError(str(xls_path))
        frame = parse_aaii_sentiment_xls(xls_path)
        path = self.history_path(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_csv(frame, path, index=False)
        return path

    def fetch(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        path = self.history_path(config)
        if not path.exists():
            return SoftDataRecord(self.name, day, None, "AAII", False, quality_penalty=5.0, reason="AAII history missing")
        frame = pd.read_csv(path, parse_dates=["date", "publish_date"])
        records = [(row["publish_date"].date(), row) for row in frame.to_dict("records")]
        picked = asof_pick(records, day)
        if picked is None:
            return SoftDataRecord(self.name, day, None, "AAII", False, quality_penalty=5.0, reason="no AAII record available as of date")
        fields = {
            "aaii_bull": _finite(picked.get("aaii_bull")),
            "aaii_bear": _finite(picked.get("aaii_bear")),
            "aaii_bull_bear_spread": _finite(picked.get("aaii_bull_bear_spread")),
            "aaii_bull_pctl": _finite(picked.get("aaii_bull_pctl")),
            "aaii_spread_pctl": _finite(picked.get("aaii_spread_pctl")),
        }
        available = fields["aaii_bull_bear_spread"] is not None
        return SoftDataRecord(
            self.name,
            day,
            fields["aaii_bull_bear_spread"],
            "AAII",
            available,
            is_proxy=False,
            latency_days=max(0, (day - picked["publish_date"].date()).days),
            quality_penalty=1.5 if available else 5.0,
            reason="" if available else "AAII fields unavailable",
            fields=fields,
        )

    def source_path(self, config: Dict[str, Any]) -> Path:
        raw = config.get("paths", {}).get("aaii_sentiment_xls") or "/Users/liweishi/Downloads/sentiment.xls"
        path = Path(str(raw)).expanduser()
        return path if path.is_absolute() else resolve_path(config, "aaii_sentiment_xls")

    def history_path(self, config: Dict[str, Any]) -> Path:
        if "paths" in config and config.get("paths", {}).get("soft_history_dir"):
            base = resolve_path(config, "soft_history_dir")
        else:
            base = Path("data/soft_history")
        return base / "aaii_sentiment.csv"


class NaaimSource:
    name = "naaim"
    feature_flag = "data_naaim"

    def collect(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        if not bool(config.get("features", {}).get(self.feature_flag, False)):
            return SoftDataRecord(self.name, day, None, "NAAIM", False, reason=f"feature disabled: {self.feature_flag}")
        return self.fetch(as_of, config)

    def fetch(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        path = self.history_path(config)
        if not path.exists():
            return SoftDataRecord(self.name, day, None, "NAAIM", False, quality_penalty=5.0, reason="NAAIM history missing")
        frame = pd.read_csv(path, parse_dates=["date", "publish_date"])
        records = [(row["publish_date"].date(), row) for row in frame.to_dict("records")]
        picked = asof_pick(records, day)
        if picked is None:
            return SoftDataRecord(self.name, day, None, "NAAIM", False, quality_penalty=5.0, reason="no NAAIM record available as of date")
        fields = {
            "naaim_exposure": _finite(picked.get("naaim_exposure")),
            "naaim_pctl": _finite(picked.get("naaim_pctl")),
        }
        available = fields["naaim_exposure"] is not None
        # Use per-row is_proxy flag: real survey data (False) gets penalty=0,
        # momentum proxy rows (True) get penalty=1.5
        row_is_proxy = bool(picked.get("is_proxy", False))
        penalty = 1.5 if row_is_proxy else 0.0
        source = "NAAIM_PROXY" if row_is_proxy else "NAAIM"
        return SoftDataRecord(
            self.name,
            day,
            fields["naaim_exposure"],
            source,
            available,
            is_proxy=row_is_proxy,
            latency_days=max(0, (day - picked["publish_date"].date()).days),
            quality_penalty=penalty if available else 5.0,
            reason="" if available else "NAAIM fields unavailable",
            fields=fields,
        )

    def history_path(self, config: Dict[str, Any]) -> Path:
        if "paths" in config and config.get("paths", {}).get("soft_history_dir"):
            base = resolve_path(config, "soft_history_dir")
        else:
            base = Path("data/soft_history")
        return base / "naaim_exposure.csv"


class CnnFearGreedSource:
    name = "cnn_fear_greed"
    feature_flag = "data_cnn_fgi"

    def collect(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        if not bool(config.get("features", {}).get(self.feature_flag, False)):
            return SoftDataRecord(self.name, day, None, "CNN_FGI", False, reason=f"feature disabled: {self.feature_flag}")
        return self.fetch(as_of, config)

    def fetch(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        path = self.history_path(config)
        if not path.exists():
            return SoftDataRecord(self.name, day, None, "CNN_FGI", False, quality_penalty=5.0, reason="CNN F&G history missing")
        frame = pd.read_csv(path, parse_dates=["date", "publish_date"])
        records = [(row["publish_date"].date(), row) for row in frame.to_dict("records")]
        picked = asof_pick(records, day)
        if picked is None:
            return SoftDataRecord(self.name, day, None, "CNN_FGI", False, quality_penalty=5.0, reason="no CNN F&G record available as of date")
        fields = {
            "cnn_fear_greed": _finite(picked.get("cnn_fear_greed")),
            "cnn_fear_greed_pctl": _finite(picked.get("cnn_fear_greed_pctl")),
        }
        available = fields["cnn_fear_greed"] is not None
        row_is_proxy = bool(picked.get("is_proxy", False))
        return SoftDataRecord(
            self.name,
            day,
            fields["cnn_fear_greed"],
            "CNN_FGI_PROXY" if row_is_proxy else "CNN_FGI",
            available,
            is_proxy=row_is_proxy,
            latency_days=max(0, (day - picked["publish_date"].date()).days),
            quality_penalty=3.0 if available else 5.0,
            reason="" if available else "CNN F&G fields unavailable",
            fields=fields,
        )

    def history_path(self, config: Dict[str, Any]) -> Path:
        if "paths" in config and config.get("paths", {}).get("soft_history_dir"):
            base = resolve_path(config, "soft_history_dir")
        else:
            base = Path("data/soft_history")
        return base / "cnn_fear_greed.csv"


def parse_aaii_sentiment_xls(path: Path) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name="SENTIMENT", header=2)
    dates = pd.to_datetime(raw["Reported"], errors="coerce")
    clean = raw.loc[dates.notna()].copy()
    clean["date"] = dates[dates.notna()].dt.normalize()
    clean["aaii_bull"] = pd.to_numeric(clean["Unnamed: 1"], errors="coerce")
    clean["aaii_bear"] = pd.to_numeric(clean["Unnamed: 3"], errors="coerce")
    clean["aaii_bull_bear_spread"] = pd.to_numeric(clean["Bull-Bear"], errors="coerce")
    clean = clean.dropna(subset=["date", "aaii_bull", "aaii_bear", "aaii_bull_bear_spread"]).sort_values("date")
    clean["aaii_bull_pctl"] = clean["aaii_bull"].rolling(156, min_periods=52).apply(_last_percentile, raw=False)
    clean["aaii_spread_pctl"] = clean["aaii_bull_bear_spread"].rolling(156, min_periods=52).apply(_last_percentile, raw=False)
    clean["publish_date"] = clean["date"]
    return clean[["date", "publish_date", "aaii_bull", "aaii_bear", "aaii_bull_bear_spread", "aaii_bull_pctl", "aaii_spread_pctl"]]


def _last_percentile(window: pd.Series) -> float:
    current = window.iloc[-1]
    if pd.isna(current):
        return float("nan")
    valid = window.dropna()
    if valid.empty:
        return float("nan")
    return float((valid <= current).mean() * 100.0)


def _finite(value: Any) -> Optional[float]:
    try:
        out = float(value)
        return out if out == out else None
    except Exception:
        return None
