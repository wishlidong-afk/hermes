"""Fast tests for the flag-sweep cache-key wrapper."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "backtest_flag_sweep.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("backtest_flag_sweep", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def test_build_config_variants_are_distinct() -> None:
    mod = _load_module()
    baseline = mod.build_config("baseline")
    cot = mod.build_config("cot_nq")
    mnav = mod.build_config("mnav_b6")
    stabilizer = mod.build_config("decision_stabilizer")
    fred_vintage = mod.build_config("fred_vintage_pit")
    route_buffer = mod.build_config("route_set_transition_buffer")
    cd_baseline = mod.build_config("cd_trend_baseline")
    cd_dedup = mod.build_config("cd_trend_dedup")

    assert baseline["features"]["use_indicator_cache"] is True
    assert baseline["features"]["data_cot_nq"] is False
    assert cot["features"]["data_cot_nq"] is True
    assert mnav["features"]["data_mstr_mnav"] is True
    assert mnav["features"]["use_b6_mnav_valuation"] is True
    assert stabilizer["features"]["use_decision_stabilizer"] is True
    assert baseline["features"]["use_fred_vintage_pit"] is False
    assert fred_vintage["features"]["use_fred_vintage_pit"] is True
    assert baseline["features"].get("use_route_set_transition_buffer", False) is False
    assert route_buffer["features"]["use_route_set_transition_buffer"] is True
    assert cd_baseline["features"].get("use_cd_trend_dedup", False) is False
    assert cd_dedup["features"]["use_cd_trend_dedup"] is True


def test_route_set_turnover_counts_only_non_risk_set_transition_days() -> None:
    mod = _load_module()
    config = {"symbols": {"MSTR": {}, "FNGU": {}, "SOXL": {}}}
    rows = [
        {"date": "2026-01-01", "route_leg_weights": {"BOXX": 0.8, "MSTR": 0.2}},
        {"date": "2026-01-02", "route_leg_weights": {"BOXX": 0.79, "MSTR": 0.2, "IAU": 0.01}},
        {"date": "2026-01-03", "route_leg_weights": {"BOXX": 0.77, "MSTR": 0.22, "IAU": 0.01}},
        {"date": "2026-01-04", "route_leg_weights": {"BOXX": 0.78, "MSTR": 0.22}},
    ]

    evidence = mod.route_set_turnover_evidence(rows, config)

    assert evidence == {
        "definition": "full_portfolio_l1_on_nonrisk_nonboxx_route_set_change_days",
        "event_count": 2,
        "total": 0.04,
    }


def test_default_gate_config_uses_current_baseline_snapshot(tmp_path, monkeypatch) -> None:
    mod = _load_module()
    snapshot = tmp_path / "CURRENT_BASELINE_CONFIG.json"
    config = json.loads((REPO_ROOT / "src/hermes_escape_top/config/config.json").read_text())
    config["features"]["use_market_admission_gate"] = True
    config["features"].pop("use_fred_vintage_pit", None)
    snapshot.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(mod, "CURRENT_BASELINE_CONFIG_PATH", snapshot)

    selected = mod.build_config("baseline")
    explicit = mod.build_config(
        "baseline",
        config_path=REPO_ROOT / "src/hermes_escape_top/config/config.json",
    )

    assert selected["features"]["use_market_admission_gate"] is True
    assert explicit["features"]["use_market_admission_gate"] is False
    assert selected["features"]["use_indicator_cache"] is True
    assert selected["features"]["use_fred_vintage_pit"] is False


def test_provenance_commit_ignores_docs_only_commits(tmp_path, monkeypatch) -> None:
    mod = _load_module()
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "cache-test@example.com")
    _git(tmp_path, "config", "user.name", "Cache Test")
    source = tmp_path / "src" / "hermes_escape_top" / "core" / "model.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", source.relative_to(tmp_path).as_posix())
    _git(tmp_path, "commit", "-q", "-m", "add gate code")
    code_commit = _git(tmp_path, "rev-parse", "HEAD")

    docs = tmp_path / "docs" / "evidence.md"
    docs.parent.mkdir(parents=True)
    docs.write_text("evidence\n", encoding="utf-8")
    _git(tmp_path, "add", docs.relative_to(tmp_path).as_posix())
    _git(tmp_path, "commit", "-q", "-m", "record evidence")
    test_file = tmp_path / "src" / "hermes_escape_top" / "tests" / "test_model.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_value(): assert True\n", encoding="utf-8")
    _git(tmp_path, "add", test_file.relative_to(tmp_path).as_posix())
    _git(tmp_path, "commit", "-q", "-m", "add gate test")
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)

    assert mod._git_commit() == code_commit

    source.write_text("VALUE = 2\n", encoding="utf-8")
    _git(tmp_path, "add", source.relative_to(tmp_path).as_posix())
    _git(tmp_path, "commit", "-q", "-m", "change gate code")
    assert mod._git_commit() == _git(tmp_path, "rev-parse", "HEAD")


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


def test_current_gate_window_comes_from_current_baseline_artifact(tmp_path, monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(mod, "OUT_DIR", tmp_path)
    (tmp_path / "baseline.json").write_text(
        json.dumps(
            {
                "evidence_status": "CURRENT_EXECUTION_EVIDENCE",
                "start": "2018-01-01",
                "end": "2026-07-14",
            }
        ),
        encoding="utf-8",
    )

    assert mod.current_gate_window() == ("2018-01-01", "2026-07-14")

    (tmp_path / "baseline.json").write_text('{"evidence_status": "STALE"}', encoding="utf-8")
    assert mod.current_gate_window() == (mod.BACKTEST_START, mod.BACKTEST_END)


def test_artifact_freshness_uses_explicit_gate_window(monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(mod, "_data_manifest_id", lambda cfg: "manifest-a")
    monkeypatch.setattr(mod, "_soft_history_hash", lambda cfg: "soft-a")
    monkeypatch.setattr(mod, "_code_hash", lambda: "code-a")
    monkeypatch.setattr(mod, "_git_commit", lambda: "commit-a")
    cfg = mod.build_config("baseline")
    cached = mod.cache_evidence(
        "baseline",
        cfg,
        start="2018-01-01",
        end="2026-07-14",
    )

    assert mod.assess_artifact_freshness(
        "baseline",
        cached,
        cfg,
        start="2018-01-01",
        end="2026-07-14",
    )["status"] == "FRESH"
    assert mod.assess_artifact_freshness("baseline", cached, cfg)["status"] == "STALE"


def test_artifact_freshness_rejects_any_provenance_mismatch(monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(mod, "_data_manifest_id", lambda cfg: "manifest-a")
    monkeypatch.setattr(mod, "_soft_history_hash", lambda cfg: "soft-a")
    monkeypatch.setattr(mod, "_code_hash", lambda: "code-a")
    monkeypatch.setattr(mod, "_git_commit", lambda: "commit-a")

    cfg = mod.build_config("baseline")
    current = mod.cache_evidence("baseline", cfg)
    assert current["evidence_status"] == "CURRENT_EXECUTION_EVIDENCE"
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
        "evidence_status",
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
