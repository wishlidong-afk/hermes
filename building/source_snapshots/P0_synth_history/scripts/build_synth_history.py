from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from ..config import load_config, resolve_path
from ..core.data.manifest import freeze_manifest, write_manifest
from ..core.data.store import LocalStore, safe_symbol
from ..core.data.synth_leverage import equal_weight_basket, reconstruct_leveraged_history, validate_synth


@dataclass(frozen=True)
class SynthBuildResult:
    symbol: str
    leverage: float
    underlying: str
    path: str
    start_date: str
    end_date: str
    real_start: str
    real_end: str
    rows: int
    proxy_rows: int
    proxy_start: Optional[str]
    proxy_end: Optional[str]
    validation: Dict[str, Any]
    validation_stable_skip20: Dict[str, Any]
    official_3x_validation: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


DEFAULT_SPECS = {
    "FNGU": {
        "leverage": 3.0,
        "underlying": "^NYFANG",
        "fallback_components_key": "FNGU",
        "expense_ratio_annual": 0.0095,
        "target_start": "2018-01-01",
    },
    "FNGS": {
        "leverage": 1.0,
        "underlying": "^NYFANG",
        "fallback_components_key": "FNGU",
        "expense_ratio_annual": 0.0058,
        "target_start": "2018-01-01",
    },
}


def build_all(config: Optional[Dict[str, Any]] = None, report_path: Optional[str | Path] = None) -> Dict[str, SynthBuildResult]:
    cfg = config or load_config()
    store = LocalStore(cfg)
    results: Dict[str, SynthBuildResult] = {}
    for symbol, spec in DEFAULT_SPECS.items():
        results[symbol] = build_symbol(symbol, spec, store, cfg)
    report = Path(report_path) if report_path else Path(__file__).resolve().parents[1] / "reports" / "P0_synth_history_report.md"
    write_report(results, cfg, report)
    manifest_path = store.archive_dir / "data_manifest_latest.json"
    write_manifest(store.history_dir, manifest_path)
    return results


def build_symbol(symbol: str, spec: Dict[str, Any], store: LocalStore, cfg: Dict[str, Any]) -> SynthBuildResult:
    real_df = _real_only(store.load_history(symbol))
    if real_df.empty:
        raise ValueError(f"{symbol} real history is required before synthetic reconstruction")
    underlying_ret, underlying_name = _underlying_returns(spec, store, cfg)
    if underlying_ret.empty:
        raise ValueError(f"{symbol} underlying returns are empty")
    short_rate = _short_rate_series(store)
    synth_cfg = {
        "start": spec.get("target_start", "2018-01-01"),
        "expense_ratio_annual": float(spec.get("expense_ratio_annual", 0.0)),
        "financing_rate_annual": 0.0,
        "short_rate_series": short_rate,
        "source": f"synth_{spec['leverage']}x_{underlying_name}",
        "underlying": underlying_name,
        "leverage": float(spec["leverage"]),
    }
    combined = reconstruct_leveraged_history(symbol, float(spec["leverage"]), underlying_ret, real_df, synth_cfg)
    _write_history_with_meta(store.history_path(symbol), combined)

    real_start = real_df.index.min().date().isoformat()
    real_end = real_df.index.max().date().isoformat()
    validation_proxy = reconstruct_leveraged_history(
        symbol,
        float(spec["leverage"]),
        underlying_ret,
        real_df,
        {**synth_cfg, "mode": "forward", "start": real_start, "end": real_end},
    )
    validation = validate_synth(real_df, validation_proxy, (real_start, real_end))
    stable_start = real_df.index[min(20, len(real_df.index) - 1)].date().isoformat()
    validation_stable = validate_synth(real_df, validation_proxy, (stable_start, real_end))
    official_validation = _official_3x_validation(symbol, real_df, store, real_start, real_end)

    proxy_mask = combined.get("is_proxy", pd.Series(False, index=combined.index)).astype(str).str.lower().isin({"true", "1", "yes"})
    proxy_dates = combined.index[proxy_mask]
    return SynthBuildResult(
        symbol=symbol,
        leverage=float(spec["leverage"]),
        underlying=underlying_name,
        path=str(store.history_path(symbol)),
        start_date=combined.index.min().date().isoformat(),
        end_date=combined.index.max().date().isoformat(),
        real_start=real_start,
        real_end=real_end,
        rows=int(len(combined)),
        proxy_rows=int(proxy_mask.sum()),
        proxy_start=proxy_dates.min().date().isoformat() if len(proxy_dates) else None,
        proxy_end=proxy_dates.max().date().isoformat() if len(proxy_dates) else None,
        validation=validation,
        validation_stable_skip20=validation_stable,
        official_3x_validation=official_validation,
    )


