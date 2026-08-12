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
    assert profile.lifecycle_policy == "RETIRED_PAYWALL"
    assert profile.lifecycle_effective_date == "2026-08-01"
    assert profile.probe_weekdays == (4,)


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
    assert row["lifecycle_status"] == "ACTIVE"
    assert row["migration_deadline"] == "2026-08-01"


def test_naaim_status_retires_stale_public_channel_after_paywall_deadline():
    profile = _effective_source_profile({}, "naaim_exposure")

    row = profiles.enrich_source_status(
        {
            "source_id": "naaim_exposure",
            "status": "OK",
            "latest_promoted_as_of": "2026-07-29",
            "latest_source_channel": "naaim_public_workbook",
            "finished_at": "2026-08-12T22:45:00+00:00",
            "evidence_status": "MATCH",
        },
        today=date(2026, 8, 14),
        profile=profile,
    )

    assert row["freshness_status"] == "STALE"
    assert row["lifecycle_status"] == "RETIRED_PAYWALL"
    assert row["migration_status"] == "RETIRED_PAYWALL"
    assert row["probe_weekdays"] == [4]
    assert "certified history frozen" in row["next_action"]


def test_naaim_retirement_is_effective_on_2026_08_01():
    row = profiles.enrich_source_status(
        {
            "source_id": "naaim_exposure",
            "status": "OK",
            "latest_promoted_as_of": "2026-07-01",
            "latest_source_channel": "naaim_public_workbook",
            "finished_at": "2026-07-31T22:45:00+00:00",
            "evidence_status": "MATCH",
        },
        today=date(2026, 8, 1),
        profile=_effective_source_profile({}, "naaim_exposure"),
    )

    assert row["lifecycle_status"] == "RETIRED_PAYWALL"
    assert row["migration_status"] == "RETIRED_PAYWALL"


def test_naaim_verified_subscriber_supersedes_retired_public_channel():
    profile = _effective_source_profile({}, "naaim_exposure")

    row = profiles.enrich_source_status(
        {
            "source_id": "naaim_exposure",
            "status": "OK",
            "latest_promoted_as_of": "2026-08-12",
            "latest_source_channel": "naaim_subscriber",
            "finished_at": "2026-08-13T22:45:00+00:00",
            "evidence_status": "MATCH",
        },
        today=date(2026, 8, 14),
        profile=profile,
    )

    assert row["freshness_status"] == "OK"
    assert row["lifecycle_status"] == "ACTIVE_SUBSCRIBER"
    assert row["migration_status"] == "SUBSCRIBER_READY"


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


def test_registry_owns_soft_record_aliases_without_a_second_source_registry():
    assert profiles.profile_for("aaii_sentiment").soft_record_names == ("aaii",)
    assert profiles.profile_for("naaim_exposure").soft_record_names == ("naaim",)
    assert profiles.profile_for("fred_net_liquidity").soft_record_names == (
        "net_liquidity",
    )
    assert profiles.profile_for("cboe_equity_pcr").soft_record_names == (
        "cboe_pcr",
    )
    assert profiles.profile_for("btc_funding_basis").soft_record_names == (
        "btc_funding_basis",
    )
    assert "cboe_indices" in profiles.profile_for("cboe_vix").soft_record_names
    assert "cboe_indices" in profiles.profile_for("cboe_vix9d").soft_record_names


def test_soft_record_aliases_do_not_change_existing_status_payload_shape():
    payload = profiles.profile_for("aaii_sentiment").to_dict()

    assert "soft_record_names" not in payload


def test_fred_and_aaii_profiles_require_verified_publisher_calendars():
    expected = {
        "dollar": ("fred_release_calendar", ("17",)),
        "real_rate": ("fred_release_calendar", ("18",)),
        "fred_net_liquidity": ("fred_release_calendar", ("20", "379")),
        "aaii_sentiment": ("publisher_issue_sequence", ()),
    }

    for source_id, (policy, release_ids) in expected.items():
        profile = profiles.profile_for(source_id)
        assert profile is not None
        assert profile.expected_release_policy == policy
        assert profile.publisher_release_ids == release_ids
        assert profile.publisher_availability_lag_days == 1
        assert profile.expected_release_weekdays == ()
