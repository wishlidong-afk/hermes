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
_SOFT_RECORD_FEATURE_FLAGS = {
    "gex": "data_gex",
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


def soft_record_is_decision_bearing(
    config: dict[str, Any],
    record_name: str,
) -> bool:
    """Return whether a soft record is enabled and can affect a decision."""
    name = str(record_name)
    direct = effective_source_profile(config, name)
    matches = (
        [direct]
        if direct is not None
        else [
            effective_source_profile(config, source_id)
            for source_id, profile in PROFILES.items()
            if name in profile.soft_record_names
        ]
    )
    resolved = [profile for profile in matches if profile is not None]
    if resolved:
        return any(
            profile.active and profile.decision_role in _DECISION_BEARING_ROLES
            for profile in resolved
        )

    feature_flag = _SOFT_RECORD_FEATURE_FLAGS.get(name)
    if feature_flag is not None:
        return bool(((config or {}).get("features") or {}).get(feature_flag, False))
    return soft_record_decision_role(config, name) in _DECISION_BEARING_ROLES
