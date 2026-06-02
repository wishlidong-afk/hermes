"""E30 Data Source Failover -- ordered source list with health check and auto-switch.

Provides FailoverSource that wraps multiple data sources with priority ordering,
health checking, automatic fallback, and degradation annotation.

All downstream consumers see a single interface; degradation state feeds into
ConfidenceSpine as failover_state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import pandas as pd


@dataclass
class SourceHealth:
    name: str
    rank: int  # 1 = primary, 2 = first backup, etc.
    is_healthy: bool
    last_check: Optional[str] = None
    error: Optional[str] = None


@dataclass
class FailoverResult:
    data: Optional[pd.DataFrame]
    active_source: str
    active_rank: int
    is_degraded: bool
    tried: List[SourceHealth]
    notes: List[str]


class FailoverSource:
    """Ordered data source with health check and auto-failover.

    Usage:
        fs = FailoverSource("MSTR_price", [
            SourceSpec("yfinance", fetch_fn=yf_fetch, health_fn=yf_health),
            SourceSpec("local_csv", fetch_fn=csv_fetch, health_fn=csv_health),
        ])
        result = fs.fetch(as_of="2026-06-01")
        # result.is_degraded feeds into ConfidenceSpine
    """

    def __init__(self, name: str, sources: List["SourceSpec"]):
        self._name = name
        self._sources = sources

    def fetch(self, as_of: str, **kwargs: Any) -> FailoverResult:
        """Try sources in priority order; return first successful result."""
        tried: List[SourceHealth] = []
        notes: List[str] = []

        for rank, spec in enumerate(self._sources, 1):
            health = self._check_health(spec, rank)
            tried.append(health)

            if not health.is_healthy:
                notes.append(f"{spec.name} unhealthy: {health.error}")
                continue

            try:
                data = spec.fetch_fn(as_of=as_of, **kwargs)
                if data is not None and not data.empty:
                    is_degraded = rank > 1
                    if is_degraded:
                        notes.append(f"degraded to {spec.name} (rank {rank})")
                    return FailoverResult(
                        data=data,
                        active_source=spec.name,
                        active_rank=rank,
                        is_degraded=is_degraded,
                        tried=tried,
                        notes=notes,
                    )
                else:
                    notes.append(f"{spec.name} returned empty data")
            except Exception as e:
                notes.append(f"{spec.name} fetch error: {str(e)[:100]}")
                tried[-1] = SourceHealth(
                    name=spec.name, rank=rank, is_healthy=False, error=str(e)[:100],
                )

        notes.append("all sources exhausted; no data available")
        return FailoverResult(
            data=None,
            active_source="NONE",
            active_rank=0,
            is_degraded=True,
            tried=tried,
            notes=notes,
        )

    def _check_health(self, spec: "SourceSpec", rank: int) -> SourceHealth:
        if spec.health_fn is None:
            return SourceHealth(name=spec.name, rank=rank, is_healthy=True)
        try:
            healthy = spec.health_fn()
            return SourceHealth(name=spec.name, rank=rank, is_healthy=bool(healthy))
        except Exception as e:
            return SourceHealth(
                name=spec.name, rank=rank, is_healthy=False, error=str(e)[:100],
            )

    def to_confidence_input(self, result: FailoverResult) -> Dict[str, Any]:
        """Convert FailoverResult to ConfidenceSpine failover_state input."""
        return {
            "is_degraded": result.is_degraded,
            "active_source_rank": result.active_rank,
            "active_source": result.active_source,
        }


@dataclass
class SourceSpec:
    name: str
    fetch_fn: Callable
    health_fn: Optional[Callable] = None
