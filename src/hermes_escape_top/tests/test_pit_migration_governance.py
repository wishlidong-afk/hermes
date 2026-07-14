from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ADR = ROOT / "docs" / "adr" / "ADR-001-pit-data-correctness-migrations.md"


def test_pit_migration_adr_defines_a_separate_non_alpha_gate():
    text = ADR.read_text(encoding="utf-8")

    assert "Status: Accepted" in text
    assert "Alpha Experiment Gate" in text
    assert "Data-Correctness Migration Gate" in text
    assert "Positive alpha is not a pass criterion" in text
    assert "MIGRATION_APPROVED" in text
    assert "MIGRATION_BLOCKED" in text
    assert "hermes-formal-gate-v2" in text
    assert "governance_lane" in text
    assert "MIGRATION_IMPACT_RECORDED / NO_FLIP" in text
    assert "baseline" in text.lower()
    assert "human" in text.lower()


def test_pit_migration_policy_does_not_retroactively_authorize_fred_candidate():
    adr = ADR.read_text(encoding="utf-8")
    registry = (ROOT / "docs" / "FLAG_REGISTRY.md").read_text(encoding="utf-8")
    runbook = (ROOT / "docs" / "PRODUCTION_RUNBOOK.md").read_text(encoding="utf-8")

    assert "fred-vintage-pit-v1" in adr
    assert "NO_FLIP" in adr
    assert "fred-vintage-pit-v1" in registry
    assert "Rejected" in registry
    assert "ADR-001-pit-data-correctness-migrations.md" in runbook
