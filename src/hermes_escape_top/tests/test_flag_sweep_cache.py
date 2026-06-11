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
    stabilizer = mod.build_config("decision_stabilizer")

    assert baseline["features"]["data_cot_nq"] is False
    assert cot["features"]["data_cot_nq"] is True
    assert stabilizer["features"]["use_decision_stabilizer"] is True


def test_cache_fresh_requires_schema_key_and_equity(tmp_path, monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(mod, "OUT_DIR", tmp_path)
    variant = "baseline"
    key = "abc123"

    (tmp_path / f"{variant}.json").write_text(json.dumps({
        "cache_schema": mod.CACHE_SCHEMA,
        "cache_key": key,
    }))
    assert mod._cache_is_fresh(variant, key) is False

    (tmp_path / f"{variant}_equity.json").write_text("{}")
    assert mod._cache_is_fresh(variant, key) is True
    assert mod._cache_is_fresh(variant, "different") is False


def test_cache_key_changes_on_config_and_commit(monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(mod, "_data_manifest_id", lambda cfg: "manifest-a")
    monkeypatch.setattr(mod, "_code_hash", lambda: "code-a")
    monkeypatch.setattr(mod, "_git_commit", lambda: "commit-a")

    cfg = mod.build_config("baseline")
    baseline_key = mod.cache_key("baseline", cfg)

    cfg_changed = mod.build_config("baseline")
    cfg_changed["status_thresholds"]["WATCH"] += 1
    assert mod.cache_key("baseline", cfg_changed) != baseline_key

    monkeypatch.setattr(mod, "_git_commit", lambda: "commit-b")
    assert mod.cache_key("baseline", cfg) != baseline_key
