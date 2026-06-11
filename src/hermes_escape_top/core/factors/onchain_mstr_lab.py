"""Offline MSTR on-chain research lab.

This module is intentionally not imported by production scoring paths. It is a
T16 research tool for Coin Metrics community fields that were verified on
2026-06-11.
"""
from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
CM_ENDPOINT = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
APPROVED_COMMUNITY_METRICS = [
    "CapMVRVCur",
    "FlowInExUSD",
    "FlowOutExUSD",
    "SplyExUSD",
    "PriceUSD",
    "CapMrktCurUSD",
    "SplyCur",
]
PAID_OR_UNAVAILABLE_METRICS = [
    "CapRealUSD",
    "SOPR",
    "SOPRSth155d",
    "SOPRLth155d",
    "MCRC",
    "RCTC",
    "RevAllTimeUSD",
]


@dataclass(frozen=True)
class CandidateSpec:
    name: str
    column: str
    threshold: float
    direction: str
    hypothesis: str


CANDIDATES = [
    CandidateSpec(
        "CM_MVRV_HEAT",
        "mvrv_pctl_252",
        95.0,
        ">",
        "BTC valuation heat should precede MSTR top risk.",
    ),
    CandidateSpec(
        "CM_EXCHANGE_INFLOW_PRESSURE",
        "flow_in_ex_mcap_z90",
        2.0,
        ">",
        "Exchange inflow spikes indicate sell/volatility pressure.",
    ),
    CandidateSpec(
        "CM_EXCHANGE_NETFLOW_PRESSURE",
        "flow_net_ex_mcap_z90",
        2.0,
        ">",
        "Net deposits to exchanges indicate spot sell pressure.",
    ),
    CandidateSpec(
        "CM_EXCHANGE_SUPPLY_HEAT",
        "ex_supply_mcap_pctl_252",
        95.0,
        ">",
        "High exchange-held supply leaves more BTC immediately saleable.",
    ),
    CandidateSpec(
        "CM_COMPOSITE_ONCHAIN_HEAT",
        "composite_onchain_heat",
        90.0,
        ">",
        "A simple equal-weight composite should reduce single-metric noise.",
    ),
]


def fetch_coinmetrics_community(
    start: str,
    end: str,
    metrics: list[str] | None = None,
) -> pd.DataFrame:
    """Fetch verified Coin Metrics community metrics for BTC.

    Daily Coin Metrics rows are shifted by one calendar day before alignment in
    `pit_align_to_trading_days`, so the lab does not use same-day UTC data as if
    it were known before the US equity close.
    """
    metrics = metrics or APPROVED_COMMUNITY_METRICS
    params = {
        "assets": "btc",
        "metrics": ",".join(metrics),
        "frequency": "1d",
        "start_time": start,
        "end_time": end,
        "page_size": 10000,
    }
    url = f"{CM_ENDPOINT}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = json.load(response)
    rows = payload.get("data", [])
    if not rows:
        return pd.DataFrame(columns=metrics)
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(None).dt.normalize()
    for metric in metrics:
        df[metric] = pd.to_numeric(df.get(metric), errors="coerce")
    return df.set_index("date")[metrics].sort_index()


def load_history(symbol: str, root: Path = REPO_ROOT) -> pd.DataFrame:
    path_symbol = symbol.replace("-", "_").replace("^", "_")
    path = root / "src" / "hermes_escape_top" / "data" / "history" / f"{path_symbol}.csv"
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df.set_index("date").sort_index()


def pit_align_to_trading_days(cm: pd.DataFrame, trading_index: pd.DatetimeIndex) -> pd.DataFrame:
    pit = cm.copy()
    pit.index = pit.index + pd.Timedelta(days=1)
    return pit.reindex(trading_index).ffill()