def write_report(results: Dict[str, SynthBuildResult], cfg: Dict[str, Any], output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = freeze_manifest(resolve_path(cfg, "history_dir"))
    strict_pass = all(result.validation.get("passed") for result in results.values())
    lines = [
        "# P0 Synthetic Leveraged History Report",
        "",
        f"Generated: `{date.today().isoformat()}`",
        f"Data manifest: `{manifest.manifest_id}`",
        f"Strict P0 gate: `{'PASS' if strict_pass else 'NOT PASSED'}`",
        "",
        "## Reconstruction Summary",
        "",
        "| Symbol | Underlying | Leverage | Start | End | Real Start | Proxy Rows | Proxy Range |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for result in results.values():
        proxy_range = f"{result.proxy_start} to {result.proxy_end}" if result.proxy_start else "-"
        lines.append(
            f"| {result.symbol} | {result.underlying} | {result.leverage:.1f}x | {result.start_date} | "
            f"{result.end_date} | {result.real_start} | {result.proxy_rows} | {proxy_range} |"
        )
    lines.extend(
        [
            "",
            "## Strict Overlap Validation",
            "",
            "| Symbol | Overlap | Obs | Return Corr | Annual TE | Max Abs Dev | Corr Gate | TE Gate |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for result in results.values():
        row = result.validation
        lines.append(_validation_row(result.symbol, row))
    lines.extend(
        [
            "",
            "## Stable Window Diagnostic",
            "",
            "This secondary diagnostic skips the first 20 real observations to reveal whether failures are concentrated at the vendor seam. It is diagnostic only and does not override the strict P0 gate.",
            "",
            "| Symbol | Overlap | Obs | Return Corr | Annual TE | Max Abs Dev | Corr Gate | TE Gate |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for result in results.values():
        row = result.validation_stable_skip20
        lines.append(_validation_row(result.symbol, row))
    official_rows = [result for result in results.values() if result.official_3x_validation]
    if official_rows:
        lines.extend(
            [
                "",
                "## Official 3x Index Diagnostic",
                "",
                "FNGU was also compared with the ICE-published NYSE FANG+ Daily 3x Leveraged Index (`FANG3X`) when a local `FANG3X.csv` cache is available. This is diagnostic only; it does not override the strict P0 gate above.",
                "",
                "| Symbol | Overlap | Obs | Return Corr | Annual TE | Max Abs Dev | Corr Gate | TE Gate |",
                "|---|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for result in official_rows:
            lines.append(_validation_row(result.symbol, result.official_3x_validation or {}))
    lines.extend(
        [
            "",
            "## Gate Decision",
            "",
        ]
    )
    if strict_pass:
        lines.append("- P0 is ready for P1 full-window backtest rerun.")
    else:
        lines.append("- P0 code/data plumbing is built, but strict acceptance is not fully passed; do not start P1 calibration yet.")
        lines.append("- FNGU is expected to be the gating item if annual tracking error remains above 5%.")
    lines.extend(
        [
            "",
            "## Provenance Rules",
            "",
            "- Synthetic rows are marked `is_proxy=True` and real rows `is_proxy=False`.",
            "- Synthetic rows use source labels like `synth_3.0x_^NYFANG`.",
            "- The manifest records proxy row counts and proxy date ranges.",
            "- No order placement or live switch was enabled.",
        ]
    )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (output.with_suffix(".json")).write_text(
        json.dumps({key: value.to_dict() for key, value in results.items()}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def _validation_row(symbol: str, row: Dict[str, Any]) -> str:
    overlap = f"{row.get('overlap_start')} to {row.get('overlap_end')}" if row.get("overlap_start") else "-"
    corr = _num(row.get("ret_corr"))
    te = _pct(row.get("tracking_error_annual"))
    dev = _pct(row.get("max_abs_dev"))
    return f"| {symbol} | {overlap} | {row.get('observations')} | {corr} | {te} | {dev} | {row.get('pass_corr')} | {row.get('pass_tracking_error')} |"


def _underlying_returns(spec: Dict[str, Any], store: LocalStore, cfg: Dict[str, Any]) -> tuple[pd.Series, str]:
    preferred = str(spec.get("underlying") or "")
    history = store.load_history(preferred)
    target_start = pd.Timestamp(spec.get("target_start", "2018-01-01"))
    if not history.empty and "Close" in history and history.index.min() <= target_start + pd.Timedelta(days=7):
        return pd.to_numeric(history["Close"], errors="coerce").pct_change().fillna(0.0), preferred

    key = str(spec.get("fallback_components_key") or "")
    components = {
        symbol: store.load_history(symbol)
        for symbol in cfg.get("component_proxies", {}).get(key, [])
    }
    return equal_weight_basket(components), f"equal_weight_{key}_components"


def _short_rate_series(store: LocalStore) -> pd.Series:
    bil = store.load_history("BIL")
    if bil.empty or "Close" not in bil:
        return pd.Series(dtype=float)
    returns = pd.to_numeric(bil["Close"], errors="coerce").pct_change()
    return returns.rolling(21, min_periods=5).mean().mul(252.0).clip(lower=0.0, upper=0.08).fillna(0.0)


def _official_3x_validation(symbol: str, real_df: pd.DataFrame, store: LocalStore, real_start: str, real_end: str) -> Optional[Dict[str, Any]]:
    if symbol != "FNGU":
        return None
    official = _real_only(store.load_history("FANG3X"))
    if official.empty or "Close" not in official:
        return None
    common = real_df.index.intersection(official.index)
    if len(common) < 3:
        return None
    close = pd.to_numeric(official.loc[common, "Close"], errors="coerce").dropna()
    if close.empty:
        return None
    real_close = pd.to_numeric(real_df.loc[common, "Close"], errors="coerce").dropna()
    anchor_common = real_close.index.intersection(close.index)
    if len(anchor_common) < 3:
        return None
    anchor = float(real_close.loc[anchor_common].iloc[0])
    scaled = close.loc[anchor_common] / float(close.loc[anchor_common].iloc[0]) * anchor
    frame = pd.DataFrame(
        {
            "Open": scaled,
            "High": scaled,
            "Low": scaled,
            "Close": scaled,
            "Adj Close": scaled,
            "Volume": 0.0,
        },
        index=scaled.index,
    )
    return validate_synth(real_df, frame, (real_start, real_end))


def _real_only(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "is_proxy" not in frame:
        return frame
    proxy = frame["is_proxy"].astype(str).str.lower().isin({"true", "1", "yes"})
    return frame.loc[~proxy].copy()


def _write_history_with_meta(path: Path, frame: pd.DataFrame) -> None:
    out = frame.copy().sort_index()
    out.index.name = "date"
    out = out.reset_index()
    rename = {
        "Date": "date",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Adj Close": "adj_close",
        "Volume": "volume",
    }
    out = out.rename(columns=rename)
    ordered = [
        "date",
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
        "is_proxy",
        "source",
        "underlying",
        "leverage",
        "expense_ratio_annual",
        "financing_rate_annual",
        "symbol",
    ]
    for column in ordered:
        if column not in out:
            out[column] = None
    path.parent.mkdir(parents=True, exist_ok=True)
    out[ordered].to_csv(path, index=False)


def _num(value: Any) -> str:
    return "NA" if value is None else f"{float(value):.4f}"


def _pct(value: Any) -> str:
    return "NA" if value is None else f"{float(value):.2%}"


if __name__ == "__main__":
    build_all()
