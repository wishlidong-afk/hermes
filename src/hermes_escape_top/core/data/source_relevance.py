from __future__ import annotations

from typing import Any

from .external_sources.profiles import PROFILES, effective_source_profile

_DECISION_BEARING_ROLES = frozenset({"strategy", "hard_gate"})
_ROLE_PRIORITY = {
    "research": 0,
    "auxiliary": 1,
    "strategy": 2,
    "hard_gate": 3,
}


def source_is_decision_bearing(config: dict[str, Any], source_id: str) -> bool:
    """Return whether an enabled source can affect strategy readiness."""
    profile = effective_source_profile(config, source_id)
    return bool(
        profile is not None
        and profile.active
        and profile.decision_role in _DECISION_BEARING_ROLES
    )


def source_refresh_lane(config: dict[str, Any], source_id: str) -> str:
    """Classify a source as decision, shadow, or explicit/manual refresh."""
    profile = effective_source_profile(config, source_id)
    if profile is None or not profile.active:
        return "manual"
    if profile.decision_role in _DECISION_BEARING_ROLES:
        return "decision"
    return "shadow"


def soft_record_decision_role(config: dict[str, Any], record_name: str) -> str:
    """Resolve a soft record role, defaulting unknown records to strategy."""
    name = str(record_name)
    direct = effective_source_profile(config, name)
    if direct is not None:
        return direct.decision_role

    matches = [
        effective_source_profile(config, source_id)
        for source_id, profile in PROFILES.items()
        if name in profile.soft_record_names
    ]
    resolved = [profile for profile in matches if profile is not None]
    active = [profile for profile in resolved if profile.active]
    candidates = active or resolved
    if not candidates:
        return "strategy"
    return max(
        candidates,
        key=lambda profile: _ROLE_PRIORITY[profile.decision_role],
    ).decision_role
