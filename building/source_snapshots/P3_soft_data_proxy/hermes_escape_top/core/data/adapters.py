from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
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


def default_sources() -> list[DataSource]:
    from .breadth import ComponentBreadthSource
    from .crypto import CryptoFundingSource
    from .macro import CboeIndicesSource, FredNetLiquiditySource
    from .pcr import PutCallSource
    from .sentiment import AaiiSource, NaaimSource

    return [
        MissingSource("gex", "data_gex", "GEX source credentials/API not configured"),
        CboeIndicesSource(),
        FredNetLiquiditySource(),
        AaiiSource(),
        NaaimSource(),
        PutCallSource(),
        ComponentBreadthSource(),
        CryptoFundingSource(),
    ]


def collect_soft_data(as_of: str, config: Dict[str, Any], store: LocalStore) -> Dict[str, Any]:
    records = {source.name: source.collect(as_of, config).to_dict() for source in default_sources()}
    path = store.write_dated_snapshot(
        "soft_adapter_snapshot",
        as_of,
        {
            "schema_version": "escape-top-greenfield-soft-adapter-v1",
            "as_of": str(as_of)[:10],
            "records": records,
        },
    )
    return {"as_of": str(as_of)[:10], "path": str(path), "records": records}
