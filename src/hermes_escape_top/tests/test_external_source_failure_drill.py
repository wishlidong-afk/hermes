from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[3] / "ops" / "external_source_failure_drill.py"


def _module():
    assert SCRIPT.exists(), "external-source failure drill is not implemented"
    spec = importlib.util.spec_from_file_location("external_source_failure_drill", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_aaii_and_naaim_failure_drill_preserves_canonical_and_recovers(tmp_path: Path):
    module = _module()

    report = module.run_drill(tmp_path / "drill")

    assert report["schema"] == "hermes-external-source-failure-drill-v1"
    assert report["status"] == "PASS"
    assert report["network_used"] is False
    assert report["live_data_touched"] is False

    scenarios = {
        (row["source_id"], row["scenario"]): row
        for row in report["scenarios"]
    }
    assert set(scenarios) == {
        (source_id, scenario)
        for source_id in ("aaii_sentiment", "naaim_exposure")
        for scenario in (
            "primary_fetch_failure",
            "older_official_file",
            "wrong_issue_file",
            "manual_import_recovery",
        )
    }
    assert all(row["passed"] for row in scenarios.values())

    for source_id in ("aaii_sentiment", "naaim_exposure"):
        for scenario in (
            "primary_fetch_failure",
            "older_official_file",
            "wrong_issue_file",
        ):
            row = scenarios[(source_id, scenario)]
            assert row["canonical_unchanged"] is True
            assert row["ledger_written"] is True

        recovery = scenarios[(source_id, "manual_import_recovery")]
        assert recovery["actual_status"] == "OK"
        assert recovery["canonical_advanced"] is True
        assert recovery["ledger_written"] is True
        assert recovery["canonical_sha256"]
        assert recovery["official_file_sha256"]
