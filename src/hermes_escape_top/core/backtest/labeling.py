from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Iterable

import pandas as pd


@dataclass(frozen=True)
class BarrierLabel:
    as_of: str
    horizon: int
    label: int
    forward_return: float
    max_forward_drawdown: float
    uniqueness_weight: float = 1.0

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["forward_return"] = round(float(payload["forward_return"]), 6)
        payload["max_forward_drawdown"] = round(float(payload["max_forward_drawdown"]), 6)
        payload["uniqueness_weight"] = round(float(payload["uniqueness_weight"]), 6)
        return payload


def triple_barrier_labels(
    close: pd.Series,
    events: Iterable[str],
    horizon: int = 20,
    profit_take: float = 0.12,
    stop_loss: float = -0.10,
) -> list[BarrierLabel]:
    series = pd.to_numeric(close, errors="coerce").dropna()
    out = []
    for raw_event in events:
        event = pd.Timestamp(raw_event)
        if event not in series.index:
            idx = series.index[series.index <= event]
            if len(idx) == 0:
                continue
            event = idx[-1]
        loc = series.index.get_loc(event)
        future = series.iloc[loc : loc + horizon + 1]
        if len(future) < 2:
            continue
        base = float(future.iloc[0])
        rets = future / base - 1.0
        hit_profit = rets[rets >= profit_take]
        hit_loss = rets[rets <= stop_loss]
        label = 0
        if not hit_profit.empty and (hit_loss.empty or hit_profit.index[0] <= hit_loss.index[0]):
            label = 1
        elif not hit_loss.empty:
            label = -1
        out.append(
            BarrierLabel(
                as_of=event.date().isoformat(),
                horizon=horizon,
                label=label,
                forward_return=float(rets.iloc[-1]),
                max_forward_drawdown=float(rets.min()),
            )
        )
    return apply_uniqueness_weights(out, horizon)


def eval_labels(signals: Iterable[str], price: pd.Series, H: int = 20, dd_threshold: float = -0.10) -> pd.DataFrame:
    series = pd.to_numeric(price, errors="coerce").dropna()
    rows = []
    for raw_signal in signals:
        signal = pd.Timestamp(raw_signal)
        idx = series.index[series.index <= signal]
        if len(idx) == 0:
            continue
        event = idx[-1]
        loc = series.index.get_loc(event)
        future = series.iloc[loc : loc + H + 1]
        if len(future) < 2:
            continue
        base = float(future.iloc[0])
        returns = future / base - 1.0
        fwd_dd = float(returns.min())
        rows.append(
            {
                "as_of": event.date().isoformat(),
                "label": int(fwd_dd <= dd_threshold),
                "fwd_dd": fwd_dd,
                "fwd_ret": float(returns.iloc[-1]),
                "horizon": int(H),
                "dd_threshold": float(dd_threshold),
            }
        )
    return pd.DataFrame(rows)


def apply_uniqueness_weights(labels: list[BarrierLabel], horizon: int) -> list[BarrierLabel]:
    if not labels:
        return []
    starts = [pd.Timestamp(label.as_of) for label in labels]
    weights = []
    for start in starts:
        overlaps = sum(abs((start - other).days) < horizon for other in starts)
        weights.append(1.0 / max(1, overlaps))
    return [
        BarrierLabel(label.as_of, label.horizon, label.label, label.forward_return, label.max_forward_drawdown, weight)
        for label, weight in zip(labels, weights)
    ]
