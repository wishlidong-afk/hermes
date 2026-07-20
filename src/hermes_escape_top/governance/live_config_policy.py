"""Validate the committed desired state for the effective live configuration."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo


POLICY_SCHEMA = "hermes-approved-live-config-v1"
ATTESTATION_SCHEMA = "hermes-live-config-attestation-v2"


class LiveConfigPolicyError(ValueError):
    """The observed config is not the repository-approved live state."""


def semantic_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def boolean_feature_diff(
    repo_config: Mapping[str, Any],
    live_config: Mapping[str, Any],
) -> dict[str, dict[str, bool]]:
    repo_features = repo_config.get("features") or {}
    live_features = live_config.get("features") or {}
    if not isinstance(repo_features, Mapping) or not isinstance(live_features, Mapping):
        raise LiveConfigPolicyError("config features must be objects")
    result: dict[str, dict[str, bool]] = {}
    for key in sorted(set(repo_features) | set(live_features)):
        repo_value = repo_features.get(key, False)
        live_value = live_features.get(key, False)
        if not isinstance(repo_value, bool) or not isinstance(live_value, bool):
            raise LiveConfigPolicyError(f"feature {key} must be boolean")
        if live_value != repo_value:
            result[str(key)] = {"live": live_value, "repo": repo_value}
    return result


def load_policy(path: Path) -> dict[str, Any]:
    try:
        policy = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LiveConfigPolicyError(f"live config policy unreadable: {path}: {exc}") from exc
    if not isinstance(policy, dict) or policy.get("schema_version") != POLICY_SCHEMA:
        raise LiveConfigPolicyError(f"invalid live config policy schema: {path}")
    return policy


def validate_repository_policy(
    repo_config: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    observed = semantic_sha256(repo_config)
    expected = str(policy.get("repo_config_semantic_sha256") or "")
    if observed != expected:
        raise LiveConfigPolicyError(
            "repository config is not bound by live config policy "
            f"observed={observed} approved={expected or 'MISSING'}"
        )
    _validate_required_values(repo_config, policy)
    _validate_approved_feature_diff(policy)
    repo_features = repo_config.get("features") or {}
    for key, row in (policy.get("approved_feature_diff") or {}).items():
        repo_value = repo_features.get(key, False)
        if repo_value != row["repo"]:
            raise LiveConfigPolicyError(
                f"approved feature diff {key} repo side is {row['repo']!r}, "
                f"current repository default is {repo_value!r}"
            )


def validate_configs(
    repo_config: Mapping[str, Any],
    live_config: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, dict[str, bool]]:
    validate_repository_policy(repo_config, policy)
    observed_live = semantic_sha256(live_config)
    expected_live = str(policy.get("live_config_semantic_sha256") or "")
    if observed_live != expected_live:
        raise LiveConfigPolicyError(
            "live config policy semantic sha256 mismatch "
            f"observed={observed_live} approved={expected_live or 'MISSING'}"
        )
    observed_diff = boolean_feature_diff(repo_config, live_config)
    approved_diff = policy.get("approved_feature_diff")
    if observed_diff != approved_diff:
        raise LiveConfigPolicyError(
            "live config policy feature diff mismatch "
            f"observed={json.dumps(observed_diff, sort_keys=True)} "
            f"approved={json.dumps(approved_diff, sort_keys=True)}"
        )
    _validate_required_values(live_config, policy)
    return observed_diff


def validate_attestation(
    live_config: Mapping[str, Any],
    policy: Mapping[str, Any],
    attestation: Mapping[str, Any],
    *,
    policy_path: Path,
) -> None:
    if attestation.get("schema_version") != ATTESTATION_SCHEMA:
        raise LiveConfigPolicyError("live config attestation is not policy-bound v2")
    expected_policy_hash = file_sha256(policy_path)
    if str(attestation.get("policy_sha256") or "") != expected_policy_hash:
        raise LiveConfigPolicyError("live config policy hash differs from attestation")
    observed_live = semantic_sha256(live_config)
    approved_live = str(policy.get("live_config_semantic_sha256") or "")
    if observed_live != approved_live:
        raise LiveConfigPolicyError(
            "live config is not approved by policy "
            f"observed={observed_live} approved={approved_live or 'MISSING'}"
        )
    if str(attestation.get("live_config_semantic_sha256") or "") != observed_live:
        raise LiveConfigPolicyError("attested live semantic sha256 mismatch")
    approved_repo = str(policy.get("repo_config_semantic_sha256") or "")
    if str(attestation.get("repo_config_semantic_sha256") or "") != approved_repo:
        raise LiveConfigPolicyError("attested repository semantic sha256 mismatch")
    if attestation.get("feature_diff") != policy.get("approved_feature_diff"):
        raise LiveConfigPolicyError("attested feature diff is not repository-approved")
    _validate_required_values(live_config, policy)


def build_attestation(
    *,
    repo_path: Path,
    live_path: Path,
    policy_path: Path,
    release_id: str,
    release_hash: str,
    prior_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    repo_bytes = Path(repo_path).read_bytes()
    live_bytes = Path(live_path).read_bytes()
    repo = json.loads(repo_bytes)
    live = json.loads(live_bytes)
    policy = load_policy(policy_path)
    diff = validate_configs(repo, live, policy)
    observed_at = now or datetime.now(timezone.utc)
    generated_at = observed_at.isoformat(timespec="seconds")
    prior: Mapping[str, Any] = {}
    if prior_path is not None:
        try:
            value = json.loads(Path(prior_path).read_text(encoding="utf-8"))
            prior = value if isinstance(value, Mapping) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
    active_since = str(prior.get("retention_policy_active_since") or generated_at)
    first_expected = str(prior.get("retention_first_expected_at") or "")
    if not first_expected:
        local = observed_at.astimezone(ZoneInfo("Asia/Shanghai"))
        days_until_sunday = (6 - local.weekday()) % 7
        candidate = datetime.combine(
            local.date() + timedelta(days=days_until_sunday),
            time(8, 35),
            tzinfo=ZoneInfo("Asia/Shanghai"),
        )
        if candidate <= local:
            candidate += timedelta(days=7)
        first_expected = candidate.isoformat(timespec="seconds")
    live_features = live.get("features") or {}
    return {
        "schema_version": ATTESTATION_SCHEMA,
        "generated_at": generated_at,
        "release_id": str(release_id),
        "release_hash": str(release_hash),
        "live_config_sha256": hashlib.sha256(live_bytes).hexdigest(),
        "repo_config_sha256": hashlib.sha256(repo_bytes).hexdigest(),
        "live_config_semantic_sha256": semantic_sha256(live),
        "repo_config_semantic_sha256": semantic_sha256(repo),
        "policy_sha256": file_sha256(policy_path),
        "feature_diff": diff,
        "live_enabled_features": sorted(
            key for key, value in live_features.items() if value is True
        ),
        "retention_policy_active_since": active_since,
        "retention_first_expected_at": first_expected,
    }


def write_attestation(path: Path, payload: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def _validate_approved_feature_diff(policy: Mapping[str, Any]) -> None:
    value = policy.get("approved_feature_diff")
    if not isinstance(value, Mapping):
        raise LiveConfigPolicyError("approved_feature_diff must be an object")
    for key, row in value.items():
        if not isinstance(key, str) or not isinstance(row, Mapping):
            raise LiveConfigPolicyError("approved feature diff rows must be objects")
        if set(row) != {"live", "repo"} or not all(
            isinstance(row[name], bool) for name in ("live", "repo")
        ):
            raise LiveConfigPolicyError(f"approved feature diff {key} must contain booleans")
        if row["live"] == row["repo"]:
            raise LiveConfigPolicyError(f"approved feature diff {key} is not a difference")


def _validate_required_values(
    config: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    required = policy.get("required_values")
    if not isinstance(required, Mapping) or not required:
        raise LiveConfigPolicyError("live config policy required_values must be non-empty")
    for dotted_path, expected in required.items():
        current: Any = config
        for part in str(dotted_path).split("."):
            if not isinstance(current, Mapping) or part not in current:
                raise LiveConfigPolicyError(f"required config value missing: {dotted_path}")
            current = current[part]
        if current != expected:
            raise LiveConfigPolicyError(
                f"required config value {dotted_path}={current!r}, expected {expected!r}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    attest = subparsers.add_parser("attest")
    attest.add_argument("--repo", required=True, type=Path)
    attest.add_argument("--live", required=True, type=Path)
    attest.add_argument("--policy", required=True, type=Path)
    attest.add_argument("--output", required=True, type=Path)
    attest.add_argument("--prior", type=Path)
    attest.add_argument("--release-id", required=True)
    attest.add_argument("--release-hash", required=True)
    args = parser.parse_args()
    try:
        payload = build_attestation(
            repo_path=args.repo,
            live_path=args.live,
            policy_path=args.policy,
            prior_path=args.prior,
            release_id=args.release_id,
            release_hash=args.release_hash,
        )
        write_attestation(args.output, payload)
    except (LiveConfigPolicyError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"live config policy ERROR: {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
