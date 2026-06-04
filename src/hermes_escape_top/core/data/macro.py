from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any
from typing import Dict, Optional

import pandas as pd

from ...config import resolve_path
from .adapters import SoftDataRecord
from .pit import asof_pick


@dataclass(frozen=True)
class NetLiquidityRecord:
    as_of: date
    value: Optional[float]
    change_10d: Optional[float]
    source: str
    data_available: bool
    reason: str = ""

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["as_of"] = self.as_of.isoformat()
        return payload


def net_liquidity_from_series(walcl: pd.Series, wtregen: pd.Series, rrp: pd.Series, as_of: str) -> NetLiquidityRecord:
    day = date.fromisoformat(str(as_of)[:10])
    frame = pd.concat({"walcl": walcl, "wtregen": wtregen, "rrp": rrp}, axis=1).dropna()
    frame = frame.loc[frame.index <= pd.Timestamp(as_of)]
    if frame.empty:
        return NetLiquidityRecord(day, None, None, "FRED", False, "missing input series")
    net = frame["walcl"] - frame["wtregen"] - frame["rrp"]
    change = float(net.iloc[-1] - net.iloc[-11]) if len(net) >= 11 else None
    return NetLiquidityRecord(day, float(net.iloc[-1]), change, "FRED", True)


class FredNetLiquiditySource:
    name = "net_liquidity"
    feature_flag = "data_net_liquidity"
    fred_ids = {"walcl": "WALCL", "wtregen": "WTREGEN", "rrp": "RRPONTSYD"}

    def collect(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        if not bool(config.get("features", {}).get(self.feature_flag, False)):
            return SoftDataRecord(self.name, day, None, "FRED", False, reason=f"feature disabled: {self.feature_flag}")
        path = self.history_path(config)
        if not path.exists() and not config.get("runtime", {}).get("offline_replay_mode", False):
            try:
                self.backfill(config=config)
            except Exception as exc:
                return SoftDataRecord(self.name, day, None, "FRED", False, quality_penalty=5.0, reason=f"FRED backfill failed: {exc}")
        return self.fetch(as_of, config)

    def backfill(self, start: str = "2015-01-01", end: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> Path:
        cfg = config or {}
        series = {name: fetch_fred_graph_csv(series_id, start=start, end=end) for name, series_id in self.fred_ids.items()}
        frame = fred_net_liquidity_frame(series["walcl"], series["wtregen"], series["rrp"])
        path = self.history_path(cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)
        return path

    def fetch(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        path = self.history_path(config)
        if not path.exists():
            return SoftDataRecord(self.name, day, None, "FRED", False, quality_penalty=5.0, reason="FRED net-liquidity history missing")
        frame = pd.read_csv(path, parse_dates=["date", "publish_date"])
        records = []
        for row in frame.to_dict("records"):
            records.append((row["publish_date"].date(), row))
        picked = asof_pick(records, day)
        if picked is None:
            return SoftDataRecord(self.name, day, None, "FRED", False, quality_penalty=5.0, reason="no FRED record available as of date")
        value = _finite(picked.get("net_liq_chg10_pctl"))
        fields = {
            "net_liq": _finite(picked.get("net_liq")),
            "net_liq_chg10": _finite(picked.get("net_liq_chg10")),
            "net_liq_chg10_pctl": value,
        }
        return SoftDataRecord(
            self.name,
            day,
            value,
            "FRED",
            value is not None,
            is_proxy=False,
            latency_days=max(0, (day - picked["publish_date"].date()).days),
            quality_penalty=0.0 if value is not None else 5.0,
            reason="" if value is not None else "FRED percentile unavailable",
            fields=fields,
        )

    def history_path(self, config: Dict[str, Any]) -> Path:
        if "paths" in config and config.get("paths", {}).get("soft_history_dir"):
            base = resolve_path(config, "soft_history_dir")
        else:
            base = Path("data/soft_history")
        return base / "fred_net_liquidity.csv"


class CboeIndicesSource:
    name = "cboe_indices"
    feature_flag = "data_skew_vvix"
    symbols = {
        "vix": "^VIX",
        "vix3m": "^VIX3M",
        "vix9d": "^VIX9D",
        "skew": "^SKEW",
        "vvix": "^VVIX",
    }

    def collect(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        if not bool(config.get("features", {}).get(self.feature_flag, False)):
            return SoftDataRecord(self.name, day, None, "local_cboe_history", False, reason=f"feature disabled: {self.feature_flag}")
        return self.fetch(as_of, config)

    def fetch(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        from .store import LocalStore

        day = date.fromisoformat(str(as_of)[:10])
        store = LocalStore(config)
        closes: Dict[str, Optional[float]] = {}
        pctl: Dict[str, Optional[float]] = {}
        as_of_dates = []
        for field, symbol in self.symbols.items():
            history = _sanitize_cboe_history(field, store.load_history(symbol))
            closes[field] = _close_at_or_before(history, as_of)
            pctl[f"{field}_pctl"] = _close_percentile(history, as_of)
            row_date = _row_date_at_or_before(history, as_of)
            if row_date is not None:
                as_of_dates.append(row_date)
        vix = closes.get("vix")
        vix3m = closes.get("vix3m")
        vix9d = closes.get("vix9d")
        fields = {
            "vix_term_ratio": vix / vix3m if vix is not None and vix3m not in (None, 0.0) else None,
            "vix9d_vix_ratio": vix9d / vix if vix9d is not None and vix not in (None, 0.0) else None,
            "skew_index": closes.get("skew"),
            "vvix_index": closes.get("vvix"),
            "skew_pctl": pctl.get("skew_pctl"),
            "vvix_pctl": pctl.get("vvix_pctl"),
        }
        available = fields["skew_index"] is not None and fields["vvix_pctl"] is not None
        picked_date = max(as_of_dates) if as_of_dates else day
        return SoftDataRecord(
            self.name,
            day,
            fields["vvix_pctl"],
            "local_cboe_history",
            available,
            is_proxy=False,
            latency_days=max(0, (day - picked_date).days),
            quality_penalty=0.0 if available else 5.0,
            reason="" if available else "CBOE index history missing or insufficient warmup",
            fields=fields,
        )


def fetch_fred_graph_csv(series_id: str, start: str = "2015-01-01", end: Optional[str] = None) -> pd.Series:
    import requests

    response = requests.get(
        "https://fred.stlouisfed.org/graph/fredgraph.csv",
        params={"id": series_id, "cosd": start, **({"coed": end} if end else {})},
        timeout=30,
    )
    response.raise_for_status()
    from io import StringIO

    frame = pd.read_csv(StringIO(response.text))
    date_col = "observation_date" if "observation_date" in frame.columns else "DATE"
    value_col = series_id if series_id in frame.columns else frame.columns[-1]
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    values = pd.to_numeric(frame[value_col].replace(".", pd.NA), errors="coerce")
    series = pd.Series(values.values, index=frame[date_col]).dropna().sort_index()
    return series


def fred_net_liquidity_frame(walcl: pd.Series, wtregen: pd.Series, rrp: pd.Series, percentile_window: int = 252) -> pd.DataFrame:
    frame = pd.concat({"walcl": walcl, "wtregen": wtregen, "rrp": rrp}, axis=1).sort_index()
    frame = frame.ffill().dropna()
    frame["net_liq"] = frame["walcl"] - frame["wtregen"] - frame["rrp"]
    frame["net_liq_chg10"] = frame["net_liq"].diff(10)
    frame["net_liq_chg10_pctl"] = frame["net_liq_chg10"].rolling(percentile_window, min_periods=60).apply(_last_percentile, raw=False)
    out = frame.reset_index().rename(columns={"index": "date"})
    if "date" not in out:
        out = out.rename(columns={out.columns[0]: "date"})
    out["publish_date"] = pd.to_datetime(out["date"]) + pd.Timedelta(days=1)
    columns = ["date", "publish_date", "walcl", "wtregen", "rrp", "net_liq", "net_liq_chg10", "net_liq_chg10_pctl"]
    return out[columns]


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


def _close_at_or_before(history: pd.DataFrame, as_of: str) -> Optional[float]:
    if history is None or history.empty or "Close" not in history:
        return None
    local = history.loc[history.index <= pd.Timestamp(str(as_of)[:10])]
    if local.empty:
        return None
    return _finite(local["Close"].iloc[-1])


def _row_date_at_or_before(history: pd.DataFrame, as_of: str) -> Optional[date]:
    if history is None or history.empty:
        return None
    local = history.loc[history.index <= pd.Timestamp(str(as_of)[:10])]
    if local.empty:
        return None
    return local.index[-1].date()


def _close_percentile(history: pd.DataFrame, as_of: str, window: int = 252, min_periods: int = 60) -> Optional[float]:
    if history is None or history.empty or "Close" not in history:
        return None
    local = history.loc[history.index <= pd.Timestamp(str(as_of)[:10])].tail(window)
    close = pd.to_numeric(local["Close"], errors="coerce").dropna()
    if len(close) < min_periods:
        return None
    current = float(close.iloc[-1])
    return float((close <= current).mean() * 100.0)


def _sanitize_cboe_history(field: str, history: pd.DataFrame) -> pd.DataFrame:
    if history is None or history.empty or "Close" not in history:
        return history
    out = history.copy()
    close = pd.to_numeric(out["Close"], errors="coerce")
    bounds = {
        "vix": (5.0, 120.0),
        "vix3m": (5.0, 120.0),
        "vix9d": (5.0, 150.0),
        "skew": (90.0, 220.0),
        "vvix": (40.0, 250.0),
    }
    low, high = bounds.get(field, (float("-inf"), float("inf")))
    out = out.loc[(close >= low) & (close <= high)]
    return out
