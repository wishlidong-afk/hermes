from __future__ import annotations

from hermes_escape_top.core.routing.portfolio_routes import (
    apply_route_set_transition_buffer,
)


CONFIG = {
    "features": {"use_route_set_transition_buffer": True},
    "symbols": {
        "MSTR": {"sleeve_cap": 0.15},
        "FNGU": {"sleeve_cap": 0.20},
        "SOXL": {"sleeve_cap": 0.30},
    },
}


def test_flag_off_is_exact_identity() -> None:
    current = {"BOXX": 0.63, "MSTR": 0.15, "IAU": 0.019, "SOXL": 0.201}
    previous = {"BOXX": 0.649, "MSTR": 0.15, "SOXL": 0.201}
    config = {**CONFIG, "features": {"use_route_set_transition_buffer": False}}

    result = apply_route_set_transition_buffer(config, current, previous)

    assert result.weights == current
    assert result.to_dict() == {
        "applied": False,
        "reason": "flag_off",
        "changed_leg": None,
        "direction": None,
        "threshold": 0.02,
        "raw_weights": current,
        "weights": current,
    }


def test_suppresses_only_added_small_non_risk_leg() -> None:
    previous = {"BOXX": 0.65, "MSTR": 0.15, "SOXL": 0.20}
    current = {"BOXX": 0.631, "MSTR": 0.15, "SOXL": 0.20, "IAU": 0.019}

    result = apply_route_set_transition_buffer(CONFIG, current, previous)

    assert result.applied is True
    assert result.changed_leg == "IAU"
    assert result.direction == "added"
    assert result.weights == {"BOXX": 0.65, "MSTR": 0.15, "SOXL": 0.2}


def test_preserves_hard_exit_and_risk_reduction_weights() -> None:
    previous = {"BOXX": 0.45, "MSTR": 0.15, "FNGU": 0.20, "SOXL": 0.20}
    current = {"BOXX": 0.731, "SOXL": 0.25, "IAU": 0.019}

    result = apply_route_set_transition_buffer(CONFIG, current, previous)

    assert result.applied is True
    assert result.weights.get("IAU", 0.0) == 0.0
    assert result.weights.get("MSTR", 0.0) == current.get("MSTR", 0.0)
    assert result.weights.get("FNGU", 0.0) == current.get("FNGU", 0.0)
    assert result.weights["SOXL"] == current["SOXL"]


def test_keeps_sole_removed_small_non_risk_leg_using_boxx() -> None:
    previous = {"BOXX": 0.631, "MSTR": 0.15, "SOXL": 0.20, "IAU": 0.019}
    current = {"BOXX": 0.65, "MSTR": 0.15, "SOXL": 0.20}

    result = apply_route_set_transition_buffer(CONFIG, current, previous)

    assert result.applied is True
    assert result.changed_leg == "IAU"
    assert result.direction == "removed"
    assert result.weights == previous


def test_does_not_suppress_multiple_route_set_changes_or_two_percent_leg() -> None:
    previous = {"BOXX": 0.65, "MSTR": 0.15, "SOXL": 0.20}
    multiple = {"BOXX": 0.62, "MSTR": 0.15, "SOXL": 0.20, "IAU": 0.01, "DBMF": 0.02}
    exactly_two_percent = {"BOXX": 0.63, "MSTR": 0.15, "SOXL": 0.20, "IAU": 0.02}

    assert apply_route_set_transition_buffer(CONFIG, multiple, previous).weights == multiple
    assert apply_route_set_transition_buffer(CONFIG, exactly_two_percent, previous).weights == exactly_two_percent


def test_missing_previous_portfolio_is_an_explicit_noop() -> None:
    current = {"BOXX": 0.65, "MSTR": 0.15, "SOXL": 0.20}

    result = apply_route_set_transition_buffer(CONFIG, current, None)

    assert result.applied is False
    assert result.reason == "no_previous_weights"
    assert result.weights == current
