from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest

from hermes_escape_top.core.backtest.formal_gate import ExperimentManifest, FormalGateError


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "formal_gate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("formal_gate_cli", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def _manifest(**updates) -> ExperimentManifest:
    raw = {
        "schema": "hermes-formal-gate-v1",
        "experiment_id": "cli-integration-v1",
        "created_at": "2026-07-10",
        "hypothesis": "The target improves the pre-registered OOS objective.",
        "artifacts_dir": "building/reports/flag_sweep",
        "baseline": "baseline",
        "target": "alpha",
        "candidates": ["alpha"],
        "declared_trial_count": 2,
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


def _equities() -> dict[str, pd.Series]:
    x = np.arange(119, dtype=float)
    dates = pd.bdate_range("2020-01-02", periods=120)

    def curve(returns: np.ndarray) -> pd.Series:
        return pd.Series(100.0 * np.cumprod(np.r_[1.0, 1.0 + returns]), index=dates)

    return {
        "baseline": curve(0.001 + 0.0002 * np.sin(x / 5.0)),
        "alpha": curve(0.002 + 0.0003 * np.sin(x / 4.0)),
    }


def _splits() -> list[tuple[np.ndarray, np.ndarray]]:
    return [
        (np.arange(0, 50), np.arange(50 + 5 * fold, 75 + 5 * fold))
        for fold in range(8)
    ]


def test_manifest_must_be_committed_and_clean(tmp_path) -> None:
    mod = _load_module()
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "gate-test@example.com")
    _git(tmp_path, "config", "user.name", "Gate Test")
    manifest = tmp_path / "experiment.json"
    manifest.write_text("{}\n", encoding="utf-8")

    with pytest.raises(FormalGateError, match="tracked"):
        mod.require_preregistered_manifest(tmp_path, manifest)

    _git(tmp_path, "add", "experiment.json")
    _git(tmp_path, "commit", "-q", "-m", "register experiment")
    commit = mod.require_preregistered_manifest(tmp_path, manifest)
    assert commit == _git(tmp_path, "rev-parse", "HEAD")

    manifest.write_text('{"changed": true}\n', encoding="utf-8")
    with pytest.raises(FormalGateError, match="committed and clean"):
        mod.require_preregistered_manifest(tmp_path, manifest)


def test_gate_code_must_be_committed_while_report_outputs_may_be_dirty(tmp_path) -> None:
    mod = _load_module()
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "gate-test@example.com")
    _git(tmp_path, "config", "user.name", "Gate Test")
    source = tmp_path / "src" / "hermes_escape_top" / "core" / "model.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    baseline_config = (
        tmp_path
        / "building"
        / "reports"
        / "current_baseline"
        / "CURRENT_BASELINE_CONFIG.json"
    )
    baseline_config.parent.mkdir(parents=True)
    baseline_config.write_text("{}\n", encoding="utf-8")
    reports = tmp_path / "building" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "result.json").write_text("{}\n", encoding="utf-8")
    soft_data = tmp_path / "src" / "hermes_escape_top" / "data" / "soft_history" / "source.csv"
    soft_data.parent.mkdir(parents=True)
    soft_data.write_text("date,value\n2026-07-10,1\n", encoding="utf-8")
    _git(
        tmp_path,
        "add",
        "src/hermes_escape_top/core/model.py",
        "building/reports/current_baseline/CURRENT_BASELINE_CONFIG.json",
    )
    _git(tmp_path, "commit", "-q", "-m", "add gate code")

    assert mod.require_gate_code_clean(tmp_path) == _git(tmp_path, "rev-parse", "HEAD")

    source.write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(FormalGateError, match="gate code and config must be committed"):
        mod.require_gate_code_clean(tmp_path)

    source.write_text("VALUE = 1\n", encoding="utf-8")
    baseline_config.write_text('{"changed": true}\n', encoding="utf-8")
    with pytest.raises(FormalGateError, match="gate code and config must be committed"):
        mod.require_gate_code_clean(tmp_path)


