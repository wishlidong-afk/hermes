"""Tests for the pre-deploy validation smoke gate.

Each check maps to a real 2026-06 incident; these prove the gate catches a
synthetic reproduction of each (and passes a clean one).
"""
from __future__ import annotations

import pandas as pd

from hermes_escape_top.scripts import predeploy_smoke as smoke


def _dollar_slo_config(max_age: int = 6, *, guard_enabled: bool = True):
    return {
        "features": {
            "data_dollar": True,
            "use_soft_data_max_age": guard_enabled,
        },
        "soft_data_slo": {"max_age_days": {"dollar": max_age}},
    }


def _dollar_stale_record(*, latency: int = 7, reason: str = "stale: latency 7d > max_age 6d"):
    return {
        "data_available": False,
        "latency_days": latency,
        "reason": reason,
    }


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


def test_fred_publish_date_check_accepts_late_exact_revision(tmp_path, monkeypatch):
    d = tmp_path / "soft"
    d.mkdir()
    pd.DataFrame(
        {
            "series_id": ["DFII10"],
            "observation_date": ["2020-01-02"],
            "realtime_start": ["2026-06-13"],
            "vintage_date": ["2026-06-13"],
            "value": [1.2],
            "is_missing": [False],
            "fetched_at": ["2026-07-14T00:00:00+00:00"],
            "source_url": ["https://api.stlouisfed.org/fred/series/observations"],
            "response_sha256": ["a" * 64],
        }
    ).to_csv(d / "fred_vintages.csv", index=False)
    pd.DataFrame(
        {
            "date": ["2020-01-02", "2020-01-03"],
            "publish_date": ["2020-01-03", "2026-06-13"],
            "realtime_start": ["2020-01-03", "2026-06-13"],
            "vintage_date": ["2020-01-03", "2026-06-13"],
            "real_rate_10y": [1.0, 1.2],
            "real_rate_10y_pctl": [50.0, 60.0],
        }
    ).to_csv(d / "real_rate_vintage.csv", index=False)
    monkeypatch.setattr(smoke, "resolve_path", lambda cfg, key: d)
    config = {
        "features": {"data_real_rate": True, "use_fred_vintage_pit": True},
        "paths": {},
    }

    _, ok, detail = smoke.check_fred_publish_dates(config)

    assert ok, detail


def test_fred_publish_date_check_rejects_missing_or_mismatched_exact_evidence(
    tmp_path,
    monkeypatch,
):
    d = tmp_path / "soft"
    d.mkdir()
    pd.DataFrame(
        {
            "date": ["2020-01-02"],
            "publish_date": ["2020-01-03"],
            "realtime_start": ["2020-01-04"],
            "vintage_date": ["2020-01-03"],
            "real_rate_10y": [1.0],
            "real_rate_10y_pctl": [50.0],
        }
    ).to_csv(d / "real_rate_vintage.csv", index=False)
    monkeypatch.setattr(smoke, "resolve_path", lambda cfg, key: d)
    config = {
        "features": {"data_real_rate": True, "use_fred_vintage_pit": True},
        "paths": {},
    }

    _, ok, detail = smoke.check_fred_publish_dates(config)

    assert not ok
    assert "fred_vintages.csv missing" in detail
    assert "vintage columns disagree" in detail


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


def test_policy_verified_slo_stale_is_warning_not_fatal():
    config = _dollar_slo_config()
    stale = _dollar_stale_record()
    prev = {"soft_data": {"records": {"dollar": {"data_available": True}}}}
    curr = {"soft_data": {"records": {"dollar": stale}}}

    _, available_ok, available_detail = smoke.check_on_sources_available(config, curr)
    _, regression_ok, regression_detail = smoke.check_no_source_regression(prev, curr, config)
    warning_name, warning_ok, warning_detail = smoke.check_expected_slo_stale(config, curr)

    assert available_ok, available_detail
    assert regression_ok, regression_detail
    assert warning_name == "policy-verified SLO stale"
    assert not warning_ok
    assert "dollar" in warning_detail


