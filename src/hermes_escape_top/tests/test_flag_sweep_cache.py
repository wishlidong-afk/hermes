"""Fast tests for the flag-sweep cache-key wrapper."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "backtest_flag_sweep.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("backtest_flag_sweep", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_config_variants_are_distinct() -> None:
    mod = _load_module()
    baseline = mod.build_config("baseline")
    cot = mod.build_config("cot_nq")
    mnav = mod.build_config("mnav_b6")
    stabilizer = mod.build_config("decision_stabilizer")

    assert baseline["features"]["use_indicator_cache"] is True
    assert baseline["features"]["data_cot_nq"] is False
    assert cot["features"]["data_cot_nq"] is True
    assert mnav["features"]["data_mstr_mnav"] is True
    assert mnav["features"]["use_b6_mnav_valuation"] is True
    assert stabilizer["features"]["use_decision_stabilizer"] is True


def test_cache_fresh_requires_schema_key_and_equity(tmp_path, monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(mod, "OUT_DIR", tmp_path)
    variant = "baseline"
    expected = {
        "variant": variant,
        "cache_schema": mod.CACHE_SCHEMA,
        "cache_key": "abc123",
        "manifest_id": "manifest-a",
        "git_commit": "commit-a",
        "code_sha256": "code-a",
        "config_sha256": "config-a",
        "soft_history_sha256": "soft-a",
        "start": mod.BACKTEST_START,
        "end": mod.BACKTEST_END,
        "enable": mod.ENABLE,
        "equity_timing": "next_open",
    }

    (tmp_path / f"{variant}.json").write_text(json.dumps(expected))
    assert mod._cache_is_fresh(variant, expected) is False

    (tmp_path / f"{variant}_equity.json").write_text("{}")
    assert mod._cache_is_fresh(variant, expected) is True

    stale = dict(expected, cache_key="different")
    assert mod._cache_is_fresh(variant, stale) is False

    missing_provenance = dict(expected)
    missing_provenance.pop("soft_history_sha256")
    (tmp_path / f"{variant}.json").write_text(json.dumps(missing_provenance))
    assert mod._cache_is_fresh(variant, expected) is False


def test_cache_key_changes_on_config_and_commit(monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(mod, "_data_manifest_id", lambda cfg: "manifest-a")
    monkeypatch.setattr(mod, "_soft_history_hash", lambda cfg: "soft-a")
    monkeypatch.setattr(mod, "_code_hash", lambda: "code-a")
    monkeypatch.setattr(mod, "_git_commit", lambda: "commit-a")

    cfg = mod.build_config("baseline")
    baseline_key = mod.cache_key("baseline", cfg)

    cfg_changed = mod.build_config("baseline")
    cfg_changed["status_thresholds"]["WATCH"] += 1
    assert mod.cache_key("baseline", cfg_changed) != baseline_key

    monkeypatch.setattr(mod, "_git_commit", lambda: "commit-b")
    assert mod.cache_key("baseline", cfg) != baseline_key

    monkeypatch.setattr(mod, "_git_commit", lambda: "commit-a")
    monkeypatch.setattr(mod, "_soft_history_hash", lambda cfg: "soft-b")
    assert mod.cache_key("baseline", cfg) != baseline_key


def test_cache_evidence_exposes_every_freshness_dimension(monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(mod, "_data_manifest_id", lambda cfg: "manifest-a")
    monkeypatch.setattr(mod, "_soft_history_hash", lambda cfg: "soft-a")
    monkeypatch.setattr(mod, "_code_hash", lambda: "code-a")
    monkeypatch.setattr(mod, "_git_commit", lambda: "commit-a")

    cfg = mod.build_config("baseline")
    evidence = mod.cache_evidence("baseline", cfg)

    assert mod.CACHE_SCHEMA == "flag-sweep-cache-v4"
    assert evidence["variant"] == "baseline"
    assert evidence["manifest_id"] == "manifest-a"
    assert evidence["soft_history_sha256"] == "soft-a"
    assert evidence["code_sha256"] == "code-a"
    assert evidence["git_commit"] == "commit-a"
    assert evidence["config_sha256"]
    assert evidence["cache_key"]
    assert evidence["start"] == mod.BACKTEST_START
    assert evidence["end"] == mod.BACKTEST_END
    assert evidence["enable"] == mod.ENABLE
    assert evidence["equity_timing"] == "next_open"


def test_cache_evidence_accepts_an_explicit_current_window(monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(mod, "_data_manifest_id", lambda cfg: "manifest-a")
    monkeypatch.setattr(mod, "_soft_history_hash", lambda cfg: "soft-a")
    monkeypatch.setattr(mod, "_code_hash", lambda: "code-a")
    monkeypatch.setattr(mod, "_git_commit", lambda: "commit-a")
    cfg = mod.build_config("baseline")

    evidence = mod.cache_evidence(
        "baseline",
        cfg,
        start="2018-01-01",
        end="2026-07-09",
        enable=["costs"],
    )

    assert evidence["start"] == "2018-01-01"
    assert evidence["end"] == "2026-07-09"
    assert evidence["enable"] == ["costs"]
    assert evidence["cache_key"] != mod.cache_evidence("baseline", cfg)["cache_key"]


def test_artifact_freshness_rejects_any_provenance_mismatch(monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(mod, "_data_manifest_id", lambda cfg: "manifest-a")
    monkeypatch.setattr(mod, "_soft_history_hash", lambda cfg: "soft-a")
    monkeypatch.setattr(mod, "_code_hash", lambda: "code-a")
    monkeypatch.setattr(mod, "_git_commit", lambda: "commit-a")

    cfg = mod.build_config("baseline")
    current = mod.cache_evidence("baseline", cfg)
    assert mod.assess_artifact_freshness("baseline", current, cfg)["status"] == "FRESH"

    for field in (
        "cache_schema",
        "cache_key",
        "manifest_id",
        "git_commit",
        "code_sha256",
        "config_sha256",
        "soft_history_sha256",
        "start",
        "end",
        "enable",
        "equity_timing",
    ):
        stale = dict(current)
        stale[field] = "different"
        result = mod.assess_artifact_freshness("baseline", stale, cfg)
        assert result["status"] == "STALE"
        assert field in result["mismatches"]


def test_gate_equity_selector_uses_next_open_and_keeps_legacy_shadow() -> None:
    mod = _load_module()
    timing = {
        "scenarios": [
            {"scenario_id": "legacy_close", "metrics": {"cagr": 0.20}, "equity_curve": {"2026-01-01": 100.0}},
            {"scenario_id": "next_open", "metrics": {"cagr": 0.15}, "equity_curve": {"2026-01-01": 99.0}},
        ]
    }

    selected = mod.select_gate_equity(timing)

    assert selected["equity_timing"] == "next_open"
    assert selected["metrics"] == {"cagr": 0.15}
    assert selected["equity_curve"] == {"2026-01-01": 99.0}
    assert selected["legacy_close_metrics"] == {"cagr": 0.20}
