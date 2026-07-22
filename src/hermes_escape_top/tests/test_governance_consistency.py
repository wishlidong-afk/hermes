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
    assert report["checks"]["execution_open_quality"] == "OK"


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
    source = _write_authorized_baseline_source(tmp_path)
    artifact_dir = tmp_path / "building" / "reports" / "current_baseline"

    assert module._baseline_source_errors(tmp_path) == []


def test_baseline_source_evidence_rejects_missing_config_authorization(tmp_path):
    module = _module()
    source = _write_authorized_baseline_source(tmp_path)
    artifact_dir = tmp_path / "building" / "reports" / "current_baseline"
    payload = json.loads(source)
    payload.pop("config_authorization")
    tampered = (json.dumps(payload, sort_keys=True) + "\n").encode()
    (artifact_dir / "CURRENT_BASELINE_FULL.json.gz").write_bytes(
        gzip.compress(tampered, mtime=0)
    )
    _write_timing_sha(artifact_dir, tampered)
    timing_path = (
        artifact_dir / "execution_timing" / "EXECUTION_TIMING_SENSITIVITY.json"
    )
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    timing["source"]["path"] = "/tmp/CURRENT_BASELINE_FULL.json"
    timing_path.write_text(json.dumps(timing), encoding="utf-8")

    errors = module._baseline_source_errors(tmp_path)

    assert any("config authorization" in error for error in errors)
    assert any("source path" in error for error in errors)


def test_baseline_source_evidence_rejects_normalized_config_or_policy_drift(tmp_path):
    module = _module()
    _write_authorized_baseline_source(tmp_path)
    artifact_dir = tmp_path / "building" / "reports" / "current_baseline"
    config_path = artifact_dir / "CURRENT_BASELINE_CONFIG.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["features"]["use_indicator_cache"] = False
    config_path.write_text(json.dumps(config), encoding="utf-8")

    errors = module._baseline_source_errors(tmp_path)
    assert any("normalized config semantic sha256 mismatch" in error for error in errors)

    _write_authorized_baseline_source(tmp_path)
    policy_path = (
        tmp_path
        / "src"
        / "hermes_escape_top"
        / "governance"
        / "approved_live_config.json"
    )
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["live_config_semantic_sha256"] = "f" * 64
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    errors = module._baseline_source_errors(tmp_path)
    assert any("policy sha256 mismatch" in error for error in errors)


def test_baseline_source_evidence_rejects_nonretained_source_path(tmp_path):
    module = _module()
    _write_authorized_baseline_source(tmp_path)
    timing_path = (
        tmp_path
        / "building"
        / "reports"
        / "current_baseline"
        / "execution_timing"
        / "EXECUTION_TIMING_SENSITIVITY.json"
    )
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    timing["source"]["path"] = "/tmp/CURRENT_BASELINE_FULL.json"
    timing_path.write_text(json.dumps(timing), encoding="utf-8")

    errors = module._baseline_source_errors(tmp_path)

    assert any("source path" in error for error in errors)


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


def test_execution_open_quality_enforces_missing_and_modeled_budgets(tmp_path):
    module = _module()
    timing_path = (
        tmp_path
        / "building"
        / "reports"
        / "current_baseline"
        / "execution_timing"
        / "EXECUTION_TIMING_SENSITIVITY.json"
    )
    timing_path.parent.mkdir(parents=True)

    def write_quality(*, missing: int, modeled: int, total: int) -> None:
        timing_path.write_text(
            json.dumps(
                {
                    "open_quality": {
                        "required_missing_rows": missing,
                        "required_modeled_rows": modeled,
                        "required_total_rows": total,
                    }
                }
            ),
            encoding="utf-8",
        )

    write_quality(missing=0, modeled=13, total=100)
    assert module._execution_open_quality_errors(tmp_path) == []

    write_quality(missing=1, modeled=13, total=100)
    assert any(
        "required_missing_rows" in error
        for error in module._execution_open_quality_errors(tmp_path)
    )

    write_quality(missing=0, modeled=16, total=100)
    assert any(
        "modeled share" in error
        for error in module._execution_open_quality_errors(tmp_path)
    )


