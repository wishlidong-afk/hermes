from __future__ import annotations

import copy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "build_current_baseline.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("current_baseline_builder", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _evidence() -> dict[str, object]:
    return {
        "variant": "baseline",
        "cache_schema": "flag-sweep-cache-v4",
        "cache_key": "key",
        "manifest_id": "manifest-a",
        "git_commit": "commit-a",
        "code_sha256": "code-a",
        "config_sha256": "config-a",
        "soft_history_sha256": "soft-a",
        "start": "2018-01-01",
        "end": "2026-07-10",
        "enable": ["costs"],
        "equity_timing": "next_open",
    }


def test_source_payload_embeds_clean_provenance_and_requires_manifest_match() -> None:
    mod = _load_module()
    report = SimpleNamespace(
        to_dict=lambda: {
            "schema_version": "escape-top-greenfield-full-backtest-v1",
            "data_manifest_id": "manifest-a",
            "requested_start": "2018-01-01",
            "requested_end": "2026-07-10",
            "simulation": {"metrics": {"cagr": 0.1}, "turnover": 2.0},
            "rows": [],
        }
    )

    payload = mod.build_source_payload(report, _evidence(), config_source="/live/config.json")

    assert payload["evidence_schema"] == "current-baseline-source-v1"
    assert payload["provenance"]["worktree_clean"] is True
    assert payload["provenance"]["end"] == "2026-07-10"
    assert payload["config_source"] == "/live/config.json"

    bad = dict(_evidence(), manifest_id="different")
    with pytest.raises(ValueError, match="manifest"):
        mod.build_source_payload(report, bad, config_source="/live/config.json")


def test_latest_history_date_uses_last_valid_close() -> None:
    mod = _load_module()
    frame = pd.DataFrame(
        {"Close": [100.0, 101.0, float("nan")]},
        index=pd.to_datetime(["2026-07-08", "2026-07-09", "2026-07-10"]),
    )

    assert mod.latest_history_date(frame) == "2026-07-09"
    with pytest.raises(ValueError, match="history"):
        mod.latest_history_date(pd.DataFrame())


def test_run_refuses_dirty_research_code_before_backtest(tmp_path, monkeypatch) -> None:
    mod = _load_module()
    called = {"backtest": False}
    monkeypatch.setattr(mod, "research_worktree_clean", lambda repo_root=mod.REPO_ROOT: False)

    def should_not_run(*args, **kwargs):
        called["backtest"] = True
        raise AssertionError("backtest should not start")

    monkeypatch.setattr(mod, "run_full_backtest", should_not_run)

    with pytest.raises(RuntimeError, match="committed and clean"):
        mod.run(output_dir=tmp_path)
    assert called["backtest"] is False


def test_run_writes_effective_config_snapshot(tmp_path, monkeypatch) -> None:
    mod = _load_module()
    config = {"features": {"use_indicator_cache": True, "use_fred_vintage_pit": False}}
    report = SimpleNamespace(
        to_dict=lambda: {
            "schema_version": "escape-top-greenfield-full-backtest-v1",
            "data_manifest_id": "manifest-a",
            "requested_start": "2018-01-01",
            "requested_end": "2026-07-10",
            "effective_start": "2018-01-02",
            "effective_end": "2026-07-10",
            "simulation": {
                "metrics": {"cagr": 0.1},
                "turnover": 2.0,
                "equity_curve": {"2018-01-02": 100.0},
            },
            "rows": [],
        }
    )
    monkeypatch.setattr(mod, "research_worktree_clean", lambda repo_root=mod.REPO_ROOT: True)
    monkeypatch.setattr(mod, "build_baseline_config", lambda path: config)
    monkeypatch.setattr(
        mod,
        "LocalStore",
        lambda cfg: SimpleNamespace(
            load_history=lambda symbol: pd.DataFrame(
                {"Close": [100.0]}, index=pd.to_datetime(["2026-07-10"])
            )
        ),
    )
    monkeypatch.setattr(mod, "cache_evidence", lambda *args, **kwargs: _evidence())
    monkeypatch.setattr(mod, "run_full_backtest", lambda **kwargs: report)

    mod.run(output_dir=tmp_path, end="2026-07-10")

    assert json.loads((tmp_path / "CURRENT_BASELINE_CONFIG.json").read_text()) == config
    source_bytes = (tmp_path / "CURRENT_BASELINE_FULL.json").read_bytes()
    assert gzip.decompress((tmp_path / "CURRENT_BASELINE_FULL.json.gz").read_bytes()) == source_bytes


def test_deterministic_gzip_is_byte_identical() -> None:
    mod = _load_module()
    payload = b'{"evidence":"current"}\n'

    assert mod.deterministic_gzip(payload) == mod.deterministic_gzip(payload)
    assert gzip.decompress(mod.deterministic_gzip(payload)) == payload


def test_baseline_config_must_match_the_approved_live_policy(tmp_path, monkeypatch) -> None:
    mod = _load_module()
    repo_config = json.loads(
        (REPO_ROOT / "src/hermes_escape_top/config/config.json").read_text()
    )
    live_config = copy.deepcopy(repo_config)
    for feature in (
        "use_btc_spot_witness",
        "use_cboe_official_indices",
        "use_market_admission_gate",
    ):
        live_config["features"][feature] = True

    def semantic_sha256(value):
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    repo_path = tmp_path / "repo.json"
    live_path = tmp_path / "live.json"
    policy_path = tmp_path / "policy.json"
    repo_path.write_text(json.dumps(repo_config))
    live_path.write_text(json.dumps(live_config))
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": "hermes-approved-live-config-v1",
                "repo_config_semantic_sha256": semantic_sha256(repo_config),
                "live_config_semantic_sha256": semantic_sha256(live_config),
                "approved_feature_diff": {
                    feature: {"repo": False, "live": True}
                    for feature in (
                        "use_btc_spot_witness",
                        "use_cboe_official_indices",
                        "use_market_admission_gate",
                    )
                },
                "required_values": {"ibkr.readonly": True},
            }
        )
    )
    monkeypatch.setattr(mod, "CONFIG_PATH", repo_path)
    monkeypatch.setattr(mod, "APPROVED_LIVE_POLICY_PATH", policy_path, raising=False)

    approved = mod.build_baseline_config(live_path)
    assert approved["features"]["use_market_admission_gate"] is True
    assert approved["features"]["use_indicator_cache"] is True

    live_config["routing"]["defcon2"]["brkb_corr_threshold"] = 0.123
    live_path.write_text(json.dumps(live_config))
    with pytest.raises(ValueError, match="policy|approved|semantic"):
        mod.build_baseline_config(live_path)