def rolling_percentile(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    def last_pct(values: np.ndarray) -> float:
        clean = values[~np.isnan(values)]
        if len(clean) == 0:
            return np.nan
        return float((clean <= clean[-1]).mean() * 100.0)

    return series.rolling(window, min_periods=min_periods).apply(last_pct, raw=True)


def rolling_z(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    mean = series.rolling(window, min_periods=min_periods).mean()
    std = series.rolling(window, min_periods=min_periods).std(ddof=0)
    return (series - mean) / std.replace(0.0, np.nan)


def build_onchain_features(cm_aligned: pd.DataFrame) -> pd.DataFrame:
    df = cm_aligned.copy()
    df["flow_net_ex_usd"] = df["FlowInExUSD"] - df["FlowOutExUSD"]
    df["flow_in_ex_mcap"] = df["FlowInExUSD"] / df["CapMrktCurUSD"]
    df["flow_net_ex_mcap"] = df["flow_net_ex_usd"] / df["CapMrktCurUSD"]
    df["ex_supply_mcap"] = df["SplyExUSD"] / df["CapMrktCurUSD"]
    df["mvrv_pctl_252"] = rolling_percentile(df["CapMVRVCur"], 252, 126)
    df["mvrv_z252"] = rolling_z(df["CapMVRVCur"], 252, 126)
    df["flow_in_ex_mcap_z90"] = rolling_z(df["flow_in_ex_mcap"], 90, 45)
    df["flow_net_ex_mcap_z90"] = rolling_z(df["flow_net_ex_mcap"], 90, 45)
    df["ex_supply_mcap_pctl_252"] = rolling_percentile(df["ex_supply_mcap"], 252, 126)
    flow_in_pctl = rolling_percentile(df["flow_in_ex_mcap"], 252, 126)
    netflow_pctl = rolling_percentile(df["flow_net_ex_mcap"], 252, 126)
    df["composite_onchain_heat"] = pd.concat(
        [df["mvrv_pctl_252"], flow_in_pctl, netflow_pctl, df["ex_supply_mcap_pctl_252"]],
        axis=1,
    ).mean(axis=1)
    return df


def label_mstr_tops(
    mstr_close: pd.Series,
    horizon: int = 60,
    drawdown_threshold: float = -0.30,
    prior_peak_window: int = 20,
    min_gap: int = 45,
) -> list[pd.Timestamp]:
    closes = mstr_close.dropna().sort_index()
    prior_peak = closes.rolling(prior_peak_window, min_periods=10).max()
    candidates: list[tuple[pd.Timestamp, float]] = []
    values = closes.to_numpy()
    dates = list(closes.index)
    for i, date in enumerate(dates):
        if i + 2 >= len(values):
            continue
        future = values[i + 1 : min(len(values), i + 1 + horizon)]
        if len(future) < 10:
            continue
        future_dd = float(np.nanmin(future) / values[i] - 1.0)
        near_prior_peak = values[i] >= float(prior_peak.iloc[i]) * 0.98
        if near_prior_peak and future_dd <= drawdown_threshold:
            candidates.append((date, float(values[i])))

    clusters: list[list[tuple[pd.Timestamp, float]]] = []
    for date, close in candidates:
        if not clusters or (closes.index.get_loc(date) - closes.index.get_loc(clusters[-1][-1][0])) > min_gap:
            clusters.append([(date, close)])
        else:
            clusters[-1].append((date, close))
    tops = [max(cluster, key=lambda item: item[1])[0] for cluster in clusters]
    return tops


def extract_existing_mstr_factor_panel(report_path: Path) -> pd.DataFrame:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for row in data.get("rows", []):
        scores = row.get("scores", {}).get("MSTR", {}).get("factor_scores", {})
        record: dict[str, Any] = {"date": row.get("date")}
        for module, factors in scores.items():
            for factor in factors:
                factor_id = factor.get("factor_id")
                if factor_id:
                    record[f"{module}:{factor_id}"] = factor.get("score")
        rows.append(record)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df.set_index("date").sort_index()


def fire_mask(series: pd.Series, spec: CandidateSpec) -> pd.Series:
    if spec.direction == ">":
        return series > spec.threshold
    if spec.direction == "<":
        return series < spec.threshold
    raise ValueError(f"unsupported direction: {spec.direction}")


def fire_episodes(mask: pd.Series, cooldown: int = 20) -> list[pd.Timestamp]:
    active_dates = list(mask[mask].index)
    if not active_dates:
        return []
    index = mask.index
    episodes = [active_dates[0]]
    last_pos = index.get_loc(active_dates[0])
    for date in active_dates[1:]:
        pos = index.get_loc(date)
        if pos - last_pos > cooldown:
            episodes.append(date)
            last_pos = pos
    return episodes


def precision_against_tops(
    episodes: list[pd.Timestamp],
    tops: list[pd.Timestamp],
    trading_index: pd.DatetimeIndex,
    lead_window: int = 60,
) -> float | None:
    if not episodes:
        return None
    top_positions = [trading_index.get_loc(t) for t in tops if t in trading_index]
    hits = 0
    for episode in episodes:
        pos = trading_index.get_loc(episode)
        if any(0 < top_pos - pos <= lead_window for top_pos in top_positions):
            hits += 1
    return hits / len(episodes)


def lead_time_summary(
    series: pd.Series,
    spec: CandidateSpec,
    tops: list[pd.Timestamp],
    lead_window: int = 60,
) -> dict[str, Any]:
    mask = fire_mask(series, spec)
    lead_times: dict[str, int | None] = {}
    idx = series.index
    for top in tops:
        if top not in idx:
            lead_times[top.date().isoformat()] = None
            continue
        top_pos = idx.get_loc(top)
        start_pos = max(0, top_pos - lead_window)
        window = mask.iloc[start_pos:top_pos]
        fire_dates = list(window[window].index)
        lead_times[top.date().isoformat()] = int((top - fire_dates[0]).days) if fire_dates else None
    valid = [v for v in lead_times.values() if v is not None]
    episodes = fire_episodes(mask)
    return {
        "lead_times_days": lead_times,
        "hit_rate": len(valid) / len(tops) if tops else 0.0,
        "median_lead_days": float(np.median(valid)) if valid else None,
        "fire_rate": float(mask.mean()) if len(mask) else 0.0,
        "episodes": episodes,
        "precision": precision_against_tops(episodes, tops, idx, lead_window=lead_window),
    }


def correlation_summary(candidates: pd.DataFrame, factor_panel: pd.DataFrame) -> dict[str, dict[str, Any]]:
    joined = candidates.join(factor_panel, how="inner")
    result: dict[str, dict[str, Any]] = {}
    if joined.empty:
        return result
    candidate_cols = [spec.name for spec in CANDIDATES if spec.name in joined.columns]
    factor_cols = [c for c in joined.columns if c not in candidate_cols]
    for candidate in candidate_cols:
        corrs = joined[[candidate] + factor_cols].corr(method="spearman")[candidate].drop(candidate, errors="ignore").dropna()
        if corrs.empty:
            result[candidate] = {"max_abs_corr": None, "top_factor": None, "by_module": {}}
            continue
        top_factor = corrs.abs().sort_values(ascending=False).index[0]
        by_module: dict[str, float] = {}
        for module in ["A", "B", "C", "D"]:
            module_corrs = corrs[[c.startswith(f"{module}:") for c in corrs.index]]
            by_module[module] = float(module_corrs.abs().max()) if not module_corrs.empty else float("nan")
        result[candidate] = {
            "max_abs_corr": float(abs(corrs[top_factor])),
            "top_factor": top_factor,
            "top_corr": float(corrs[top_factor]),
            "by_module": by_module,
        }
    return result


def run_lab(start: str, end: str) -> dict[str, Any]:
    mstr = load_history("MSTR")
    trading_index = mstr.loc[start:end].index
    cm_raw = fetch_coinmetrics_community(start=start, end=end)
    cm_aligned = pit_align_to_trading_days(cm_raw, trading_index)
    features = build_onchain_features(cm_aligned)

    tops = label_mstr_tops(mstr.loc[trading_index, "close"])
    candidate_scores = pd.DataFrame(index=features.index)
    for spec in CANDIDATES:
        candidate_scores[spec.name] = features[spec.column]

    factor_panel = extract_existing_mstr_factor_panel(REPO_ROOT / "building" / "reports" / "Backtest_FULL_2018_2026.json")
    correlations = correlation_summary(candidate_scores, factor_panel)

    candidate_results: dict[str, Any] = {}
    for spec in CANDIDATES:
        series = candidate_scores[spec.name].dropna()
        summary = lead_time_summary(series, spec, tops)
        corr = correlations.get(spec.name, {})
        survivor = (
            summary["hit_rate"] >= 0.50
            and (summary["precision"] or 0.0) >= 0.30
            and summary["fire_rate"] <= 0.20
            and (corr.get("max_abs_corr") is None or corr.get("max_abs_corr", 1.0) < 0.80)
        )
        candidate_results[spec.name] = {
            "column": spec.column,
            "threshold": spec.threshold,
            "hypothesis": spec.hypothesis,
            "hit_rate": summary["hit_rate"],
            "median_lead_days": summary["median_lead_days"],
            "fire_rate": summary["fire_rate"],
            "episode_count": len(summary["episodes"]),
            "precision": summary["precision"],
            "lead_times_days": summary["lead_times_days"],
            "correlation": corr,
            "offline_survivor": survivor,
        }

    return {
        "start": start,
        "end": end,
        "metrics": APPROVED_COMMUNITY_METRICS,
        "unavailable_metrics": PAID_OR_UNAVAILABLE_METRICS,
        "source_rows": len(cm_raw),
        "aligned_rows": len(features),
        "cm_first_date": cm_raw.index.min().date().isoformat() if not cm_raw.empty else None,
        "cm_last_date": cm_raw.index.max().date().isoformat() if not cm_raw.empty else None,
        "pit_shift": "Coin Metrics date + 1 calendar day, then forward-filled to MSTR trading days",
        "labeled_tops": [t.date().isoformat() for t in tops],
        "candidate_results": candidate_results,
    }


def _fmt_pct(value: float | None) -> str:
    if value is None or not np.isfinite(value):
        return "n/a"
    return f"{value:.1%}"


def _fmt_num(value: float | None, digits: int = 3) -> str:
    if value is None or not np.isfinite(value):
        return "n/a"
    return f"{value:.{digits}f}"


def render_report(result: dict[str, Any]) -> str:
    lines = [
        "# MSTR On-Chain Offline Lab — 2026-06-11",
        "",
        "Scope: T16 offline research only. This report does not change production scoring, config, routing, or gates.",
        "",
        "## Data Boundary",
        "",
        f"- Window: `{result['start']}` to `{result['end']}`",
        f"- Coin Metrics rows: {result['source_rows']} raw; {result['aligned_rows']} aligned MSTR trading days",
        f"- Raw Coin Metrics date range: `{result['cm_first_date']}` to `{result['cm_last_date']}`",
        f"- PIT alignment: {result['pit_shift']}",
        f"- Approved fields: `{', '.join(result['metrics'])}`",
        f"- Not implemented because current community probes returned 403/unsupported: `{', '.join(result['unavailable_metrics'])}`",
        "",
        "## D-Module Structure Decision",
        "",
        "MSTR D already reaches the 20-point cap: D1 5 + D2 3 + D3 4 + D4 4 + D_M3 BTC proxy 4. "
        "Any on-chain survivor must replace or split the existing 4-point `D_M3_BTC_VOLATILITY_PROXY` budget; "
        "it must not expand the D cap and must not add another independent 4-point block. Preferred T19 design, if any candidate survives: "
        "`D_M3_BTC_RISK_COMPOSITE` remains max 4, with price-volatility stress and on-chain stress blended inside that same budget.",
        "",
        "## Labeled Tops",
        "",
        "Labels are offline outcomes: MSTR near a 20-trading-day peak followed by at least a 30% drawdown within 60 trading days, deduplicated by 45 trading days.",
        "",
        ", ".join(f"`{d}`" for d in result["labeled_tops"]) or "No labeled tops.",
        "",
        "## Candidate Screen",
        "",
        "| Candidate | Threshold | Hit rate vs tops | Median lead | Precision | Fire rate | Episodes | Max abs corr | Top correlated existing factor | Survivor? |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for name, row in result["candidate_results"].items():
        corr = row.get("correlation", {})
        lines.append(
            f"| `{name}` | {row['threshold']} | {_fmt_pct(row['hit_rate'])} | "
            f"{_fmt_num(row['median_lead_days'], 1)}d | {_fmt_pct(row['precision'])} | "
            f"{_fmt_pct(row['fire_rate'])} | {row['episode_count']} | "
            f"{_fmt_num(corr.get('max_abs_corr'))} | `{corr.get('top_factor') or 'n/a'}` | "
            f"{'YES' if row['offline_survivor'] else 'NO'} |"
        )

    lines += [
        "",
        "## Lead-Time Detail",
        "",
    ]
    for name, row in result["candidate_results"].items():
        lead = ", ".join(f"{top}:{days if days is not None else 'miss'}" for top, days in row["lead_times_days"].items())
        lines.append(f"- `{name}`: {lead}")

    survivors = [name for name, row in result["candidate_results"].items() if row["offline_survivor"]]
    lines += [
        "",
        "## Offline Conclusion",
        "",
    ]
    if survivors:
        lines.append(
            "Offline survivors for T19 queue: "
            + ", ".join(f"`{name}`" for name in survivors)
            + ". These are research candidates only; each still gets exactly one in-system gate after A confirms the backtest window is free."
        )
    else:
        lines.append(
            "No candidate met the offline survivor bar. Keep the source adapter/lab for future paid-data expansion, but do not queue T19 gates from this subset."
        )
    lines += [
        "",
        "## Config Keys For Agent A",
        "",
        "- If a future survivor is approved for shadow wiring: `features.data_onchain_mstr=false` (default OFF; comment: Coin Metrics/approved on-chain MSTR lab feed, PIT shifted one day, no live scoring until gate passes).",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default="2026-05-29")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "building" / "reports" / "onchain_mstr_lab" / "ONCHAIN_MSTR_LAB_2026_06_11.md")
    parser.add_argument("--json-out", type=Path, default=REPO_ROOT / "building" / "reports" / "onchain_mstr_lab" / "onchain_mstr_lab_2026_06_11.json")
    args = parser.parse_args()

    result = run_lab(args.start, args.end)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_report(result), encoding="utf-8")
    args.json_out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"wrote {args.out}")
    print(f"wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