def test_execution_open_quality_fails_closed_on_missing_or_invalid_evidence(tmp_path):
    module = _module()
    assert any(
        "missing execution timing" in error
        for error in module._execution_open_quality_errors(tmp_path)
    )

    timing_path = (
        tmp_path
        / "building"
        / "reports"
        / "current_baseline"
        / "execution_timing"
        / "EXECUTION_TIMING_SENSITIVITY.json"
    )
    timing_path.parent.mkdir(parents=True)
    timing_path.write_text(json.dumps({"open_quality": {}}), encoding="utf-8")

    assert any(
        "invalid" in error
        for error in module._execution_open_quality_errors(tmp_path)
    )


def _semantic_sha256(value) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_timing_sha(artifact_dir: Path, source: bytes) -> None:
    timing_dir = artifact_dir / "execution_timing"
    timing_dir.mkdir(parents=True, exist_ok=True)
    (timing_dir / "EXECUTION_TIMING_SENSITIVITY.json").write_text(
        json.dumps(
            {
                "source": {
                    "path": "building/reports/current_baseline/CURRENT_BASELINE_FULL.json.gz",
                    "sha256": hashlib.sha256(source).hexdigest(),
                    "sha256_scope": "decompressed_json_payload",
                }
            }
        ),
        encoding="utf-8",
    )


def _write_authorized_baseline_source(root: Path) -> bytes:
    artifact_dir = root / "building" / "reports" / "current_baseline"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    policy_path = (
        root
        / "src"
        / "hermes_escape_top"
        / "governance"
        / "approved_live_config.json"
    )
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    repo_config = {
        "features": {"live_flag": False, "use_indicator_cache": False},
        "ibkr": {"readonly": True},
    }
    live_config = {
        "features": {"live_flag": True, "use_indicator_cache": False},
        "ibkr": {"readonly": True},
    }
    normalized_config = {
        "features": {"live_flag": True, "use_indicator_cache": True},
        "ibkr": {"readonly": True},
    }
    policy = {
        "schema_version": "hermes-approved-live-config-v1",
        "repo_config_semantic_sha256": _semantic_sha256(repo_config),
        "live_config_semantic_sha256": _semantic_sha256(live_config),
        "approved_feature_diff": {
            "live_flag": {"live": True, "repo": False}
        },
        "required_values": {"ibkr.readonly": True},
    }
    policy_bytes = (json.dumps(policy, sort_keys=True) + "\n").encode()
    policy_path.write_bytes(policy_bytes)
    (artifact_dir / "CURRENT_BASELINE_CONFIG.json").write_text(
        json.dumps(normalized_config), encoding="utf-8"
    )
    authorization = {
        "schema_version": "current-baseline-config-authorization-v1",
        "config_source": "/live/config.json",
        "raw_live_config_sha256": "a" * 64,
        "raw_live_config_semantic_sha256": _semantic_sha256(live_config),
        "repo_config_semantic_sha256": _semantic_sha256(repo_config),
        "policy_sha256": hashlib.sha256(policy_bytes).hexdigest(),
        "policy_schema_version": policy["schema_version"],
        "policy_approved_live_semantic_sha256": policy[
            "live_config_semantic_sha256"
        ],
        "policy_approved_repo_semantic_sha256": policy[
            "repo_config_semantic_sha256"
        ],
        "normalized_config_semantic_sha256": _semantic_sha256(normalized_config),
        "approved_feature_diff": policy["approved_feature_diff"],
        "normalization": {
            "use_indicator_cache": {
                "raw": False,
                "normalized": True,
                "reason": "byte-identical replay acceleration only",
            }
        },
    }
    source = (
        json.dumps(
            {
                "rows": [{"as_of": "2026-07-14"}],
                "config_authorization": authorization,
            },
            sort_keys=True,
        )
        + "\n"
    ).encode()
    (artifact_dir / "CURRENT_BASELINE_FULL.json.gz").write_bytes(
        gzip.compress(source, mtime=0)
    )
    _write_timing_sha(artifact_dir, source)
    return source
