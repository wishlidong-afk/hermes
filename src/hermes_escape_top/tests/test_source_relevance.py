from hermes_escape_top.core.data.source_relevance import (
    soft_record_is_decision_bearing,
    soft_record_decision_role,
    source_is_decision_bearing,
    source_refresh_lane,
)


def _config(**features):
    return {
        "features": features,
        "soft_data_slo": {"default_max_age_days": 13},
    }


def test_inactive_or_unknown_sources_are_manual_and_not_decision_bearing():
    config = _config(data_cot_nq=False)

    assert source_is_decision_bearing(config, "cot_nq") is False
    assert source_refresh_lane(config, "cot_nq") == "manual"
    assert source_is_decision_bearing(config, "occ_equity_pcr") is False
    assert source_refresh_lane(config, "occ_equity_pcr") == "manual"
    assert source_is_decision_bearing(config, "unknown_source") is False
    assert source_refresh_lane(config, "unknown_source") == "manual"


def test_active_research_and_auxiliary_sources_use_the_shadow_lane():
    config = _config(
        data_btc_funding=True,
        use_cboe_official_indices=True,
    )

    assert source_is_decision_bearing(config, "btc_funding_basis") is False
    assert source_refresh_lane(config, "btc_funding_basis") == "shadow"
    assert source_is_decision_bearing(config, "cboe_vix9d") is False
    assert source_refresh_lane(config, "cboe_vix9d") == "shadow"


def test_exact_fred_hard_gate_and_dependents_follow_the_vintage_flag():
    disabled = _config(use_fred_vintage_pit=False)
    enabled = _config(use_fred_vintage_pit=True)
    exact_sources = (
        "fred_vintages",
        "dollar_vintage",
        "real_rate_vintage",
        "fred_net_liquidity_vintage",
    )

    for source_id in exact_sources:
        assert source_is_decision_bearing(disabled, source_id) is False
        assert source_refresh_lane(disabled, source_id) == "manual"
        assert source_is_decision_bearing(enabled, source_id) is True
        assert source_refresh_lane(enabled, source_id) == "decision"


def test_retired_naaim_history_remains_decision_bearing_for_its_due_probe():
    config = _config(data_naaim=True)

    assert source_is_decision_bearing(config, "naaim_exposure") is True
    assert source_refresh_lane(config, "naaim_exposure") == "decision"


def test_soft_record_roles_resolve_through_existing_source_profiles():
    config = _config(
        data_aaii=True,
        data_naaim=True,
        data_net_liquidity=True,
        data_cboe_pcr=True,
        data_btc_funding=True,
        use_cboe_official_indices=True,
    )

    assert soft_record_decision_role(config, "aaii") == "strategy"
    assert soft_record_decision_role(config, "naaim") == "strategy"
    assert soft_record_decision_role(config, "net_liquidity") == "strategy"
    assert soft_record_decision_role(config, "cboe_pcr") == "strategy"
    assert soft_record_decision_role(config, "cboe_indices") == "strategy"
    assert soft_record_decision_role(config, "btc_funding_basis") == "research"
    assert soft_record_decision_role(config, "cboe_vix9d") == "auxiliary"


def test_unknown_soft_record_defaults_to_strategy():
    assert soft_record_decision_role(_config(), "new_unregistered_feed") == "strategy"


def test_disabled_soft_record_is_not_decision_bearing_but_unknowns_fail_closed():
    disabled = _config(data_gex=False)
    enabled = _config(data_gex=True)

    assert soft_record_is_decision_bearing(disabled, "gex") is False
    assert soft_record_is_decision_bearing(enabled, "gex") is True
    assert soft_record_is_decision_bearing(disabled, "new_unregistered_feed") is True
