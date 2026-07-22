"""Pre-registered IS-selection/OOS validation gate.

This module evaluates already-produced equity curves. It never runs a backtest
and never changes production configuration. The candidate universe and all
thresholds come from a sealed experiment manifest rather than CLI arguments.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from hermes_escape_top.core.backtest.harness import prob_backtest_overfitting
from hermes_escape_top.core.backtest.metrics import compute_metrics
from hermes_escape_top.core.backtest.validation import deflated_sharpe


MANIFEST_SCHEMA = "hermes-formal-gate-v1"
MANIFEST_SCHEMA_V2 = "hermes-formal-gate-v2"
MANIFEST_SCHEMA_V3 = "hermes-formal-gate-v3"
RESULT_SCHEMA = "hermes-formal-gate-result-v1"
MIN_GATE_FOLDS = 8
MAX_PBO_THRESHOLD = 0.5
MAX_DRAWDOWN_TOLERANCE = 0.01
MIN_OOS_DELTA = 0.0
MIN_DSR = 0.0
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_TOP_LEVEL_FIELDS = {
    "schema",
    "experiment_id",
    "created_at",
    "hypothesis",
    "artifacts_dir",
    "baseline",
    "target",
    "candidates",
    "declared_trial_count",
    "walk_forward",
    "cpcv",
    "thresholds",
}
_TOP_LEVEL_FIELDS_V2 = _TOP_LEVEL_FIELDS | {"governance_lane"}
_TOP_LEVEL_FIELDS_V3 = _TOP_LEVEL_FIELDS_V2 | {"turnover_objective"}
_GOVERNANCE_LANES = {"alpha_experiment", "data_correctness_migration"}
_WALK_FORWARD_FIELDS = {
    "is_years",
    "oos_months",
    "step_months",
    "label_horizon",
    "embargo_pct",
}
_CPCV_FIELDS = {"n_groups", "n_test", "label_horizon", "embargo_pct"}
_THRESHOLD_FIELDS = {"pbo_max", "min_oos_delta", "maxdd_tolerance", "min_dsr"}
_TURNOVER_OBJECTIVE_FIELDS = {"metric", "max_delta_vs_baseline"}
_TURNOVER_METRICS = {"total_turnover", "route_set_turnover"}


class FormalGateError(ValueError):
    pass


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _require_exact_fields(name: str, value: Mapping[str, Any], expected: set[str]) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        raise FormalGateError(f"{name} fields invalid: missing={missing}, unknown={unknown}")


def _positive_int(name: str, value: Any, *, allow_zero: bool = False) -> int:
    if type(value) is not int or value < (0 if allow_zero else 1):
        comparator = ">= 0" if allow_zero else "> 0"
        raise FormalGateError(f"{name} must be an integer {comparator}")
    return int(value)


def _finite_float(name: str, value: Any) -> float:
    if isinstance(value, bool):
        raise FormalGateError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise FormalGateError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise FormalGateError(f"{name} must be a finite number")
    return result


@dataclass(frozen=True)
class ExperimentManifest:
    schema: str
    experiment_id: str
    created_at: str
    hypothesis: str
    artifacts_dir: str
    baseline: str
    target: str
    candidates: tuple[str, ...]
    declared_trial_count: int
    walk_forward: Mapping[str, Any]
    cpcv: Mapping[str, Any]
    thresholds: Mapping[str, float]
    governance_lane: str
    turnover_objective: Mapping[str, Any] | None
    manifest_sha256: str

    @property
    def variants(self) -> tuple[str, ...]:
        return (self.baseline, *self.candidates)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ExperimentManifest":
        if not isinstance(raw, Mapping):
            raise FormalGateError("manifest must be an object")
        schema = str(raw.get("schema") or "")
        if schema == MANIFEST_SCHEMA:
            _require_exact_fields("manifest", raw, _TOP_LEVEL_FIELDS)
            governance_lane = "alpha_experiment"
        elif schema in {MANIFEST_SCHEMA_V2, MANIFEST_SCHEMA_V3}:
            fields = _TOP_LEVEL_FIELDS_V3 if schema == MANIFEST_SCHEMA_V3 else _TOP_LEVEL_FIELDS_V2
            _require_exact_fields("manifest", raw, fields)
            governance_lane = str(raw["governance_lane"])
            if governance_lane not in _GOVERNANCE_LANES:
                raise FormalGateError(
                    "governance_lane must be alpha_experiment or data_correctness_migration"
                )
        else:
            raise FormalGateError(
                f"schema must be {MANIFEST_SCHEMA}, {MANIFEST_SCHEMA_V2}, or {MANIFEST_SCHEMA_V3}"
            )

        experiment_id = str(raw["experiment_id"])
        if not _NAME_RE.fullmatch(experiment_id):
            raise FormalGateError("experiment_id contains unsupported characters")
        try:
            date.fromisoformat(str(raw["created_at"]))
        except ValueError as exc:
            raise FormalGateError("created_at must be YYYY-MM-DD") from exc
        hypothesis = str(raw["hypothesis"]).strip()
        if not hypothesis:
            raise FormalGateError("hypothesis must not be empty")

        artifacts_dir = str(raw["artifacts_dir"])
        artifact_path = PurePosixPath(artifacts_dir)
        if artifact_path.is_absolute() or ".." in artifact_path.parts:
            raise FormalGateError("artifacts_dir must be a repo-relative path")

        baseline = str(raw["baseline"])
        target = str(raw["target"])
        candidates_raw = raw["candidates"]
        if not isinstance(candidates_raw, list) or not candidates_raw:
            raise FormalGateError("candidates must be a non-empty list")
        candidates = tuple(str(value) for value in candidates_raw)
        if len(set(candidates)) != len(candidates):
            raise FormalGateError("candidates must be unique")
        if baseline in candidates:
            raise FormalGateError("baseline must not be listed as a candidate")
        if target not in candidates:
            raise FormalGateError("target must be listed in candidates")
        for variant in (baseline, *candidates):
            if not _NAME_RE.fullmatch(variant):
                raise FormalGateError(f"invalid variant name: {variant}")

        declared_trial_count = _positive_int("declared_trial_count", raw["declared_trial_count"])
        if declared_trial_count < 1 + len(candidates):
            raise FormalGateError("declared_trial_count must include baseline and every candidate")

        walk_forward = raw["walk_forward"]
        cpcv = raw["cpcv"]
        thresholds = raw["thresholds"]
        if not all(isinstance(value, Mapping) for value in (walk_forward, cpcv, thresholds)):
            raise FormalGateError("walk_forward, cpcv, and thresholds must be objects")
        _require_exact_fields("walk_forward", walk_forward, _WALK_FORWARD_FIELDS)
        _require_exact_fields("cpcv", cpcv, _CPCV_FIELDS)
        _require_exact_fields("thresholds", thresholds, _THRESHOLD_FIELDS)

        normalized_walk = {
            "is_years": _positive_int("walk_forward.is_years", walk_forward["is_years"]),
            "oos_months": _positive_int("walk_forward.oos_months", walk_forward["oos_months"]),
            "step_months": _positive_int("walk_forward.step_months", walk_forward["step_months"]),
            "label_horizon": _positive_int(
                "walk_forward.label_horizon", walk_forward["label_horizon"], allow_zero=True
            ),
            "embargo_pct": _finite_float("walk_forward.embargo_pct", walk_forward["embargo_pct"]),
        }
        normalized_cpcv = {
            "n_groups": _positive_int("cpcv.n_groups", cpcv["n_groups"]),
            "n_test": _positive_int("cpcv.n_test", cpcv["n_test"]),
            "label_horizon": _positive_int("cpcv.label_horizon", cpcv["label_horizon"], allow_zero=True),
            "embargo_pct": _finite_float("cpcv.embargo_pct", cpcv["embargo_pct"]),
        }
        if normalized_cpcv["n_groups"] < 2 or normalized_cpcv["n_test"] >= normalized_cpcv["n_groups"]:
            raise FormalGateError("cpcv requires n_groups >= 2 and n_test < n_groups")
        if (
            not 0.0 <= normalized_walk["embargo_pct"] < 0.5
            or not 0.0 <= normalized_cpcv["embargo_pct"] < 0.5
        ):
            raise FormalGateError("embargo_pct must be in [0, 0.5)")
        if (
            normalized_walk["is_years"] < 2
            or normalized_walk["oos_months"] < 6
            or normalized_walk["step_months"] > normalized_walk["oos_months"]
            or normalized_walk["label_horizon"] < 20
            or normalized_walk["embargo_pct"] < 0.02
        ):
            raise FormalGateError("walk_forward policy requires IS>=2y, OOS>=6m, step<=OOS, horizon>=20, embargo>=2%")
        if (
            normalized_cpcv["n_groups"] < 6
            or normalized_cpcv["n_test"] < 2
            or normalized_cpcv["label_horizon"] < 20
            or normalized_cpcv["embargo_pct"] < 0.02
        ):
            raise FormalGateError("cpcv policy requires groups>=6, test groups>=2, horizon>=20, embargo>=2%")

        normalized_thresholds = {
            key: _finite_float(f"thresholds.{key}", thresholds[key]) for key in _THRESHOLD_FIELDS
        }
        if not 0.0 < normalized_thresholds["pbo_max"] <= MAX_PBO_THRESHOLD:
            raise FormalGateError(f"thresholds.pbo_max must be in (0, {MAX_PBO_THRESHOLD}]")
        if normalized_thresholds["maxdd_tolerance"] < 0.0:
            raise FormalGateError("thresholds.maxdd_tolerance must be >= 0")
        if (
            normalized_thresholds["min_oos_delta"] < MIN_OOS_DELTA
            or normalized_thresholds["maxdd_tolerance"] > MAX_DRAWDOWN_TOLERANCE
            or normalized_thresholds["min_dsr"] < MIN_DSR
        ):
            raise FormalGateError("gate thresholds cannot be weaker than policy")

        turnover_objective = None
        if schema == MANIFEST_SCHEMA_V3:
            raw_turnover = raw["turnover_objective"]
            if not isinstance(raw_turnover, Mapping):
                raise FormalGateError("turnover_objective must be an object")
            _require_exact_fields(
                "turnover_objective",
                raw_turnover,
                _TURNOVER_OBJECTIVE_FIELDS,
            )
            metric = str(raw_turnover["metric"])
            if metric not in _TURNOVER_METRICS:
                raise FormalGateError(
                    "turnover_objective.metric must be total_turnover or route_set_turnover"
                )
            max_delta = _finite_float(
                "turnover_objective.max_delta_vs_baseline",
                raw_turnover["max_delta_vs_baseline"],
            )
            if max_delta >= 0.0:
                raise FormalGateError(
                    "turnover_objective.max_delta_vs_baseline must be strictly negative"
                )
            turnover_objective = {
                "metric": metric,
                "max_delta_vs_baseline": max_delta,
            }

        normalized = {
            "schema": schema,
            "experiment_id": experiment_id,
            "created_at": str(raw["created_at"]),
            "hypothesis": hypothesis,
            "artifacts_dir": artifacts_dir,
            "baseline": baseline,
            "target": target,
            "candidates": list(candidates),
            "declared_trial_count": declared_trial_count,
            "walk_forward": normalized_walk,
            "cpcv": normalized_cpcv,
            "thresholds": normalized_thresholds,
        }
        if schema in {MANIFEST_SCHEMA_V2, MANIFEST_SCHEMA_V3}:
            normalized["governance_lane"] = governance_lane
        if turnover_objective is not None:
            normalized["turnover_objective"] = turnover_objective
        return cls(
            schema=schema,
            experiment_id=experiment_id,
            created_at=str(raw["created_at"]),
            hypothesis=hypothesis,
            artifacts_dir=artifacts_dir,
            baseline=baseline,
            target=target,
            candidates=candidates,
            declared_trial_count=declared_trial_count,
            walk_forward=normalized_walk,
            cpcv=normalized_cpcv,
            thresholds=normalized_thresholds,
            governance_lane=governance_lane,
            turnover_objective=turnover_objective,
            manifest_sha256=_canonical_hash(normalized),
        )


@dataclass(frozen=True)
class PerformanceMatrix:
    variants: tuple[str, ...]
    is_perf: np.ndarray
    oos_perf: np.ndarray


def _split_indices(split: Any) -> tuple[np.ndarray, np.ndarray]:
    if hasattr(split, "train_idx") and hasattr(split, "test_idx"):
        return np.asarray(split.train_idx, dtype=int), np.asarray(split.test_idx, dtype=int)
    if isinstance(split, tuple) and len(split) == 2:
        return np.asarray(split[0], dtype=int), np.asarray(split[1], dtype=int)
    raise FormalGateError("split must provide train_idx/test_idx or be a pair of arrays")


def _objective_from_metrics(metrics: Mapping[str, Any]) -> float:
    cagr = float(metrics.get("cagr") or 0.0)
    max_dd = abs(float(metrics.get("max_drawdown") or 0.0))
    calmar = float(metrics.get("calmar") or (cagr / max(max_dd, 1e-9)))
    sharpe = float(metrics.get("sharpe") or 0.0)
    dd_penalty = max(0.0, max_dd - 0.30) * 2.0
    return 0.50 * calmar + 0.25 * sharpe + 0.25 * cagr - dd_penalty


def split_objective(equity: pd.Series, indices: np.ndarray) -> float:
    n_obs = len(equity)
    selected = np.zeros(n_obs, dtype=bool)
    unique = np.unique(indices)
    if len(unique) == 0 or unique[0] < 0 or unique[-1] >= n_obs:
        raise FormalGateError("split index outside equity range")
    selected[unique] = True
    valid_return = selected & np.r_[False, selected[:-1]]
    returns = pd.to_numeric(equity, errors="coerce").pct_change(fill_method=None).to_numpy(dtype=float)
    segment_returns = returns[valid_return]
    segment_returns = segment_returns[np.isfinite(segment_returns)]
    if len(segment_returns) < 3:
        raise FormalGateError("split has fewer than three contiguous returns")
    segment_equity = pd.Series(np.r_[1.0, np.cumprod(1.0 + segment_returns)])
    return _objective_from_metrics(compute_metrics(segment_equity))


def _performance_matrix(
    variants: tuple[str, ...],
    equities: Mapping[str, pd.Series],
    splits: Sequence[Any],
) -> PerformanceMatrix:
    if len(splits) < 2:
        raise FormalGateError("formal PBO requires at least two folds")
    is_perf = np.empty((len(variants), len(splits)), dtype=float)
    oos_perf = np.empty_like(is_perf)
    for fold_idx, split in enumerate(splits):
        train_idx, test_idx = _split_indices(split)
        for variant_idx, variant in enumerate(variants):
            is_perf[variant_idx, fold_idx] = split_objective(equities[variant], train_idx)
            oos_perf[variant_idx, fold_idx] = split_objective(equities[variant], test_idx)
    if not np.isfinite(is_perf).all() or not np.isfinite(oos_perf).all():
        raise FormalGateError("non-finite objective in performance matrix")
    return PerformanceMatrix(variants, is_perf, oos_perf)


def _rank_percentile(values: np.ndarray, selected_idx: int) -> float:
    if len(values) <= 1:
        return 1.0
    chosen = float(values[selected_idx])
    return float((np.sum(values <= chosen) - 1) / (len(values) - 1))


def selection_evidence(matrix: PerformanceMatrix) -> dict[str, Any]:
    if matrix.is_perf.ndim != 2 or matrix.oos_perf.ndim != 2:
        raise FormalGateError("performance matrices must be two-dimensional")
    if matrix.is_perf.shape != matrix.oos_perf.shape:
        raise FormalGateError("IS and OOS matrices must have the same shape")
    if matrix.is_perf.shape[0] != len(matrix.variants):
        raise FormalGateError("matrix rows must match variants")
    if matrix.is_perf.shape[0] < 2 or matrix.is_perf.shape[1] < 2:
        raise FormalGateError("formal PBO requires at least two variants and two folds")
    if not np.isfinite(matrix.is_perf).all() or not np.isfinite(matrix.oos_perf).all():
        raise FormalGateError("performance matrices must be finite")

    pbo = prob_backtest_overfitting(matrix.is_perf, matrix.oos_perf)
    folds: list[dict[str, Any]] = []
    for fold_idx in range(matrix.is_perf.shape[1]):
        train_values = matrix.is_perf[:, fold_idx]
        test_values = matrix.oos_perf[:, fold_idx]
        selected_idx = int(np.argmax(train_values))
        selected_oos = float(test_values[selected_idx])
        median_oos = float(np.median(test_values))
        folds.append(
            {
                "fold": fold_idx + 1,
                "selected_variant": matrix.variants[selected_idx],
                "selected_is_objective": float(train_values[selected_idx]),
                "selected_oos_objective": selected_oos,
                "oos_median_objective": median_oos,
                "oos_rank_percentile": _rank_percentile(test_values, selected_idx),
                "overfit_event": selected_oos < median_oos,
                "is_tie_count": int(np.sum(np.isclose(train_values, train_values[selected_idx]))),
            }
        )
    medians = {
        variant: float(np.median(matrix.oos_perf[idx])) for idx, variant in enumerate(matrix.variants)
    }
    return {"pbo": float(pbo), "n_folds": len(folds), "folds": folds, "median_oos": medians}


def _blocked_result(
    manifest: ExperimentManifest,
    artifact_statuses: Mapping[str, Mapping[str, Any]],
    blocked_variants: list[str],
) -> dict[str, Any]:
    return {
        "schema": RESULT_SCHEMA,
        "experiment_id": manifest.experiment_id,
        "governance_lane": manifest.governance_lane,
        "manifest_sha256": manifest.manifest_sha256,
        "variants": list(manifest.variants),
        "target_variant": manifest.target,
        "artifact_statuses": dict(artifact_statuses),
        "blocked_variants": blocked_variants,
        "verdict": "BLOCKED",
        "authorization": "NO_FLIP",
    }


def evaluate_formal_gate(
    manifest: ExperimentManifest,
    equities: Mapping[str, pd.Series],
    artifact_statuses: Mapping[str, Mapping[str, Any]],
    *,
    walk_forward_splits: Sequence[Any],
    cpcv_splits: Sequence[Any],
) -> dict[str, Any]:
    expected = set(manifest.variants)
    if set(equities) != expected:
        raise FormalGateError("equity artifacts must exactly match the registered candidate universe")

    blocked = [
        variant
        for variant in manifest.variants
        if artifact_statuses.get(variant, {}).get("status") != "FRESH"
    ]
    turnover_values: dict[str, float] = {}
    if manifest.turnover_objective is not None:
        metric = str(manifest.turnover_objective["metric"])
        for variant in manifest.variants:
            value = (artifact_statuses.get(variant, {}).get("turnover_evidence") or {}).get(
                metric
            )
            if value is None:
                blocked.append(variant)
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                blocked.append(variant)
                continue
            if not math.isfinite(numeric) or numeric < 0.0:
                blocked.append(variant)
                continue
            turnover_values[variant] = numeric
    if blocked:
        return _blocked_result(manifest, artifact_statuses, sorted(set(blocked)))

    first_index = equities[manifest.baseline].index
    if any(not equity.index.equals(first_index) for equity in equities.values()):
        raise FormalGateError("all equity artifacts must have identical date indexes")
    if first_index.has_duplicates or not first_index.is_monotonic_increasing:
        raise FormalGateError("equity date indexes must be unique and increasing")
    if len(first_index) < 10:
        raise FormalGateError("equity artifacts are too short")
    for variant, equity in equities.items():
        values = pd.to_numeric(equity, errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(values).all() or np.any(values <= 0.0):
            raise FormalGateError(f"equity values must be finite and positive: {variant}")
    if len(walk_forward_splits) < MIN_GATE_FOLDS or len(cpcv_splits) < MIN_GATE_FOLDS:
        raise FormalGateError(f"walk-forward and CPCV each require at least {MIN_GATE_FOLDS} folds")

    wf_matrix = _performance_matrix(manifest.variants, equities, walk_forward_splits)
    cpcv_matrix = _performance_matrix(manifest.variants, equities, cpcv_splits)
    wf = selection_evidence(wf_matrix)
    cpcv = selection_evidence(cpcv_matrix)

    target_equity = equities[manifest.target]
    baseline_equity = equities[manifest.baseline]
    target_metrics = compute_metrics(target_equity)
    baseline_metrics = compute_metrics(baseline_equity)
    target_returns = pd.to_numeric(target_equity, errors="coerce").pct_change(fill_method=None).dropna()
    skew = float(target_returns.skew())
    kurtosis = float(target_returns.kurt() + 3.0)
    shape_fallback = not math.isfinite(skew) or not math.isfinite(kurtosis)
    if shape_fallback:
        skew, kurtosis = 0.0, 3.0
    dsr = float(
        deflated_sharpe(
            target_returns.to_numpy(dtype=float),
            n_trials=manifest.declared_trial_count,
            skew=skew,
            kurt=kurtosis,
        )
    )

    thresholds = manifest.thresholds
    wf_delta = wf["median_oos"][manifest.target] - wf["median_oos"][manifest.baseline]
    cpcv_delta = cpcv["median_oos"][manifest.target] - cpcv["median_oos"][manifest.baseline]
    target_dd = abs(float(target_metrics.get("max_drawdown") or 0.0))
    baseline_dd = abs(float(baseline_metrics.get("max_drawdown") or 0.0))
    checks = {
        "walk_forward_pbo": wf["pbo"] < thresholds["pbo_max"],
        "cpcv_pbo": cpcv["pbo"] < thresholds["pbo_max"],
        "walk_forward_oos_delta": wf_delta > thresholds["min_oos_delta"],
        "cpcv_oos_delta": cpcv_delta > thresholds["min_oos_delta"],
        "max_drawdown": target_dd <= baseline_dd + thresholds["maxdd_tolerance"],
        "deflated_sharpe": dsr >= thresholds["min_dsr"],
    }
    turnover_result = None
    if manifest.turnover_objective is not None:
        metric = str(manifest.turnover_objective["metric"])
        baseline_turnover = turnover_values[manifest.baseline]
        target_turnover = turnover_values[manifest.target]
        turnover_delta = target_turnover - baseline_turnover
        max_delta = float(manifest.turnover_objective["max_delta_vs_baseline"])
        checks["turnover_objective"] = turnover_delta <= max_delta
        turnover_result = {
            "metric": metric,
            "baseline": baseline_turnover,
            "target": target_turnover,
            "delta_vs_baseline": turnover_delta,
            "max_delta_vs_baseline": max_delta,
        }
    passed = all(checks.values())
    if manifest.governance_lane == "data_correctness_migration":
        verdict = "MIGRATION_IMPACT_RECORDED"
        authorization = "NO_FLIP"
    else:
        verdict = "CANDIDATE_GATE_PASSED" if passed else "REJECTED"
        authorization = "HUMAN_FLIP_REQUIRED" if passed else "NO_FLIP"
    result = {
        "schema": RESULT_SCHEMA,
        "experiment_id": manifest.experiment_id,
        "governance_lane": manifest.governance_lane,
        "manifest_sha256": manifest.manifest_sha256,
        "variants": list(manifest.variants),
        "target_variant": manifest.target,
        "declared_trial_count": manifest.declared_trial_count,
        "artifact_statuses": dict(artifact_statuses),
        "walk_forward": {**wf, "target_delta_vs_baseline": wf_delta},
        "cpcv": {**cpcv, "target_delta_vs_baseline": cpcv_delta},
        "target": {
            "metrics": target_metrics,
            "baseline_metrics": baseline_metrics,
            "dsr": dsr,
            "dsr_inputs": {
                "n_trials": manifest.declared_trial_count,
                "skew": skew,
                "kurtosis": kurtosis,
                "shape_fallback": shape_fallback,
            },
        },
        "thresholds": dict(thresholds),
        "checks": checks,
        "verdict": verdict,
        "authorization": authorization,
    }
    if turnover_result is not None:
        result["turnover_objective"] = turnover_result
    return result
