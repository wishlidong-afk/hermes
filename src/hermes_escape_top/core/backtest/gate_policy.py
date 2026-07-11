"""Authorization policy for legacy research-gate diagnostics.

The legacy flag/routing scripts rank fixed variants on OOS folds. That number
is useful as a diagnostic, but it is not the PBO of an IS-selected research
process. Keep the diagnostics visible while preventing them from authorizing a
production flag flip until the formal gate replaces this policy.
"""
from __future__ import annotations

from typing import Any


LEGACY_RATE_LABEL = "OOS bottom-half rate (diagnostic)"
FORMAL_GATE_REASON = "formal IS->OOS PBO via scripts/formal_gate.py is required before authorization"


def assess_legacy_gate(
    *,
    beats_baseline: bool,
    bottom_half_rate: float,
    drawdown_ok: bool,
    evidence_status: str,
) -> dict[str, Any]:
    failures: list[str] = []
    if not beats_baseline:
        failures.append("OOS<=baseline")
    if bottom_half_rate >= 0.5:
        failures.append("bottom-half>=0.5")
    if not drawdown_ok:
        failures.append("MaxDD")

    legacy_checks = "MEETS LEGACY CHECKS"
    if failures:
        legacy_checks = f"FAILS LEGACY CHECKS ({', '.join(failures)})"

    reason = FORMAL_GATE_REASON
    if evidence_status != "FRESH":
        reason = f"{evidence_status.lower()} evidence; {reason}"
    return {
        "legacy_checks": legacy_checks,
        "authorization": "FROZEN",
        "reason": reason,
    }
