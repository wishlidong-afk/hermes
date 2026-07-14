from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from hermes_escape_top.core.backtest.formal_gate import (
    ExperimentManifest,
    FormalGateError,
    PerformanceMatrix,
    evaluate_formal_gate,
    selection_evidence,
    split_objective,
)
from hermes_escape_top.core.backtest.harness import cpcv_splits
from hermes_escape_top.core.backtest.validation import walk_forward_splits


def _manifest(**updates) -> ExperimentManifest:
    raw = {
        "schema": "hermes-formal-gate-v1",
        "experiment_id": "alpha-hypothesis-v1",
        "created_at": "2026-07-10",
        "hypothesis": "Alpha improves defensive OOS performance without worsening drawdown.",
        "artifacts_dir": "building/reports/flag_sweep",
        "baseline": "baseline",
        "target": "alpha",
        "candidates": ["alpha", "beta"],
        "declared_trial_count": 7,
        "walk_forward": {
            "is_years": 2,
            "oos_months": 6,
            "step_months": 6,
            "label_horizon": 20,
            "embargo_pct": 0.02,
        },
        "cpcv": {
            "n_groups": 6,
            "n_test": 2,
            "label_horizon": 20,
            "embargo_pct": 0.02,
        },
        "thresholds": {
            "pbo_max": 0.5,
            "min_oos_delta": 0.0,
            "maxdd_tolerance": 0.01,
            "min_dsr": 0.0,
        },
    }
    raw.update(updates)
    return ExperimentManifest.from_dict(raw)


def _equity(returns: np.ndarray) -> pd.Series:
    dates = pd.bdate_range("2020-01-02", periods=len(returns) + 1)
    values = 100.0 * np.cumprod(np.r_[1.0, 1.0 + returns])
    return pd.Series(values, index=dates)


def _synthetic_equities(n_returns: int = 119) -> dict[str, pd.Series]:
    x = np.arange(n_returns, dtype=float)
    return {
        "baseline": _equity(0.0010 + 0.0002 * np.sin(x / 5.0)),
        "alpha": _equity(0.0020 + 0.0003 * np.sin(x / 4.0)),
        "beta": _equity(-0.0005 + 0.0002 * np.cos(x / 6.0)),
    }


def _splits() -> list[tuple[np.ndarray, np.ndarray]]:
    return [
        (np.arange(0, 50), np.arange(50 + 5 * fold, 75 + 5 * fold))
        for fold in range(8)
    ]


def test_manifest_seals_exact_candidate_universe_and_trial_count() -> None:
    manifest = _manifest()

    assert manifest.variants == ("baseline", "alpha", "beta")
    assert manifest.governance_lane == "alpha_experiment"
    assert manifest.target == "alpha"
    assert manifest.declared_trial_count == 7
    assert len(manifest.manifest_sha256) == 64

    with pytest.raises(FormalGateError, match="target must be listed"):
        _manifest(target="missing")
    with pytest.raises(FormalGateError, match="candidates must be unique"):
        _manifest(candidates=["alpha", "alpha"])
    with pytest.raises(FormalGateError, match="declared_trial_count"):
        _manifest(declared_trial_count=2)
    with pytest.raises(FormalGateError, match="pbo_max"):
        _manifest(
            thresholds={
                "pbo_max": 0.75,
                "min_oos_delta": 0.0,
                "maxdd_tolerance": 0.01,
                "min_dsr": 0.0,
            }
        )
    for weakened in (
        {
            "pbo_max": 0.5,
            "min_oos_delta": -0.01,
            "maxdd_tolerance": 0.01,
            "min_dsr": 0.0,
        },
        {
            "pbo_max": 0.5,
            "min_oos_delta": 0.0,
            "maxdd_tolerance": 0.02,
            "min_dsr": 0.0,
        },
        {
            "pbo_max": 0.5,
            "min_oos_delta": 0.0,
            "maxdd_tolerance": 0.01,
            "min_dsr": -0.1,
        },
    ):
        with pytest.raises(FormalGateError, match="weaker than policy"):
            _manifest(thresholds=weakened)

    with pytest.raises(FormalGateError, match="walk_forward policy"):
        _manifest(
            walk_forward={
                "is_years": 1,
                "oos_months": 3,
                "step_months": 3,
                "label_horizon": 5,
                "embargo_pct": 0.0,
            }
        )
    with pytest.raises(FormalGateError, match="cpcv policy"):
        _manifest(
            cpcv={
                "n_groups": 4,
                "n_test": 1,
                "label_horizon": 5,
                "embargo_pct": 0.0,
            }
        )


