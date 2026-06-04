from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd


OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]


@dataclass(frozen=True)
class SynthValidation:
    ret_corr: Optional[float]
    tracking_error_annual: Optional[float]
    max_abs_dev: Optional[float]
    overlap_start: Optional[str]
    overlap_end: Optional[str]
    observations: int
    pass_corr: bool
    pass_tracking_error: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ret_corr": self.ret_corr,
            "tracking_error_annual": self.tracking_error_annual,
            "max_abs_dev": self.max_abs_dev,
            "overlap_start": self.overlap_start,
            "overlap_end": self.overlap_end,
            "observations": self.observations,
            "pass_corr": self.pass_corr,
            "pass_tracking_error": self.pass_tracking_error,
            "passed": self.pass_corr and self.pass_tracking_error,
        }


def equal_weight_basket(component_dfs: dict[str, pd.DataFrame], rebalance: str = "Q") -> pd.Series:
    """Rebuild a fallback underlying return series from component closes.

    The function is deterministic and uses only component returns available on
    each date. Weights reset to equal-weight on the first observed date and at
    each rebalance period boundary, then drift with price moves until the next
    rebalance.
    """

    returns = []
    for symbol, frame in sorted(component_dfs.items()):
        normalized = _normalize_history(frame)
        if normalized.empty or "Close" not in normalized:
            continue
        returns.append(pd.to_numeric(normalized["Close"], errors="coerce").pct_change().rename(symbol))
    if not returns:
        return pd.Series(dtype=float, name="equal_weight_basket_ret")

    ret_frame = pd.concat(returns, axis=1).sort_index()
    if ret_frame.empty:
        return pd.Series(dtype=float, name="equal_weight_basket_ret")

    out = []
    weights: Optional[pd.Series] = None
    current_period = None
    for day, row in ret_frame.iterrows():
        available = row.dropna()
        if available.empty:
            out.append((day, 0.0))
            continue
        period = day.to_period(rebalance)
        if weights is None or period != current_period:
            weights = pd.Series(1.0 / len(available), index=available.index, dtype=float)
            current_period = period
        else:
            weights = weights.reindex(available.index).dropna()
            missing = [item for item in available.index if item not in weights.index]
            if missing:
                weights = pd.concat([weights, pd.Series(0.0, index=missing)])
            if float(weights.sum()) <= 0:
                weights = pd.Series(1.0 / len(available), index=available.index, dtype=float)
            else:
                weights = weights / float(weights.sum())
        daily_ret = float((weights.reindex(available.index).fillna(0.0) * available).sum())
        out.append((day, daily_ret))
        weights = weights.reindex(available.index).fillna(0.0) * (1.0 + available)
        total = float(weights.sum())
        weights = weights / total if total > 0 else pd.Series(1.0 / len(available), index=available.index, dtype=float)

    return pd.Series({day: value for day, value in out}, name="equal_weight_basket_ret").sort_index()


def reconstruct_leveraged_history(
    symbol: str,
    leverage: float,
    underlying_ret: pd.Series,
    real_df: pd.DataFrame,
    cfg: dict,
) -> pd.DataFrame:
    """Rebuild a leveraged symbol history with daily-reset leverage math.

    Default mode creates a pre-inception synthetic segment and appends real rows
    from the first true observation onward. Set ``cfg["mode"] = "forward"`` to
    generate a pure synthetic overlap path anchored to the first real close; this
    is used only for validation and is never written as real data.
    """

    real = _normalize_history(real_df)
    if real.empty or "Close" not in real:
        raise ValueError(f"{symbol} real_df must contain at least one Close row")
    real = _strip_existing_proxy(real)
    if real.empty:
        raise ValueError(f"{symbol} real_df contains no non-proxy real rows")

    ret = _leveraged_return_series(leverage, underlying_ret, cfg)
    if ret.empty:
        raise ValueError("underlying_ret produced no usable returns")

    mode = str(cfg.get("mode") or "preseam")
    start = pd.Timestamp(cfg.get("start") or ret.index.min()).normalize()
    end = pd.Timestamp(cfg.get("end") or real.index.max()).normalize()
    anchor_date = pd.Timestamp(cfg.get("anchor_date") or real.index.min()).normalize()
    real_anchor = _close_at_or_before(real, anchor_date)
    if real_anchor is None:
        raise ValueError(f"{symbol} has no real close at or before anchor {anchor_date.date().isoformat()}")

    if mode == "forward":
        synth = _forward_proxy_frame(symbol, ret, float(real_anchor), anchor_date, start, end, cfg)
        return synth

    synth = _backward_proxy_frame(symbol, ret, float(real_anchor), anchor_date, start, cfg)
    marked_real = _mark_real_frame(real, cfg)
    combined = pd.concat([synth, marked_real.loc[marked_real.index >= anchor_date]]).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    combined["symbol"] = symbol
    return combined


