from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "compare_pipeline_persistence.py"


def _module():
    spec = importlib.util.spec_from_file_location("compare_pipeline_persistence", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_recoverable_transaction_metadata_is_ignored_but_business_payload_is_strict(tmp_path):
    module = _module()
    baseline = {"as_of": "2026-07-10", "scores": {"MSTR": {"status": "EXIT"}}}
    candidate = {
        **baseline,
        "persistence": {
            "run_id": "random-run-id",
            "protocol": "recoverable-journal-v1",
            "recovered_run_id": None,
        },
    }

    assert module._normalize(baseline, tmp_path) == module._normalize(candidate, tmp_path)
    changed = {**candidate, "scores": {"MSTR": {"status": "HOLD"}}}
    assert module._normalize(baseline, tmp_path) != module._normalize(changed, tmp_path)


def test_comparator_includes_dated_soft_snapshot_as_business_evidence():
    module = _module()

    names = module._business_artifact_names("2026-05-29")

    assert "soft_adapter_snapshot_2026-05-29.json" in names
    assert len(names) == 7


def test_decision_quality_contract_allows_reporting_only_but_keeps_scores_strict():
    module = _module()
    baseline_payload = {
        "input_hash": "same-input",
        "scores": {"MSTR": {"status": "EXIT", "raw_score": 80.0}},
        "data_quality": {"overall_score": 92.2},
        "decision_layers": {
            "MSTR": {"strategy_confidence": {"score": 92.0}}
        },
    }
    candidate_payload = {
        **baseline_payload,
        "data_quality": {"overall_score": 93.4},
        "all_source_data_quality": {"overall_score": 92.2},
        "decision_layers": {
            "MSTR": {"strategy_confidence": {"score": 93.2}}
        },
    }
    baseline = {"payload": baseline_payload, "artifacts": {}}
    candidate = {"payload": candidate_payload, "artifacts": {}}

    assert module._contract_differences(
        baseline,
        candidate,
        contract="decision-quality-v1",
    ) == []

    changed = {
        "payload": {
            **candidate_payload,
            "scores": {"MSTR": {"status": "HOLD", "raw_score": 20.0}},
        },
        "artifacts": {},
    }
    assert module._contract_differences(
        baseline,
        changed,
        contract="decision-quality-v1",
    ) == ["payload"]


def test_evidence_tree_fingerprint_binds_relative_paths_and_file_bytes(tmp_path):
    module = _module()
    root = tmp_path / "seed"
    (root / "history").mkdir(parents=True)
    first = root / "history" / "MSTR.csv"
    first.write_text("date,Close\n2026-07-10,100\n", encoding="utf-8")

    before = module._tree_fingerprint(root, relative_roots=("history",))
    repeated = module._tree_fingerprint(root, relative_roots=("history",))
    first.write_text("date,Close\n2026-07-10,101\n", encoding="utf-8")
    after = module._tree_fingerprint(root, relative_roots=("history",))

    assert before == repeated
    assert before["file_count"] == 1
    assert before["files"][0]["path"] == "history/MSTR.csv"
    assert before["manifest_sha256"] != after["manifest_sha256"]
