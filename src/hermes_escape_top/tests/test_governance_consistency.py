from __future__ import annotations

import importlib.util
import gzip
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "check_governance_consistency.py"


def _module():
    spec = importlib.util.spec_from_file_location("check_governance_consistency", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_registry_parser_reads_on_and_off_defaults():
    module = _module()
    markdown = """
| Flag | Default | Status | What it gates |
|---|---|---|---|
| `flag_on` | **ON** ✅ | live | unit |
| `flag_off` | OFF | candidate | unit |
"""

    assert module.parse_registry_defaults(markdown) == {"flag_on": True, "flag_off": False}


def test_repository_governance_evidence_matches_config_and_baseline():
    module = _module()

    report = module.check_repository(ROOT)

    assert report["ok"], report["errors"]
    assert report["checks"]["config_invariants"] == "OK"
    assert report["checks"]["flag_registry"] == "OK"
    assert report["checks"]["context_snapshot"] == "OK"
    assert report["checks"]["baseline_metadata"] == "OK"
    assert report["checks"]["factor_capacity"] == "OK"
    assert report["checks"]["live_config_policy"] == "OK"


def test_stale_baseline_requires_explicit_labels_in_both_docs(tmp_path):
    module = _module()
    baseline = {
        "git_commit": "a" * 40,
        "equity_timing": "next_open",
        "evidence_status": "STALE",
        "metrics": {"cagr": 0.1, "max_drawdown": -0.2, "sharpe": 1.0},
    }
    baseline_doc = tmp_path / "BASELINE_CURRENT.md"
    gate_doc = tmp_path / "GATE_BASELINE_CURRENT.md"
    for path in (baseline_doc, gate_doc):
        path.write_text(
            f"{baseline['git_commit']} next_open 10.00% -20.00% 1.000\n",
            encoding="utf-8",
        )

    errors = module._baseline_errors(baseline, baseline_doc, gate_doc)

    assert any("STALE" in error for error in errors)

    for path in (baseline_doc, gate_doc):
        path.write_text(
            f"Status: **STALE**\n{baseline['git_commit']} next_open 10.00% -20.00% 1.000\n",
            encoding="utf-8",
        )
    assert module._baseline_errors(baseline, baseline_doc, gate_doc) == []


def test_baseline_source_evidence_accepts_matching_deterministic_archive(tmp_path):
    module = _module()
    source = b'{"rows":[{"as_of":"2026-07-14"}]}\n'
    artifact_dir = tmp_path / "building" / "reports" / "current_baseline"
    timing_dir = artifact_dir / "execution_timing"
    timing_dir.mkdir(parents=True)
    (artifact_dir / "CURRENT_BASELINE_FULL.json.gz").write_bytes(gzip.compress(source, mtime=0))
    (timing_dir / "EXECUTION_TIMING_SENSITIVITY.json").write_text(
        json.dumps({"source": {"sha256": hashlib.sha256(source).hexdigest()}}),
        encoding="utf-8",
    )

    assert module._baseline_source_errors(tmp_path) == []


def test_baseline_source_evidence_rejects_missing_or_mismatched_archive(tmp_path):
    module = _module()
    artifact_dir = tmp_path / "building" / "reports" / "current_baseline"
    timing_dir = artifact_dir / "execution_timing"
    timing_dir.mkdir(parents=True)
    (timing_dir / "EXECUTION_TIMING_SENSITIVITY.json").write_text(
        json.dumps({"source": {"sha256": "a" * 64}}),
        encoding="utf-8",
    )

    errors = module._baseline_source_errors(tmp_path)
    assert any("missing full provenance source" in error for error in errors)

    (artifact_dir / "CURRENT_BASELINE_FULL.json.gz").write_bytes(gzip.compress(b"wrong", mtime=0))
    errors = module._baseline_source_errors(tmp_path)
    assert any("sha256 mismatch" in error for error in errors)


def test_factor_capacity_governance_rejects_missing_or_stale_artifact(tmp_path):
    module = _module()
    config = {"module_caps": {"A": 20}, "features": {}, "symbols": {}}

    errors = module._factor_capacity_errors(tmp_path, config)
    assert any("missing" in error for error in errors)

    path = tmp_path / "building/reports/factor_capacity/FACTOR_CAPACITY_INVENTORY.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema_version": "stale"}), encoding="utf-8")
    errors = module._factor_capacity_errors(tmp_path, config)
    assert any("differs" in error for error in errors)
