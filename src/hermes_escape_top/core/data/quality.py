from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List

from .base import SymbolSnapshot


@dataclass
class MissingAnalysis:
    missing_fields: List[str]
    missing_weight: float
    effective_max_score: float
    adjusted_score: float
    blind_spot: bool
    critical_missing: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "missing_fields": self.missing_fields,
            "missing_weight": round(self.missing_weight, 2),
            "effective_max_score": round(self.effective_max_score, 2),
            "adjusted_score": round(self.adjusted_score, 2),
            "blind_spot": self.blind_spot,
            "critical_missing": self.critical_missing,
        }


@dataclass
class DataQuality:
    completeness_score: float
    quality_score: float
    latency_score: float
    overall_score: float
    penalties: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def level(self) -> str:
        score = self.overall_score
        if score >= 85:
            return "HIGH"
        if score >= 70:
            return "MEDIUM"
        if score >= 50:
            return "LOW"
        return "BLOCKED"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "completeness_score": round(self.completeness_score, 2),
            "quality_score": round(self.quality_score, 2),
            "latency_score": round(self.latency_score, 2),
            "overall_score": round(self.overall_score, 2),
            "level": self.level,
            "penalties": self.penalties,
        }


def missing_field_weight(field_name: str, weights: Dict[str, float]) -> float:
    for pattern, weight in weights.items():
        if pattern == field_name or field_name.startswith(pattern) or pattern in field_name:
            return float(weight)
    return 1.0


def analyze_missing_fields(missing_fields: Iterable[str], raw_score: float, config: Dict[str, Any]) -> MissingAnalysis:
    missing_cfg = config.get("missing", {})
    weights = missing_cfg.get("weights", {})
    critical_names = set(missing_cfg.get("critical_fields", ["history", "close", "ma200"]))
    unique = sorted(set(missing_fields))
    counted: set[str] = set()
    missing_weight = 0.0
    for name in unique:
        key = "A5" if name.startswith("A5") else name
        if key in counted:
            continue
        counted.add(key)
        missing_weight += missing_field_weight(name, weights)
    missing_weight = min(100.0, missing_weight)
    effective_max = max(0.0, 100.0 - missing_weight)
    critical = any(name in critical_names or name.split(".", 1)[-1] in critical_names for name in unique)
    adjusted = 100.0 if critical or effective_max <= 0 else min(100.0, raw_score / effective_max * 100.0)
    blind_threshold = float(missing_cfg.get("blind_spot_threshold", 30))
    return MissingAnalysis(
        missing_fields=unique,
        missing_weight=missing_weight,
        effective_max_score=effective_max,
        adjusted_score=adjusted,
        blind_spot=missing_weight > blind_threshold,
        critical_missing=critical,
    )


def quality_from_snapshots(snapshots: Iterable[SymbolSnapshot]) -> DataQuality:
    penalties: List[Dict[str, Any]] = []
    critical_missing = []
    completeness = 100.0
    quality = 100.0
    latency = 100.0
    proxy_groups: Dict[tuple, Dict[str, Any]] = {}
    latency_groups: Dict[tuple, Dict[str, Any]] = {}
    for snap in snapshots:
        for name, item in snap.fields.items():
            if item.missing and name in {"close", "ma200"}:
                critical_missing.append(f"{snap.symbol}.{name}")
            if item.is_proxy:
                penalty = item.quality_penalty or 2.0
                key = (snap.symbol, item.source, "proxy")
                _merge_penalty_group(proxy_groups, key, f"{snap.symbol}.{name}", penalty)
            if item.latency_days > 0:
                penalty = _latency_penalty(name, item)
                if penalty <= 0:
                    continue
                key = (snap.symbol, item.source, "latency", item.latency_days)
                _merge_penalty_group(latency_groups, key, f"{snap.symbol}.{name}", penalty)
    for group in proxy_groups.values():
        quality -= float(group["penalty"])
        penalties.append({"field": ",".join(group["fields"]), "reason": "proxy", "penalty": group["penalty"]})
    for group in latency_groups.values():
        latency -= float(group["penalty"])
        penalties.append({"field": ",".join(group["fields"]), "reason": "latency", "penalty": group["penalty"]})
    if critical_missing:
        completeness = 35.0
        penalties.append({"field": ",".join(critical_missing), "reason": "critical_missing", "penalty": 65.0})
    completeness = max(0.0, min(100.0, completeness))
    quality = max(0.0, min(100.0, quality))
    latency = max(0.0, min(100.0, latency))
    overall = min(completeness, quality, latency) if critical_missing else completeness * 0.50 + quality * 0.30 + latency * 0.20
    return DataQuality(completeness, quality, latency, overall, penalties)


def _merge_penalty_group(groups: Dict[tuple, Dict[str, Any]], key: tuple, field: str, penalty: float) -> None:
    current = groups.setdefault(key, {"fields": [], "penalty": 0.0})
    current["fields"].append(field)
    current["penalty"] = max(float(current["penalty"]), float(penalty))


def _latency_penalty(field_name: str, item: Any) -> float:
    grace_days = _latency_grace_days(field_name, item)
    adjusted_days = max(0, int(item.latency_days or 0) - grace_days)
    return min(20.0, adjusted_days * 3.0)


def _latency_grace_days(field_name: str, item: Any) -> int:
    source = str(getattr(item, "source", "") or "").upper()
    name = str(field_name or "").lower()
    if source in {"FRED", "NAAIM", "AAII"}:
        # These are weekly or naturally publication-lagged inputs. A value can be
        # point-in-time correct and decision-grade even when it is several days old.
        return 7
    if "PCR" in source:
        return 2
    if source in {"BTC_FUNDING_PROXY", "DERIBIT", "OKX_FAILOVER"} or name.startswith("btc_"):
        return 2
    if source == "LOCAL_COMPONENT_HISTORY":
        return 2
    return 0
