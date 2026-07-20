from __future__ import annotations

import pytest

from hermes_escape_top.governance.live_config_policy import (
    LiveConfigPolicyError,
    semantic_sha256,
    validate_repository_policy,
)


def test_repository_policy_rejects_feature_diff_with_wrong_repo_side() -> None:
    repo_config = {
        "features": {"approved_flag": False},
        "ibkr": {"readonly": True},
    }
    policy = {
        "schema_version": "hermes-approved-live-config-v1",
        "repo_config_semantic_sha256": semantic_sha256(repo_config),
        "live_config_semantic_sha256": "a" * 64,
        "approved_feature_diff": {
            "approved_flag": {"repo": True, "live": False}
        },
        "required_values": {"ibkr.readonly": True},
    }

    with pytest.raises(LiveConfigPolicyError, match="repo side"):
        validate_repository_policy(repo_config, policy)
