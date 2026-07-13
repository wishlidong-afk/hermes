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