def test_result_commit_marker_is_written_once_and_last(tmp_path) -> None:
    mod = _load_module()
    output = tmp_path / "formal_gate" / "alpha-v1"
    result = {
        "schema": "hermes-formal-gate-result-v1",
        "experiment_id": "alpha-v1",
        "verdict": "REJECTED",
        "authorization": "NO_FLIP",
    }

    mod.write_result_once(output, result, "# Formal Gate\n")

    assert json.loads((output / "result.json").read_text())["verdict"] == "REJECTED"
    assert (output / "REPORT.md").read_text() == "# Formal Gate\n"
    with pytest.raises(FormalGateError, match="already has a final result"):
        mod.write_result_once(output, result, "changed")


def test_result_snapshots_input_artifacts_before_final_marker(tmp_path) -> None:
    mod = _load_module()
    output = tmp_path / "formal_gate" / "alpha-v1"
    source = tmp_path / "flag_sweep" / "baseline.json"
    source.parent.mkdir(parents=True)
    source.write_bytes(b'{"metric": 1}\n')
    result = {
        "schema": "hermes-formal-gate-result-v1",
        "experiment_id": "alpha-v1",
        "verdict": "REJECTED",
        "authorization": "NO_FLIP",
    }

    mod.write_result_once(
        output,
        result,
        "# Formal Gate\n",
        artifact_sources={"artifacts/baseline.json": source},
    )
    source.write_bytes(b'{"metric": 2}\n')

    assert (output / "artifacts" / "baseline.json").read_bytes() == b'{"metric": 1}\n'
    assert (output / "result.json").exists()


def test_artifact_snapshot_sources_collects_each_variant_without_touching_baseline(tmp_path) -> None:
    mod = _load_module()
    manifest = _manifest()
    artifact_dir = tmp_path / manifest.artifacts_dir
    artifact_dir.mkdir(parents=True)
    expected = {
        "baseline.json",
        "baseline_equity.json",
        "baseline_legacy_close_equity.json",
        "alpha.json",
        "alpha_equity.json",
        "alpha_legacy_close_equity.json",
    }
    for name in expected:
        (artifact_dir / name).write_text(f"{name}\n", encoding="utf-8")

    sources = mod.artifact_snapshot_sources(tmp_path, manifest)

    assert set(sources) == {f"artifacts/{name}" for name in expected}
    assert {path.name for path in sources.values()} == expected


def test_load_artifacts_uses_baseline_window_for_every_variant(tmp_path, monkeypatch) -> None:
    mod = _load_module()
    manifest = _manifest()
    artifact_dir = tmp_path / manifest.artifacts_dir
    artifact_dir.mkdir(parents=True)
    for variant in manifest.variants:
        (artifact_dir / f"{variant}.json").write_text(
            json.dumps({"start": "2018-01-01", "end": "2026-07-14"}),
            encoding="utf-8",
        )
        (artifact_dir / f"{variant}_equity.json").write_text(
            json.dumps({"2026-07-14": 100.0}),
            encoding="utf-8",
        )
    seen: dict[str, tuple[str, str]] = {}
    monkeypatch.setattr(mod, "build_config", lambda variant: {"variant": variant})

    def assess(variant, cached, cfg, *, start, end):
        seen[variant] = (start, end)
        return {"status": "FRESH"}

    monkeypatch.setattr(mod, "assess_artifact_freshness", assess)

    _, statuses, missing = mod.load_artifacts(tmp_path, manifest)

    assert missing == []
    assert statuses == {"baseline": {"status": "FRESH"}, "alpha": {"status": "FRESH"}}
    assert seen == {
        "baseline": ("2018-01-01", "2026-07-14"),
        "alpha": ("2018-01-01", "2026-07-14"),
    }


