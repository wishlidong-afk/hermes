from __future__ import annotations


def assert_not_more_aggressive(
    reference_target_weight: float,
    proposed_target_weight: float,
    sleeve_cap_after_sell: float | None = None,
) -> None:
    ceiling = float(reference_target_weight)
    if sleeve_cap_after_sell is not None:
        ceiling = min(ceiling, float(sleeve_cap_after_sell))
    if float(proposed_target_weight) > ceiling + 1e-12:
        raise AssertionError(
            f"target weight became more aggressive: proposed={proposed_target_weight:.8f}, ceiling={ceiling:.8f}"
        )
