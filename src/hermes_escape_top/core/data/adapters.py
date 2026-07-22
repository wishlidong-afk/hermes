from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, Protocol

from .store import LocalStore


@dataclass(frozen=True)
class SoftDataRecord:
    name: str
    as_of: date
    value: float | None
    source: str
    data_available: bool
    is_proxy: bool = False
    latency_days: int = 0
    quality_penalty: float = 0.0
    reason: str = ""
    fields: Dict[str, float | None] = field(default_factory=dict)
    field_provenance: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["as_of"] = self.as_of.isoformat()
        return payload


class DataSource(Protocol):
    name: str

    def collect(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        ...


@dataclass(frozen=True)
class MissingSource:
    name: str
    feature_flag: str
    missing_reason: str

    def collect(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        enabled = bool(config.get("features", {}).get(self.feature_flag, False))
        reason = self.missing_reason if enabled else f"feature disabled: {self.feature_flag}"
        return SoftDataRecord(
            name=self.name,
            as_of=day,
            value=None,
            source="greenfield_soft_adapter_contract",
            data_available=False,
            quality_penalty=5.0 if enabled else 0.0,
            reason=reason,
        )


def default_sources(config: Dict[str, Any] | None = None) -> list[DataSource]:
    from .breadth import ComponentBreadthSource
    from .crypto import CryptoFundingSource
    from .macro import CboeIndicesSource, FredNetLiquiditySource
    from .pcr import PutCallSource
    from .sentiment import AaiiSource, CnnFearGreedSource, NaaimSource

    sources: list[DataSource] = [
        MissingSource("gex", "data_gex", "GEX source credentials/API not configured"),
        CboeIndicesSource(),
        FredNetLiquiditySource(),
        AaiiSource(),
        NaaimSource(),
        PutCallSource(),
        ComponentBreadthSource(),
        CryptoFundingSource(),
    ]
    # Flag-gated Tier-1/2 risk sources: appended only when their flag is ON, so
    # an all-OFF config yields exactly the list above (byte-identical).
    from .risk_signals import risk_sources
    sources.extend(risk_sources(config))
    # CNN Fear & Greed (A2): appended only when data_cnn_fgi is ON → byte-identical off.
    if config and bool(config.get("features", {}).get("data_cnn_fgi", False)):
        sources.append(CnnFearGreedSource())
    return sources


def _valuation_record(as_of: str, config: Dict[str, Any], store: LocalStore) -> Dict[str, Any]:
    """B6 valuation percentile per trade symbol, from valuation_snapshot.json.

    Maps each trade symbol to its valuation proxy percentile (FNGU→FNGS forward PE,
    SOXL→SOXX forward PE, MSTR→mNAV premium), exposed as SOFT fields
    `<SYM>_valuation_pctl` to match the v25 monolith's B6 input. Absent → no field
    (B6 then scores 0 via the registry's missing handling).
    """
    import json as _json
    sym_map = {
        "FNGU": ("FNGS", ["forward_pe_percentile", "pe_percentile", "valuation_percentile"]),
        "SOXL": ("SOXX", ["forward_pe_percentile", "pe_percentile", "valuation_percentile"]),
        "MSTR": ("MSTR", ["mnav_premium_percentile", "premium_percentile", "valuation_percentile"]),
    }
    candidates = []
    cfg_path = config.get("valuation", {}).get("snapshot_path")
    if cfg_path:
        candidates.append(Path(cfg_path))
    try:
        candidates.append(Path(store.archive_dir).parent / "valuation_snapshot.json")
    except Exception:
        pass
    base = Path(__file__).resolve().parents[2]  # escape-top/ skill root
    candidates.append(base / "data" / "valuation_snapshot.json")
    candidates.append(base.parent / "data" / "valuation_snapshot.json")

    snapshot = None
    src_path = None
    for c in candidates:
        try:
            if c and c.exists():
                snapshot = _json.loads(c.read_text(encoding="utf-8"))
                src_path = str(c)
                break
        except Exception:
            continue

    fields: Dict[str, float | None] = {}
    if snapshot:
        items = snapshot.get("items") or snapshot.get("symbols") or {}
        for sym, (key, pctl_fields) in sym_map.items():
            item = items.get(key, {})
            if not isinstance(item, dict):
                continue
            for pf in pctl_fields:
                v = item.get(pf)
                if isinstance(v, (int, float)):
                    fields[f"{sym}_valuation_pctl"] = float(v)
                    break

    return {
        "value": None,
        "source": src_path or "valuation_snapshot:absent",
        "as_of": str(as_of)[:10],
        "data_available": bool(fields),
        "is_proxy": True,
        "fields": fields,
        "reason": "B6 valuation percentile per symbol",
    }


def apply_soft_data_slo(records: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    """[T9] Degrade over-age soft records to missing (stale data != fresh data).

    Gated by features.use_soft_data_max_age (default OFF => no-op). Ages are
    latency_days (calendar); thresholds in config.soft_data_slo are sized
    long-weekend-safe so this is a coarse safety net — precise trading-day
    alerting lives in the watchdog/preflight, not here.
    """
    features = config.get("features") or {}
    if not features.get("use_soft_data_max_age"):
        return records
    slo = config.get("soft_data_slo") or {}
    default_max = int(slo.get("default_max_age_days", 13))
    per_source = slo.get("max_age_days") or {}
    for name, rec in records.items():
        if not isinstance(rec, dict) or not rec.get("data_available"):
            continue
        max_age = int(per_source.get(name, default_max))
        latency = int(rec.get("latency_days") or 0)
        if latency > max_age:
            rec["value"] = None
            rec["data_available"] = False
            rec["fields"] = {key: None for key in (rec.get("fields") or {})}
            rec["reason"] = (f"stale: latency {latency}d > max_age {max_age}d; "
                             + (rec.get("reason") or "")).rstrip("; ")
    return records


def build_soft_data(as_of: str, config: Dict[str, Any], store: LocalStore) -> Dict[str, Any]:
    """Build the deterministic soft payload without mutating persistence."""
    records = {source.name: source.collect(as_of, config).to_dict() for source in default_sources(config)}
    records["valuation"] = _valuation_record(as_of, config, store)
    records = apply_soft_data_slo(records, config)
    path = store.archive_path("soft_adapter_snapshot", str(as_of)[:10])
    return {"as_of": str(as_of)[:10], "path": str(path), "records": records}


def persist_soft_data_snapshot(payload: Dict[str, Any], store: LocalStore) -> Path:
    """Persist a previously built soft payload at its deterministic dated path."""
    as_of = str(payload.get("as_of") or "")[:10]
    if not as_of:
        raise ValueError("soft data as_of is required")
    return store.write_dated_snapshot(
        "soft_adapter_snapshot",
        as_of,
        {
            "schema_version": "escape-top-greenfield-soft-adapter-v1",
            "as_of": as_of,
            "records": payload.get("records") or {},
        },
    )


def collect_soft_data(as_of: str, config: Dict[str, Any], store: LocalStore) -> Dict[str, Any]:
    """Compatibility interface for explicit snapshot/archive commands."""
    payload = build_soft_data(as_of, config, store)
    persist_soft_data_snapshot(payload, store)
    return payload