def validate_synth(real_df: pd.DataFrame, synth_df: pd.DataFrame, overlap: tuple) -> dict:
    """Validate synthetic vs real returns over a declared overlap window."""

    real = _normalize_history(real_df)
    synth = _normalize_history(synth_df)
    if real.empty or synth.empty or "Close" not in real or "Close" not in synth:
        return SynthValidation(None, None, None, None, None, 0, False, False).to_dict()

    start, end = pd.Timestamp(overlap[0]), pd.Timestamp(overlap[1])
    real_close = pd.to_numeric(real.loc[(real.index >= start) & (real.index <= end), "Close"], errors="coerce")
    synth_close = pd.to_numeric(synth.loc[(synth.index >= start) & (synth.index <= end), "Close"], errors="coerce")
    common = real_close.dropna().index.intersection(synth_close.dropna().index)
    if len(common) < 3:
        return SynthValidation(None, None, None, None, None, 0, False, False).to_dict()

    real_ret = real_close.loc[common].pct_change().dropna()
    synth_ret = synth_close.loc[common].pct_change().dropna()
    ret_common = real_ret.index.intersection(synth_ret.index)
    if len(ret_common) < 2:
        return SynthValidation(None, None, None, None, None, 0, False, False).to_dict()

    ret_corr_value = real_ret.loc[ret_common].corr(synth_ret.loc[ret_common])
    tracking_error = float((real_ret.loc[ret_common] - synth_ret.loc[ret_common]).std() * (252.0 ** 0.5))
    real_norm = real_close.loc[common] / float(real_close.loc[common].iloc[0])
    synth_norm = synth_close.loc[common] / float(synth_close.loc[common].iloc[0])
    max_abs_dev = float((synth_norm / real_norm - 1.0).abs().max())
    ret_corr = None if pd.isna(ret_corr_value) else float(ret_corr_value)
    return SynthValidation(
        ret_corr=ret_corr,
        tracking_error_annual=tracking_error,
        max_abs_dev=max_abs_dev,
        overlap_start=common.min().date().isoformat(),
        overlap_end=common.max().date().isoformat(),
        observations=int(len(ret_common)),
        pass_corr=bool(ret_corr is not None and ret_corr > 0.98),
        pass_tracking_error=bool(tracking_error < 0.05),
    ).to_dict()


def _leveraged_return_series(leverage: float, underlying_ret: pd.Series, cfg: dict) -> pd.Series:
    ret = pd.to_numeric(underlying_ret, errors="coerce").copy()
    ret.index = pd.to_datetime(ret.index, errors="coerce")
    ret = ret[~ret.index.isna()].sort_index().dropna()
    daily_fee = float(cfg.get("expense_ratio_annual", 0.0) or 0.0) / 252.0
    short_rate = cfg.get("short_rate_series")
    if isinstance(short_rate, pd.Series):
        rate = pd.to_numeric(short_rate, errors="coerce")
        rate.index = pd.to_datetime(rate.index, errors="coerce")
        rate = rate[~rate.index.isna()].sort_index().reindex(ret.index).ffill().fillna(0.0)
    else:
        rate = pd.Series(float(cfg.get("financing_rate_annual", 0.0) or 0.0), index=ret.index)
    financing = max(0.0, abs(float(leverage)) - 1.0) * rate / 252.0
    out = float(leverage) * ret - daily_fee - financing
    return out.clip(lower=-0.95).rename("synth_return")


