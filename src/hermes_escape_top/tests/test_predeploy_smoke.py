"""Tests for the pre-deploy validation smoke gate.

Each check maps to a real 2026-06 incident; these prove the gate catches a
synthetic reproduction of each (and passes a clean one).
"""
from __future__ import annotations

import pandas as pd

from hermes_escape_top.scripts import predeploy_smoke as smoke


def _clean_payload():
    return {
        "as_of": "2026-06-12",
        "scores": {
            "MSTR": {"final_score": 66.0}, "FNGU": {"final_score": 46.0},
            "SOXL": {"final_score": 32.0},
        },
        "routing_context": {
            "module_a": {"MSTR": 15, "FNGU": 15, "SOXL": 15},
            "brkb_defense": {"degraded": True, "reason": "BRK.B close <= MA200",
                             "corr_to_spy": None, "threshold": 0.85},
            "qqq": {},
        },
        "confidence_spine": {"mode": "NORMAL", "weakest_link": "data", "components": {}},
    }


def test_no_na_check_passes_clean_payload():
    _, ok, detail = smoke.check_no_na_in_evidence(_clean_payload())
    assert ok, detail


def test_no_na_check_catches_module_a_na():
    payload = _clean_payload()
    payload["routing_context"]["module_a"] = {}  # the bug shape -> "A模块 NA"
    _, ok, detail = smoke.check_no_na_in_evidence(payload)
    assert not ok and "A模块 NA" in detail


def test_fred_publish_date_check_catches_collapsed_stamp(tmp_path, monkeypatch):
    d = tmp_path / "soft"
    d.mkdir()
    pd.DataFrame({
        "date": pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"]),
        "publish_date": pd.to_datetime(["2026-06-13", "2026-06-13", "2026-06-13"]),
        "real_rate_10y": [1.0, 1.1, 1.2], "real_rate_10y_pctl": [50, 60, 70],
    }).to_csv(d / "real_rate.csv", index=False)
    monkeypatch.setattr(smoke, "resolve_path", lambda cfg, key: d)
    config = {"features": {"data_real_rate": True}, "paths": {}}
    _, ok, detail = smoke.check_fred_publish_dates(config)
    assert not ok and "collapsed" in detail


def test_fred_publish_date_check_passes_per_row(tmp_path, monkeypatch):
    d = tmp_path / "soft"
    d.mkdir()
    pd.DataFrame({
        "date": pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"]),
        "publish_date": pd.to_datetime(["2020-01-03", "2020-01-04", "2020-01-07"]),
        "real_rate_10y": [1.0, 1.1, 1.2], "real_rate_10y_pctl": [50, 60, 70],
    }).to_csv(d / "real_rate.csv", index=False)
    monkeypatch.setattr(smoke, "resolve_path", lambda cfg, key: d)
    config = {"features": {"data_real_rate": True}, "paths": {}}
    _, ok, detail = smoke.check_fred_publish_dates(config)
    assert ok, detail


def test_unexplained_flip_flags_soft_flip_but_allows_valve():
    prev = {"scores": {"SOXL": {"status": "REDUCE", "hard_valve_hits": []}}}
    soft = {"scores": {"SOXL": {"status": "EXIT", "hard_valve_hits": []}}}
    _, ok, detail = smoke.check_no_unexplained_flip(prev, soft)
    assert not ok and "SOXL" in detail

    valve = {"scores": {"SOXL": {"status": "EXIT", "hard_valve_hits": ["H-S1"]}}}
    _, ok2, _ = smoke.check_no_unexplained_flip(prev, valve)
    assert ok2


def test_source_regression_catches_always_on_source_going_dark():
    # The gap the risk-only check missed: an always-on source (naaim) that WAS
    # available going MISSING must now be caught.
    prev = {"soft_data": {"records": {"naaim": {"data_available": True}}}}
    curr = {"soft_data": {"records": {"naaim": {"data_available": False, "reason": "no record as of date"}}}}
    _, ok, detail = smoke.check_no_source_regression(prev, curr)
    assert not ok and "naaim" in detail


def test_source_regression_ignores_steady_state_absent():
    # Absent in BOTH runs (off / legit weekly gap) is not a regression -> no false alarm.
    prev = {"soft_data": {"records": {"aaii": {"data_available": False}}}}
    curr = {"soft_data": {"records": {"aaii": {"data_available": False}}}}
    _, ok, _ = smoke.check_no_source_regression(prev, curr)
    assert ok


def test_source_regression_passes_when_still_available():
    prev = {"soft_data": {"records": {"real_rate": {"data_available": True}}}}
    curr = {"soft_data": {"records": {"real_rate": {"data_available": True}}}}
    _, ok, _ = smoke.check_no_source_regression(prev, curr)
    assert ok


def test_source_regression_ignores_off_by_design_sources():
    # gex/valuation flip available<->missing by design and don't feed advice;
    # a flip there must NOT fail the gate (caught in live self-review).
    prev = {"soft_data": {"records": {"valuation": {"data_available": True}}}}
    curr = {"soft_data": {"records": {"valuation": {"data_available": False, "reason": "absent"}}}}
    _, ok, _ = smoke.check_no_source_regression(prev, curr)
    assert ok


def test_always_on_daily_catches_steady_state_missing():
    # A daily source missing fails even if it was already missing in the prev run
    # (the steady-state gap the regression delta leaves).
    payload = {"soft_data": {"records": {"net_liquidity": {"data_available": False, "reason": "absent"}}}}
    _, ok, detail = smoke.check_always_on_daily_available(payload)
    assert not ok and "net_liquidity" in detail


def test_always_on_daily_passes_when_available():
    payload = {"soft_data": {"records": {n: {"data_available": True} for n in smoke.ALWAYS_ON_DAILY}}}
    _, ok, _ = smoke.check_always_on_daily_available(payload)
    assert ok


def test_always_on_daily_skips_unwired_source():
    # A source not present in the payload at all is not asserted (no false alarm on
    # a build that doesn't wire it).
    _, ok, _ = smoke.check_always_on_daily_available({"soft_data": {"records": {}}})
    assert ok