def test_slo_stale_reason_must_match_config_and_payload_exactly():
    config = _dollar_slo_config()
    prev = {"soft_data": {"records": {"dollar": {"data_available": True}}}}
    cases = [
        _dollar_stale_record(reason="stale: latency 7d > max_age 5d"),
        _dollar_stale_record(latency=8),
        _dollar_stale_record(reason="upstream timeout"),
    ]

    for record in cases:
        payload = {"soft_data": {"records": {"dollar": record}}}
        _, ok, detail = smoke.check_on_sources_available(config, payload)
        _, regression_ok, regression_detail = smoke.check_no_source_regression(prev, payload, config)
        assert not ok
        assert "dollar" in detail
        assert not regression_ok
        assert "dollar" in regression_detail


def test_slo_stale_is_fatal_when_guard_is_disabled():
    config = _dollar_slo_config(guard_enabled=False)
    payload = {"soft_data": {"records": {"dollar": _dollar_stale_record()}}}

    _, ok, detail = smoke.check_on_sources_available(config, payload)

    assert not ok
    assert "dollar" in detail


def test_on_source_missing_from_payload_is_fatal():
    config = _dollar_slo_config()

    _, ok, detail = smoke.check_on_sources_available(
        config,
        {"soft_data": {"records": {}}},
    )

    assert not ok
    assert "dollar: absent" in detail


def test_run_smoke_surfaces_policy_verified_stale_as_nonfatal_warning(monkeypatch):
    config = _dollar_slo_config()
    prev = {
        "as_of": "2026-07-09",
        "soft_data": {"records": {"dollar": {"data_available": True}}},
    }
    curr = {
        "as_of": "2026-07-10",
        "soft_data": {"records": {"dollar": _dollar_stale_record()}},
    }
    monkeypatch.setattr(smoke, "_read_recent_official_payloads", lambda cfg, n=2: [prev, curr])
    monkeypatch.setattr(smoke, "check_fred_publish_dates", lambda cfg: ("fred", True, "OK"))
    monkeypatch.setattr(smoke, "check_always_on_daily_available", lambda payload: ("daily", True, "OK"))
    monkeypatch.setattr(smoke, "check_no_na_in_evidence", lambda payload: ("evidence", True, "OK"))
    monkeypatch.setattr(smoke, "check_manifest_not_drift", lambda cfg: ("manifest", True, "OK"))
    monkeypatch.setattr(smoke, "check_no_unexplained_flip", lambda old, new: ("flip", True, "OK"))

    result = smoke.run_smoke(config)

    assert result["ok"]
    warning = next(check for check in result["checks"] if check["name"] == "policy-verified SLO stale")
    assert warning == {
        "name": "policy-verified SLO stale",
        "ok": False,
        "fatal": False,
        "detail": "dollar: stale: latency 7d > max_age 6d",
    }


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


def test_repo_live_data_root_points_repo_smoke_at_live_current(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    package = repo / "src" / "hermes_escape_top"
    package.mkdir(parents=True)
    (repo / ".git").mkdir()
    home = tmp_path / "home"
    live_pkg = home / ".hermes" / "skills" / "investment" / "escape-top" / "current" / "hermes_escape_top"
    (live_pkg / "data").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("HERMES_DATA_DIR", raising=False)
    monkeypatch.setattr(smoke, "PACKAGE_DIR", package)

    with smoke.repo_live_data_root() as data_root:
        assert data_root == live_pkg
        assert smoke.os.environ["HERMES_DATA_DIR"] == str(live_pkg)

    assert "HERMES_DATA_DIR" not in smoke.os.environ


def test_repo_live_data_root_respects_explicit_data_root(monkeypatch, tmp_path):
    explicit = tmp_path / "explicit"
    monkeypatch.setenv("HERMES_DATA_DIR", str(explicit))

    with smoke.repo_live_data_root() as data_root:
        assert data_root is None
        assert smoke.os.environ["HERMES_DATA_DIR"] == str(explicit)
