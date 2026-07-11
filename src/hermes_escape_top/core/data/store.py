from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from ...config import PACKAGE_DIR, resolve_path


def safe_symbol(symbol: str) -> str:
    return symbol.replace("^", "_").replace("/", "_").replace("-", "_")


@dataclass
class LocalStore:
    config: Dict[str, Any]

    @property
    def history_dir(self) -> Path:
        return resolve_path(self.config, "history_dir")

    @property
    def legacy_history_dir(self) -> Path:
        return resolve_path(self.config, "legacy_history_dir")

    @property
    def archive_dir(self) -> Path:
        return resolve_path(self.config, "archive_dir")

    def ensure_dirs(self) -> None:
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def history_path(self, symbol: str, legacy: bool = False) -> Path:
        base = self.legacy_history_dir if legacy else self.history_dir
        return base / f"{safe_symbol(symbol)}.csv"

    def load_history(self, symbol: str) -> pd.DataFrame:
        path = self.history_path(symbol)
        if not path.exists():
            path = self.history_path(symbol, legacy=True)
        if not path.exists():
            return pd.DataFrame()
        raw = pd.read_csv(path)
        rename = {
            "date": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "adj_close": "Adj Close",
            "volume": "Volume",
        }
        raw = raw.rename(columns={col: rename.get(col, col) for col in raw.columns})
        if "Date" not in raw.columns:
            return pd.DataFrame()
        df = raw.assign(Date=pd.to_datetime(raw["Date"], errors="coerce")).dropna(subset=["Date"]).set_index("Date").sort_index()
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return _quality_filter_history(symbol, df)

    def copy_legacy_history(self, symbol: str) -> Optional[Path]:
        src = self.history_path(symbol, legacy=True)
        if not src.exists():
            return None
        self.ensure_dirs()
        dst = self.history_path(symbol)
        if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
            shutil.copy2(src, dst)
        return dst

    def archive_path(self, name: str, as_of: str | date) -> Path:
        day = as_of.isoformat() if isinstance(as_of, date) else str(as_of)
        return self.archive_dir / f"{name}_{day}.json"

    def write_dated_snapshot(self, name: str, as_of: str | date, payload: Dict[str, Any]) -> Path:
        self.ensure_dirs()
        path = self.archive_path(name, as_of)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        return path

    def load_dated_snapshot(self, name: str, as_of: str | date) -> Optional[Dict[str, Any]]:
        day = date.fromisoformat(str(as_of)[:10])
        candidates = []
        for path in self.archive_dir.glob(f"{name}_*.json"):
            suffix = path.stem.replace(f"{name}_", "", 1)
            try:
                snap_date = date.fromisoformat(suffix)
            except ValueError:
                continue
            if snap_date <= day:
                candidates.append((snap_date, path))
        if not candidates:
            return None
        _, path = sorted(candidates, key=lambda item: item[0])[-1]
        return json.loads(path.read_text())


def bootstrap_history(config: Dict[str, Any]) -> Dict[str, str]:
    store = LocalStore(config)
    copied: Dict[str, str] = {}
    symbols = set(config.get("symbols", {}).keys())
    symbols.update(config.get("market_symbols", []))
    for values in config.get("radars", {}).values():
        symbols.update(values)
    for values in config.get("component_proxies", {}).values():
        symbols.update(values)
    for symbol in sorted(symbols):
        path = store.copy_legacy_history(symbol)
        if path:
            copied[symbol] = str(path)
    return copied


def _quality_filter_history(symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "Close" not in frame:
        return frame
    close = pd.to_numeric(frame["Close"], errors="coerce")
    if symbol == "BTC-USD":
        return frame.loc[close > 0]
    if symbol == "^VVIX":
        mask = (close >= 40) & (close <= 250)
        return frame.loc[mask]
    if symbol == "^SKEW":
        mask = (close >= 90) & (close <= 220)
        return frame.loc[mask]
    return frame
