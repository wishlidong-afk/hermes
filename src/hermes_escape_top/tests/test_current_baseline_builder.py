from __future__ import annotations

import importlib.util
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
