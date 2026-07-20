from __future__ import annotations

from typing import Any


class ProvenanceError(ValueError):
    pass


def source_provenance(
    source: str,
    *,
    primary_source: str | None = None,
    fallback_used: bool | None = None,
    primary_failure: str | None = None,
) -> dict[str, Any]:
    """Return the common evidence contract for an external-source fetch."""
    selected = str(source).strip()
    if not selected:
        raise ProvenanceError("external source provenance requires a selected source")
    primary = str(primary_source or selected).strip()
    failure = str(primary_failure or "").strip() or None
    fallback = (
        bool(fallback_used)
        if fallback_used is not None
        else bool(failure or selected != primary)
    )
    if fallback and failure is None:
        raise ProvenanceError(
            "fallback provenance requires the primary_failure reason"
        )
    if not fallback and selected != primary:
        raise ProvenanceError(
            "selected source differs from primary_source but fallback_used is false"
        )
    if not fallback and failure is not None:
        raise ProvenanceError(
            "primary_failure requires fallback_used=true"
        )
    return {
        "source": selected,
        "primary_source": primary,
        "fallback_used": fallback,
        "primary_failure": failure,
    }
