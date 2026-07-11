"""T9: soft-data max-age degradation (use_soft_data_max_age)."""
from __future__ import annotations

import copy

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.adapters import apply_soft_data_slo


def _records():
    return {
        "dollar": {
            "name": "dollar", "value": 0.42, "data_available": True,
            "latency_days": 9, "reason": "", "fields": {"dollar_pctl": 0.42},
        },
        "naaim": {
            "name": "naaim", "value": 0.93, "data_available": True,
            "latency_days": 7, "reason": "", "fields": {"naaim_pctl": 0.93},
        },
        "gex": {
            "name": "gex", "value": None, "data_available": False,
            "latency_days": 0, "reason": "flag off", "fields": {},
        },
    }


def _config(flag: bool):
    return {
        "features": {"use_soft_data_max_age": flag},
        "soft_data_slo": {"default_max_age_days": 13, "max_age_days": {"dollar": 6}},
    }


def test_flag_off_is_a_noop():
    records = _records()
    snapshot = copy.deepcopy(records)
    assert apply_soft_data_slo(records, _config(False)) == snapshot


def test_over_age_record_degrades_to_missing():
    records = apply_soft_data_slo(_records(), _config(True))
    dollar = records["dollar"]
    assert dollar["data_available"] is False
    assert dollar["value"] is None
    assert dollar["fields"] == {"dollar_pctl": None}
    assert "stale: latency 9d > max_age 6d" in dollar["reason"]


def test_within_age_and_already_missing_records_untouched():
    records = apply_soft_data_slo(_records(), _config(True))
    assert records["naaim"]["data_available"] is True  # 7 <= default 13
    assert records["naaim"]["value"] == 0.93
    assert records["gex"]["reason"] == "flag off"  # already missing: left alone


def test_deployed_dollar_slo_accepts_7_days_and_rejects_15_days():
    config = load_config()
    assert config["soft_data_slo"]["max_age_days"]["dollar"] == 14

    seven_days = _records()
    seven_days["dollar"]["latency_days"] = 7
    accepted = apply_soft_data_slo(seven_days, config)["dollar"]
    assert accepted["data_available"] is True
    assert accepted["value"] == 0.42

    fifteen_days = _records()
    fifteen_days["dollar"]["latency_days"] = 15
    rejected = apply_soft_data_slo(fifteen_days, config)["dollar"]
    assert rejected["data_available"] is False
    assert rejected["value"] is None
    assert "stale: latency 15d > max_age 14d" in rejected["reason"]
