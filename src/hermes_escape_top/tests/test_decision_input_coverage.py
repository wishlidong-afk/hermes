from __future__ import annotations

from hermes_escape_top.core.data.quality import decision_input_coverage


def test_decision_input_coverage_uses_scored_missing_weight() -> None:
    coverage = decision_input_coverage(
        {
            "MSTR": {
                "missing_weight": 10.0,
                "confidence_missing_weight": 4.0,
                "blind_spot": False,
            },
            "FNGU": {"missing_weight": 0.0, "confidence_missing_weight": 0.0},
        }
    )

    assert coverage["status"] == "HIGH"
    assert coverage["coverage_score"] == 98.0
    assert coverage["active_weight"] == 200.0
    assert coverage["missing_weight"] == 4.0
    assert coverage["symbols"]["MSTR"]["coverage_score"] == 96.0


def test_decision_input_coverage_falls_back_to_legacy_missing_weight() -> None:
    coverage = decision_input_coverage({"SOXL": {"missing_weight": 12.0}})

    assert coverage["coverage_score"] == 88.0
    assert coverage["symbols"]["SOXL"]["missing_weight"] == 12.0


def test_decision_input_coverage_is_unknown_without_scores() -> None:
    coverage = decision_input_coverage({})

    assert coverage == {
        "status": "UNKNOWN",
        "coverage_score": None,
        "active_weight": 0.0,
        "available_weight": 0.0,
        "missing_weight": 0.0,
        "symbol_count": 0,
        "symbols": {},
    }
