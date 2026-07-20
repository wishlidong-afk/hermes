from datetime import date

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.external_sources import profiles


def _effective_source_profile(config, source_id):
    function = getattr(profiles, "effective_source_profile", None)
    assert callable(function), "effective_source_profile must be implemented"
    return function(config, source_id)


def test_every_external_source_declares_a_decision_role():
    allowed = {"strategy", "hard_gate", "auxiliary", "research"}

    assert profiles.PROFILES
    assert {
        source_id: profile.decision_role
        for source_id, profile in profiles.PROFILES.items()
        if profile.decision_role not in allowed
    } == {}
    assert profiles.PROFILES["fred_vintages"].decision_role == "hard_gate"
    assert profiles.PROFILES["dollar"].decision_role == "strategy"
    assert profiles.PROFILES["cboe_vix9d"].decision_role == "auxiliary"
    assert profiles.PROFILES["btc_funding_basis"].decision_role == "research"


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
    assert profile.automation_mode == "subscriber_or_official_file"
    assert profile.migration_deadline == "2026-08-01"
    assert profile.pit_rule == "issue_date_plus_one_day"


def test_profile_default_slo_comes_from_config_default():
    config = {"soft_data_slo": {"default_max_age_days": 17}}

    profile = _effective_source_profile(config, "aaii_sentiment")

    assert profile is not None
    assert profile.max_age_days == 17
    assert profile.warn_age_days == 15


def test_aaii_profile_declares_official_rss_automation_with_file_fallback():
    profile = _effective_source_profile({}, "aaii_sentiment")

    assert profile is not None
    assert profile.automation_mode == "official_rss_with_file_fallback"
    assert "Insights RSS" in profile.primary
    assert "official file import" in profile.fallback


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
    exact_sources = {
        source_id: _effective_source_profile(enabled_config, source_id)
        for source_id in (
            "dollar_vintage",
            "real_rate_vintage",
            "fred_net_liquidity_vintage",
        )
    }
    assert all(profile is not None and profile.active for profile in exact_sources.values())
    assert exact_sources["dollar_vintage"].slo_key == "dollar"
    assert exact_sources["real_rate_vintage"].slo_key == "real_rate"
    assert exact_sources["fred_net_liquidity_vintage"].slo_key == "net_liquidity"
    assert {profile.pit_rule for profile in exact_sources.values()} == {
        "exact_realtime_start_vintage"
    }


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


def test_registry_is_the_single_source_for_refresh_sets_and_policy_fields():
    config = load_config()
    legacy = profiles.configured_refresh_source_ids(config)

    assert legacy[:3] == ("dollar", "real_rate", "fred_net_liquidity")
    assert "fred_vintages" not in legacy
    assert "aaii_sentiment" in legacy
    assert "naaim_exposure" in legacy

    exact_config = {**config, "features": {**config["features"], "use_fred_vintage_pit": True}}
    exact = profiles.configured_refresh_source_ids(exact_config)
    assert exact[:4] == (
        "fred_vintages",
        "dollar_vintage",
        "real_rate_vintage",
        "fred_net_liquidity_vintage",
    )
    assert "dollar" not in exact
    assert "real_rate" not in exact
    assert "fred_net_liquidity" not in exact

    for source_id in profiles.all_source_ids():
        profile = profiles.profile_for(source_id)
        assert profile is not None
        assert profile.label
        assert profile.cadence
        assert profile.publication_schedule
        assert profile.grace_days >= 0
        assert profile.max_age_days >= profile.warn_age_days
        assert profile.primary
        assert profile.fallback
        assert profile.pit_rule
        assert profile.refresh_group in {"legacy_fred", "exact_fred", "common", "cboe_indices"}
        assert profile.refresh_order >= 0


def test_registry_drives_import_and_display_metadata():
    assert set(profiles.import_source_ids()) == {"aaii_sentiment", "naaim_exposure"}
    display = profiles.display_source_ids()
    assert display.index("fred_vintages") < display.index("aaii_sentiment")
    assert profiles.profile_for("cboe_skew").label == "CBOE SKEW"
