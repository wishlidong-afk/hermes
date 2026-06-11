"""T9: soft-data max-age degradation (use_soft_data_max_age)."""
from __future__ import annotations

import copy

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
