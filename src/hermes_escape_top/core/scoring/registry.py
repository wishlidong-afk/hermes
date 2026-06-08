from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

from ..data.base import SymbolSnapshot
from .explain_registry import explain_factor


ScoreFn = Callable[["FactorContext"], tuple[float, str]]


@dataclass(frozen=True)
class FactorDefinition:
    factor_id: str
    module: str
    max_score: float
    dependencies: List[str]
    score_fn: ScoreFn
    missing_name: Optional[str] = None
    # When True, the factor is evaluated as long as *some* dependency is present
    # (the score_fn must tolerate None for absent ones). Used for multi-component
    # factors so one missing constituent doesn't silently zero the whole signal.
    # Only takes effect when features.use_partial_factor_eval is on.
    partial_ok: bool = False


@dataclass(frozen=True)
class FactorScore:
    factor_id: str
    module: str
    score: float
    max_score: float
    missing_fields: List[str] = field(default_factory=list)
    explain: str = ""

    @property
    def active(self) -> bool:
        return self.score > 0 or bool(self.missing_fields)

    def to_dict(self) -> Dict[str, object]:
        explain_meta = explain_factor(self.factor_id, self.module)
        return {
            "factor_id": self.factor_id,
            "module": self.module,
            "score": round(float(self.score), 4),
            "max_score": round(float(self.max_score), 4),
            "missing_fields": self.missing_fields,
            "explain": self.explain,
            **explain_meta,
        }


@dataclass
class FactorContext:
    symbol: str
    snapshots: Dict[str, SymbolSnapshot]
    config: Optional[Dict[str, Any]] = None

    @property
    def snapshot(self) -> SymbolSnapshot:
        return self.snapshots[self.symbol]

    @property
    def as_of(self):
        return self.snapshot.as_of

    def get(self, dependency: str) -> Optional[float]:
        snap, field_name = self._resolve(dependency)
        if snap is None:
            return None
        return snap.get(field_name)

    def missing(self, dependency: str) -> bool:
        snap, field_name = self._resolve(dependency)
        if snap is None:
            return True
        return snap.is_missing(field_name)

    def _resolve(self, dependency: str) -> tuple[Optional[SymbolSnapshot], str]:
        for symbol in sorted(self.snapshots, key=len, reverse=True):
            prefix = f"{symbol}."
            if dependency.startswith(prefix):
                return self.snapshots[symbol], dependency[len(prefix) :]
        return self.snapshot, dependency


class FactorRegistry:
    def __init__(self, factors: Iterable[FactorDefinition]) -> None:
        self.factors = list(factors)

    def evaluate(self, context: FactorContext) -> List[FactorScore]:
        results: List[FactorScore] = []
        partial_enabled = bool((context.config or {}).get("features", {}).get("use_partial_factor_eval", False))
        for factor in self.factors:
            missing = [dep for dep in factor.dependencies if context.missing(dep)]
            all_missing = len(missing) == len(factor.dependencies)
            use_partial = partial_enabled and factor.partial_ok and not all_missing
            if missing and not use_partial:
                missing_name = factor.missing_name
                missing_fields = [missing_name] if missing_name else missing
                results.append(
                    FactorScore(
                        factor_id=factor.factor_id,
                        module=factor.module,
                        score=0.0,
                        max_score=factor.max_score,
                        missing_fields=missing_fields,
                        explain=f"{factor.factor_id}: missing {', '.join(missing_fields)}",
                    )
                )
                continue
            score, explain = factor.score_fn(context)
            score = max(0.0, min(float(factor.max_score), float(score)))
            results.append(
                FactorScore(
                    factor_id=factor.factor_id,
                    module=factor.module,
                    score=score,
                    max_score=factor.max_score,
                    explain=explain,
                )
            )
        return results


def missing_only(factor_id: str, module: str, missing_name: str) -> FactorDefinition:
    return FactorDefinition(
        factor_id=factor_id,
        module=module,
        max_score=0.0,
        dependencies=[missing_name],
        missing_name=missing_name,
        score_fn=lambda _ctx: (0.0, f"{factor_id}: unavailable soft-data placeholder"),
    )
