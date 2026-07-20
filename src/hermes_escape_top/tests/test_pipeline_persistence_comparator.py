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