def test_load_artifacts_exposes_preregistered_turnover_evidence(tmp_path, monkeypatch) -> None:
    mod = _load_module()
    manifest = _manifest(
        schema="hermes-formal-gate-v3",
        governance_lane="alpha_experiment",
        turnover_objective={
            "metric": "route_set_turnover",
            "max_delta_vs_baseline": -1.0,
        },
    )
    artifact_dir = tmp_path / manifest.artifacts_dir
    artifact_dir.mkdir(parents=True)
    for variant, turnover in (("baseline", 100.0), ("alpha", 90.0)):
        (artifact_dir / f"{variant}.json").write_text(
            json.dumps(
                {
                    "start": "2018-01-01",
                    "end": "2026-07-14",
                    "route_set_turnover": {"total": turnover},
                }
            ),
            encoding="utf-8",
        )
        (artifact_dir / f"{variant}_equity.json").write_text(
            json.dumps({"2026-07-14": 100.0}),
            encoding="utf-8",
        )
    monkeypatch.setattr(mod, "build_config", lambda variant: {"variant": variant})
    monkeypatch.setattr(
        mod,
        "assess_artifact_freshness",
        lambda *args, **kwargs: {"status": "FRESH"},
    )

    _, statuses, missing = mod.load_artifacts(tmp_path, manifest)

    assert missing == []
    assert statuses["baseline"]["turnover_evidence"] == {
        "route_set_turnover": 100.0
    }
    assert statuses["alpha"]["turnover_evidence"] == {
        "route_set_turnover": 90.0
    }


def test_cost_governed_report_prints_the_sealed_turnover_result() -> None:
    mod = _load_module()
    manifest = _manifest(
        schema="hermes-formal-gate-v3",
        governance_lane="alpha_experiment",
        turnover_objective={
            "metric": "route_set_turnover",
            "max_delta_vs_baseline": -1.0,
        },
    )
    result = {
        "verdict": "REJECTED",
        "authorization": "NO_FLIP",
        "checks": {"turnover_objective": False},
        "walk_forward": {
            "pbo": 0.0,
            "target_delta_vs_baseline": 0.1,
            "n_folds": 8,
        },
        "cpcv": {
            "pbo": 0.0,
            "target_delta_vs_baseline": 0.1,
            "n_folds": 15,
        },
        "target": {
            "dsr": 1.0,
            "dsr_inputs": {"n_trials": 2, "skew": 0.0, "kurtosis": 3.0},
        },
        "turnover_objective": {
            "metric": "route_set_turnover",
            "baseline": 100.0,
            "target": 100.0,
            "delta_vs_baseline": 0.0,
            "max_delta_vs_baseline": -1.0,
        },
    }

    report = mod.render_report(manifest, result)

    assert "Turnover objective" in report
    assert "route_set_turnover" in report
    assert "delta `+0.000000`" in report
    assert "required `<= -1.000000`" in report


def test_run_rechecks_manifest_and_code_before_final_commit(tmp_path, monkeypatch) -> None:
    mod = _load_module()
    manifest = _manifest()
    checks = {"manifest": 0, "code": 0}

    def check_manifest(repo_root, path):
        checks["manifest"] += 1
        return "commit-a"

    def check_code(repo_root):
        checks["code"] += 1
        return "commit-a"

    monkeypatch.setattr(mod, "require_preregistered_manifest", check_manifest)
    monkeypatch.setattr(mod, "require_gate_code_clean", check_code)
    monkeypatch.setattr(mod, "load_manifest", lambda path: manifest)
    monkeypatch.setattr(
        mod,
        "load_artifacts",
        lambda repo_root, registered: (
            _equities(),
            {variant: {"status": "FRESH"} for variant in registered.variants},
            [],
        ),
    )
    monkeypatch.setattr(mod, "walk_forward_splits", lambda dates, **kwargs: _splits())
    monkeypatch.setattr(mod, "cpcv_splits", lambda n_obs, **kwargs: _splits())

    result = mod.run(
        tmp_path / "experiment.json",
        repo_root=tmp_path,
        output_root=tmp_path / "results",
    )

    assert result["verdict"] == "CANDIDATE_GATE_PASSED"
    assert checks == {"manifest": 2, "code": 2}
    assert (tmp_path / "results" / manifest.experiment_id / "result.json").exists()
