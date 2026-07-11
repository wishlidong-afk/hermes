from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "execution_timing_sensitivity.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("execution_timing_cli", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _current() -> dict[str, object]:
    return {
        "git_commit": "abc123",
        "code_sha256": "code",
        "config_sha256": "config",
        "manifest_id": "manifest",
        "soft_history_sha256": "soft",
        "start": "2018-01-01",
        "end": "2026-05-29",
        "worktree_clean": True,
        "equity_timing": "next_open",
    }


def test_legacy_source_without_provenance_is_methodology_only() -> None:
    mod = _load_module()

    status = mod.classify_source_provenance({"data_manifest_id": "manifest"}, _current())

    assert status["status"] == "UNVERIFIED_LEGACY_SOURCE"
    assert status["headline_eligible"] is False


def test_matching_provenance_is_current_and_any_mismatch_is_stale() -> None:
    mod = _load_module()
    current = _current()
    source = {"provenance": dict(current)}

    matched = mod.classify_source_provenance(source, current)
    source["provenance"]["code_sha256"] = "old-code"
    stale = mod.classify_source_provenance(source, current)

    assert matched == {"status": "CURRENT_SOURCE", "mismatches": [], "headline_eligible": True}
    assert stale["status"] == "STALE_SOURCE"
    assert stale["mismatches"] == ["code_sha256"]
    assert stale["headline_eligible"] is False

    source["provenance"] = dict(current)
    current["worktree_clean"] = False
    dirty = mod.classify_source_provenance(source, current)
    assert dirty["status"] == "STALE_SOURCE"
    assert dirty["mismatches"] == ["worktree_clean"]


def test_extract_decisions_requires_explicit_route_weights() -> None:
    mod = _load_module()
    source = {
        "rows": [
            {"date": "2026-01-05", "route_leg_weights": {"BOXX": 1.0}},
            {"date": "2026-01-06", "route_leg_weights": {"BOXX": 0.5, "A": 0.5}},
        ]
    }

    decisions = mod.extract_decisions(source)

    assert [item.date for item in decisions] == ["2026-01-05", "2026-01-06"]
    with pytest.raises(ValueError, match="route_leg_weights"):
        mod.extract_decisions({"rows": [{"date": "2026-01-05"}]})


def test_source_window_prefers_provenance_and_falls_back_to_requested_dates() -> None:
    mod = _load_module()

    assert mod.source_window(
        {
            "requested_start": "old-start",
            "requested_end": "old-end",
            "provenance": {"start": "2018-01-01", "end": "2026-07-10"},
        }
    ) == ("2018-01-01", "2026-07-10")
    assert mod.source_window({"requested_start": "2019-01-01", "requested_end": "2025-12-31"}) == (
        "2019-01-01",
        "2025-12-31",
    )


def test_markdown_keeps_legacy_demoted_and_blocks_unverified_headline() -> None:
    mod = _load_module()
    artifact = {
        "evidence_status": "METHODOLOGY_ONLY",
        "source_provenance": {"status": "UNVERIFIED_LEGACY_SOURCE", "mismatches": []},
        "headline_scenario": "next_open",
        "open_quality": {"total_rows": 10, "observed_rows": 8, "modeled_rows": 2, "missing_rows": 0, "observed_share": 0.8, "counts": {}},
        "scenarios": [
            {
                "scenario_id": "legacy_close",
                "role": "HISTORICAL_THEORETICAL_UPPER_BOUND",
                "timing": "legacy_close",
                "extra_slippage_bps": 0.0,
                "turnover": 1.0,
                "base_cost": 10.0,
                "extra_slippage_cost": 0.0,
                "metrics": {"final_value": 110000.0, "cagr": 0.1, "max_drawdown": -0.2, "sharpe": 1.0},
            },
            {
                "scenario_id": "next_open",
                "role": "PRIMARY_REALISTIC",
                "timing": "next_open",
                "extra_slippage_bps": 0.0,
                "turnover": 1.0,
                "base_cost": 10.0,
                "extra_slippage_cost": 0.0,
                "metrics": {"final_value": 105000.0, "cagr": 0.08, "max_drawdown": -0.22, "sharpe": 0.8},
            },
        ],
        "notes": [],
    }

    report = mod.render_report(artifact)

    assert "METHODOLOGY_ONLY" in report
    assert "不得作为当前基线头条" in report
    assert "HISTORICAL_THEORETICAL_UPPER_BOUND" in report


def test_legacy_parity_compares_source_metrics_and_turnover() -> None:
    mod = _load_module()
    source = {
        "simulation": {
            "turnover": 2.5,
            "metrics": {"final_value": 123.0, "cagr": 0.1, "max_drawdown": -0.2, "sharpe": 0.8, "sortino": 1.0},
        }
    }
    artifact = {
        "scenarios": [
            {
                "scenario_id": "legacy_close",
                "turnover": 2.5,
                "metrics": {"final_value": 123.0, "cagr": 0.1, "max_drawdown": -0.2, "sharpe": 0.8, "sortino": 1.0},
            }
        ]
    }

    matched = mod.compare_legacy_source(source, artifact)
    artifact["scenarios"][0]["metrics"]["sharpe"] = 0.7
    mismatched = mod.compare_legacy_source(source, artifact)

    assert matched == {"status": "MATCH", "mismatches": []}
    assert mismatched == {"status": "MISMATCH", "mismatches": ["sharpe"]}


def test_gate_baseline_export_uses_next_open_curve_and_source_provenance() -> None:
    mod = _load_module()
    source = {
        "provenance": {**_current(), "cache_schema": "flag-sweep-cache-v4", "cache_key": "key", "variant": "baseline"},
        "effective_start": "2018-01-02",
        "effective_end": "2026-07-10",
        "dates": ["2018-01-02", "2026-07-10"],
    }
    artifact = {
        "evidence_status": "CURRENT_EXECUTION_EVIDENCE",
        "open_quality": {"observed_share": 0.9, "modeled_rows": 2, "missing_rows": 0},
        "scenarios": [
            {
                "scenario_id": "legacy_close",
                "metrics": {"cagr": 0.17},
                "equity_curve": {"2018-01-02": 100.0, "2026-07-10": 380.0},
            },
            {
                "scenario_id": "next_open",
                "metrics": {"cagr": 0.15},
                "turnover": 10.0,
                "equity_curve": {"2018-01-02": 100.0, "2026-07-10": 350.0},
            },
        ],
    }

    metrics, next_open_equity, legacy_equity = mod.build_gate_baseline_artifacts(source, artifact)

    assert metrics["equity_timing"] == "next_open"
    assert metrics["metrics"] == {"cagr": 0.15}
    assert metrics["legacy_close_metrics"] == {"cagr": 0.17}
    assert metrics["git_commit"] == "abc123"
    assert next_open_equity["2026-07-10"] == 350.0
    assert legacy_equity["2026-07-10"] == 380.0