def _backward_proxy_frame(symbol: str, ret: pd.Series, anchor_close: float, anchor_date: pd.Timestamp, start: pd.Timestamp, cfg: dict) -> pd.DataFrame:
    dates = ret.loc[(ret.index >= start) & (ret.index <= anchor_date)].index
    if anchor_date not in dates:
        dates = dates.union(pd.DatetimeIndex([anchor_date])).sort_values()
    closes: dict[pd.Timestamp, float] = {anchor_date: float(anchor_close)}
    ordered = list(dates)
    for idx in range(len(ordered) - 2, -1, -1):
        day = ordered[idx]
        next_day = ordered[idx + 1]
        next_ret = float(ret.get(next_day, 0.0) or 0.0)
        closes[day] = closes[next_day] / max(0.05, 1.0 + next_ret)
    synth_dates = [day for day in ordered if day < anchor_date and day in closes]
    return _proxy_frame(symbol, synth_dates, closes, cfg)


def _forward_proxy_frame(
    symbol: str,
    ret: pd.Series,
    anchor_close: float,
    anchor_date: pd.Timestamp,
    start: pd.Timestamp,
    end: pd.Timestamp,
    cfg: dict,
) -> pd.DataFrame:
    dates = ret.loc[(ret.index >= max(start, anchor_date)) & (ret.index <= end)].index
    if anchor_date not in dates:
        dates = pd.DatetimeIndex([anchor_date]).union(dates).sort_values()
    closes: dict[pd.Timestamp, float] = {dates[0]: float(anchor_close)}
    previous = dates[0]
    for day in list(dates)[1:]:
        closes[day] = closes[previous] * max(0.05, 1.0 + float(ret.get(day, 0.0) or 0.0))
        previous = day
    return _proxy_frame(symbol, list(dates), closes, cfg)


def _proxy_frame(symbol: str, dates: list[pd.Timestamp], closes: dict[pd.Timestamp, float], cfg: dict) -> pd.DataFrame:
    rows = []
    for day in dates:
        close = float(closes[day])
        rows.append(
            {
                "Open": close,
                "High": close,
                "Low": close,
                "Close": close,
                "Adj Close": close,
                "Volume": 0.0,
                "is_proxy": True,
                "source": str(cfg.get("source") or f"synth_{cfg.get('leverage', 'x')}x"),
                "underlying": str(cfg.get("underlying") or ""),
                "leverage": float(cfg.get("leverage", 0.0) or 0.0),
                "expense_ratio_annual": float(cfg.get("expense_ratio_annual", 0.0) or 0.0),
                "financing_rate_annual": float(cfg.get("financing_rate_annual", 0.0) or 0.0),
            }
        )
    out = pd.DataFrame(rows, index=pd.DatetimeIndex(dates, name="Date")).sort_index()
    out["symbol"] = symbol
    return out


def _mark_real_frame(real: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    out = real.copy()
    out["is_proxy"] = False
    out["source"] = out.get("source", "real_history")
    out["underlying"] = out.get("underlying", str(cfg.get("underlying") or ""))
    out["leverage"] = out.get("leverage", float(cfg.get("leverage", 0.0) or 0.0))
    out["expense_ratio_annual"] = out.get("expense_ratio_annual", float(cfg.get("expense_ratio_annual", 0.0) or 0.0))
    out["financing_rate_annual"] = out.get("financing_rate_annual", float(cfg.get("financing_rate_annual", 0.0) or 0.0))
    return out


def _normalize_history(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    rename = {
        "date": "Date",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "adj_close": "Adj Close",
        "volume": "Volume",
    }
    out = out.rename(columns={col: rename.get(col, col) for col in out.columns})
    if "Date" in out.columns:
        out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
        out = out.dropna(subset=["Date"]).set_index("Date")
    out.index = pd.to_datetime(out.index, errors="coerce")
    out = out[~out.index.isna()].sort_index()
    for col in OHLCV_COLUMNS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "Adj Close" not in out and "Close" in out:
        out["Adj Close"] = out["Close"]
    elif "Adj Close" in out and "Close" in out:
        out["Adj Close"] = out["Adj Close"].fillna(out["Close"])
    return out


def _strip_existing_proxy(frame: pd.DataFrame) -> pd.DataFrame:
    if "is_proxy" not in frame:
        return frame
    proxy = frame["is_proxy"].astype(str).str.lower().isin({"true", "1", "yes"})
    return frame.loc[~proxy].copy()


def _close_at_or_before(frame: pd.DataFrame, day: pd.Timestamp) -> Optional[float]:
    rows = frame.loc[frame.index <= day]
    if rows.empty or "Close" not in rows:
        return None
    value = float(rows["Close"].iloc[-1])
    return value if value == value else None
