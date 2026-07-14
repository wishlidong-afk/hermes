from datetime import date

from hermes_escape_top.core.data.external_sources import profiles


def _effective_source_profile(config, source_id):
    function = getattr(profiles, "effective_source_profile", None)
    assert callable(function), "effective_source_profile must be implemented"
    return function(config, source_id)


def test_effective_profile_uses_config_slo_as_single_runtime_truth():
    config = {
        "soft_data_slo": {
            "default_max_age_days": 13,
            "max_age_days": {"dollar": 6},
        }
    }

    profile = _effective_source_profile(config, "dollar")

    assert profile is not None
    assert profile.max_age_days == 6
    assert profile.warn_age_days == 4
    assert profile.feature_flag == "data_dollar"
    assert profile.decision_weight == 4.0
    assert profile.automation_mode == "api"


def test_naaim_profile_declares_subscription_migration_deadline():
    profile = _effective_source_profile({}, "naaim_exposure")

    assert profile is not None
    assert profile.automation_mode == "official_file"
    assert profile.migration_deadline == "2026-08-01"
    assert profile.pit_rule == "issue_date_plus_one_day"


def test_profile_default_slo_comes_from_config_default():
    config = {"soft_data_slo": {"default_max_age_days": 17}}

    profile = _effective_source_profile(config, "aaii_sentiment")

    assert profile is not None
    assert profile.max_age_days == 17
    assert profile.warn_age_days == 15


def test_disabled_research_source_is_not_active_for_daily_readiness():
    config = {
        "features": {"data_cot_nq": False},
        "soft_data_slo": {"default_max_age_days": 13},
    }

    profile = _effective_source_profile(config, "cot_nq")

    assert profile is not None
    assert profile.active is False
    assert profile.decision_weight == 4.0


def test_btc_micro_remains_active_when_legacy_flag_is_absent():
    profile = _effective_source_profile(
        {"features": {}, "soft_data_slo": {"default_max_age_days": 13}},
        "btc_funding_basis",
    )

    assert profile is not None
    assert profile.active is True


def test_fred_vintage_policy_is_inactive_by_default_and_exact_when_enabled():
    disabled = _effective_source_profile({"features": {}}, "fred_vintages")
    enabled_config = {"features": {"use_fred_vintage_pit": True}}
    enabled = _effective_source_profile(enabled_config, "fred_vintages")
    dollar = _effective_source_profile(enabled_config, "dollar")

    assert disabled is not None
    assert disabled.active is False
    assert enabled is not None
    assert enabled.active is True
    assert enabled.decision_weight == 0.0
    assert enabled.pit_rule == "exact_realtime_start_vintage"
    assert dollar is not None
    assert dollar.primary == "FRED/ALFRED exact vintage event store"
    assert dollar.pit_rule == "exact_realtime_start_vintage"


def test_naaim_status_marks_subscription_migration_due_before_deadline():
    profile = _effective_source_profile({}, "naaim_exposure")

    row = profiles.enrich_source_status(
        {
            "source_id": "naaim_exposure",
            "status": "OK",
            "latest_promoted_as_of": "2026-07-09",
        },
        today=date(2026, 7, 13),
        profile=profile,
    )

    assert row["migration_status"] == "MIGRATION_DUE"
    assert row["migration_deadline"] == "2026-08-01"


def test_aaii_requires_action_only_when_overdue_without_official_artifact():
    profile = _effective_source_profile({}, "aaii_sentiment")
    fresh = profiles.enrich_source_status(
        {"source_id": "aaii_sentiment", "status": "OK", "latest_promoted_as_of": "2026-07-09"},
        today=date(2026, 7, 13),
        profile=profile,
        official_artifact_ready=False,
    )
    overdue = profiles.enrich_source_status(
        {"source_id": "aaii_sentiment", "status": "OK", "latest_promoted_as_of": "2026-06-20"},
        today=date(2026, 7, 13),
        profile=profile,
        official_artifact_ready=False,
    )
    staged = profiles.enrich_source_status(
        {"source_id": "aaii_sentiment", "status": "OK", "latest_promoted_as_of": "2026-06-20"},
        today=date(2026, 7, 13),
        profile=profile,
        official_artifact_ready=True,
    )

    assert fresh["migration_status"] == "MONITORED"
    assert overdue["migration_status"] == "ACTION_REQUIRED"
    assert staged["migration_status"] == "OFFICIAL_FILE_READY"