def test_v2_manifest_requires_an_immutable_governance_lane() -> None:
    with pytest.raises(FormalGateError, match="governance_lane"):
        _manifest(schema="hermes-formal-gate-v2")

    migration = _manifest(
        schema="hermes-formal-gate-v2",
        governance_lane="data_correctness_migration",
    )
    assert migration.governance_lane == "data_correctness_migration"

    with pytest.raises(FormalGateError, match="governance_lane"):
        _manifest(schema="hermes-formal-gate-v2", governance_lane="choose_after_results")


def test_selection_evidence_uses_is_winner_for_oos_pbo() -> None:
    matrix = PerformanceMatrix(
        variants=("baseline", "alpha"),
        is_perf=np.asarray([[10.0, 1.0], [1.0, 10.0]]),
        oos_perf=np.asarray([[0.0, 10.0], [10.0, 0.0]]),
    )

    evidence = selection_evidence(matrix)

    assert evidence["pbo"] == 1.0
    assert [row["selected_variant"] for row in evidence["folds"]] == ["baseline", "alpha"]
    assert all(row["overfit_event"] for row in evidence["folds"])


def test_split_objective_excludes_returns_across_disjoint_boundaries() -> None:
    index = pd.bdate_range("2026-01-02", periods=10)
    scaled_second_block = pd.Series(
        [100, 101, 102, 103, 104, 105, 1000, 1010, 1020, 1030],
        index=index,
        dtype=float,
    )
    unscaled_second_block = pd.Series(
        [100, 101, 102, 103, 104, 105, 100, 101, 102, 103],
        index=index,
        dtype=float,
    )
    disjoint = np.asarray([0, 1, 2, 3, 6, 7, 8, 9])

    assert split_objective(scaled_second_block, disjoint) == pytest.approx(
        split_objective(unscaled_second_block, disjoint)
    )


def test_formal_gate_passes_only_as_candidate_pending_human_flip() -> None:
    manifest = _manifest()
    result = evaluate_formal_gate(
        manifest,
        _synthetic_equities(),
        {variant: {"status": "FRESH"} for variant in manifest.variants},
        walk_forward_splits=_splits(),
        cpcv_splits=_splits(),
    )

    assert result["verdict"] == "CANDIDATE_GATE_PASSED"
    assert result["authorization"] == "HUMAN_FLIP_REQUIRED"
    assert result["walk_forward"]["pbo"] == 0.0
    assert result["cpcv"]["pbo"] == 0.0
    assert result["target"]["dsr_inputs"]["n_trials"] == 7
    assert math.isfinite(result["target"]["dsr_inputs"]["skew"])
    assert math.isfinite(result["target"]["dsr_inputs"]["kurtosis"])
    assert all(result["checks"].values())


def test_data_correctness_lane_records_impact_without_alpha_authorization() -> None:
    manifest = _manifest(
        schema="hermes-formal-gate-v2",
        governance_lane="data_correctness_migration",
        target="beta",
    )
    result = evaluate_formal_gate(
        manifest,
        _synthetic_equities(),
        {variant: {"status": "FRESH"} for variant in manifest.variants},
        walk_forward_splits=_splits(),
        cpcv_splits=_splits(),
    )

    assert result["governance_lane"] == "data_correctness_migration"
    assert result["verdict"] == "MIGRATION_IMPACT_RECORDED"
    assert result["authorization"] == "NO_FLIP"
    assert not all(result["checks"].values())


def test_formal_gate_runs_registered_walk_forward_and_cpcv_design() -> None:
    manifest = _manifest()
    equities = _synthetic_equities(2200)
    dates = [day.isoformat() for day in equities[manifest.baseline].index]
    wf = walk_forward_splits(dates, **dict(manifest.walk_forward))
    cpcv = cpcv_splits(len(dates), **dict(manifest.cpcv))

    result = evaluate_formal_gate(
        manifest,
        equities,
        {variant: {"status": "FRESH"} for variant in manifest.variants},
        walk_forward_splits=wf,
        cpcv_splits=cpcv,
    )

    assert result["walk_forward"]["n_folds"] >= 8
    assert result["cpcv"]["n_folds"] == 15
    assert result["verdict"] == "CANDIDATE_GATE_PASSED"


def test_formal_gate_blocks_stale_or_incomplete_artifacts() -> None:
    manifest = _manifest()
    statuses = {variant: {"status": "FRESH"} for variant in manifest.variants}
    statuses["alpha"] = {"status": "STALE", "mismatches": ["cache_key"]}

    stale = evaluate_formal_gate(
        manifest,
        _synthetic_equities(),
        statuses,
        walk_forward_splits=_splits(),
        cpcv_splits=_splits(),
    )
    assert stale["verdict"] == "BLOCKED"
    assert stale["authorization"] == "NO_FLIP"
    assert "alpha" in stale["blocked_variants"]

    incomplete = _synthetic_equities()
    incomplete.pop("beta")
    with pytest.raises(FormalGateError, match="candidate universe"):
        evaluate_formal_gate(
            manifest,
            incomplete,
            statuses,
            walk_forward_splits=_splits(),
            cpcv_splits=_splits(),
        )


def test_formal_gate_requires_enough_folds_for_authorization() -> None:
    manifest = _manifest()
    statuses = {variant: {"status": "FRESH"} for variant in manifest.variants}

    with pytest.raises(FormalGateError, match="at least 8 folds"):
        evaluate_formal_gate(
            manifest,
            _synthetic_equities(),
            statuses,
            walk_forward_splits=_splits()[:2],
            cpcv_splits=_splits(),
        )


def test_formal_gate_rejects_misaligned_dates_and_nonfinite_objectives() -> None:
    manifest = _manifest()
    equities = _synthetic_equities()
    equities["beta"] = equities["beta"].iloc[1:]
    statuses = {variant: {"status": "FRESH"} for variant in manifest.variants}

    with pytest.raises(FormalGateError, match="identical date indexes"):
        evaluate_formal_gate(
            manifest,
            equities,
            statuses,
            walk_forward_splits=_splits(),
            cpcv_splits=_splits(),
        )


def test_formal_gate_rejects_duplicate_dates_and_nonfinite_equity() -> None:
    manifest = _manifest()
    statuses = {variant: {"status": "FRESH"} for variant in manifest.variants}
    duplicates = _synthetic_equities()
    duplicate_index = duplicates["baseline"].index.to_list()
    duplicate_index[-1] = duplicate_index[-2]
    for variant in duplicates:
        duplicates[variant].index = pd.DatetimeIndex(duplicate_index)

    with pytest.raises(FormalGateError, match="unique and increasing"):
        evaluate_formal_gate(
            manifest,
            duplicates,
            statuses,
            walk_forward_splits=_splits(),
            cpcv_splits=_splits(),
        )

    nonfinite = _synthetic_equities()
    nonfinite["alpha"].iloc[10] = np.nan
    with pytest.raises(FormalGateError, match="finite and positive"):
        evaluate_formal_gate(
            manifest,
            nonfinite,
            statuses,
            walk_forward_splits=_splits(),
            cpcv_splits=_splits(),
        )
