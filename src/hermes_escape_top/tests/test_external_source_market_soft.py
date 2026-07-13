from __future__ import annotations

from datetime import date
import importlib
import importlib.util

import pandas as pd

from hermes_escape_top.core.data.external_sources.runner import run_external_source_refresh


def _module():
    name = "hermes_escape_top.core.data.external_sources.market_soft"
    assert importlib.util.find_spec(name) is not None, "market_soft adapters must be implemented"
    return importlib.import_module(name)


def _cboe_page(ratio: float = 0.60, calls: int = 1000, puts: int = 600) -> str:
    return (
        f'"selectedDate":"2026-07-10" '
        f'"EQUITY PUT/CALL RATIO","value":"{ratio}" '
        f'"EQUITY OPTIONS":[{{"name":"VOLUME","call":{calls},"put":{puts}'
    )


def test_cboe_adapter_promotes_validated_ratio_and_pit_date(tmp_path):
    module = _module()
    target = tmp_path / "soft_history" / "cboe_equity_pcr.csv"
    spec = module.cboe_pcr_spec(target_path=target, min_rows=1)
    adapter = module.CboePcrAdapter(seed_path=target, fetch_text=lambda: _cboe_page())

    run = run_external_source_refresh(spec, adapter, tmp_path / "archive")
    frame = pd.read_csv(target)

    assert run.status == "OK"
    assert frame.iloc[-1]["date"] == "2026-07-10"
    assert frame.iloc[-1]["publish_date"] == "2026-07-11"
    assert frame.iloc[-1]["source"] == "CBOE_DAILY_HTML"


def test_cboe_cross_check_failure_preserves_canonical_target(tmp_path):
    module = _module()
    target = tmp_path / "soft_history" / "cboe_equity_pcr.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "date,publish_date,equity_pcr,equity_pcr_pctl,source,is_proxy\n"
        "2026-07-09,2026-07-10,0.5,,CBOE_DAILY_HTML,False\n",
        encoding="utf-8",
    )
    before = target.read_bytes()
    spec = module.cboe_pcr_spec(target_path=target, min_rows=1)
    adapter = module.CboePcrAdapter(
        seed_path=target,
        fetch_text=lambda: _cboe_page(ratio=0.9, calls=1000, puts=600),
    )

    run = run_external_source_refresh(spec, adapter, tmp_path / "archive")

    assert run.status == "VALIDATION_ERROR"
    assert "cross-check failed" in str(run.error_message)
    assert target.read_bytes() == before


def test_cboe_adapter_repairs_legacy_publish_dates_to_pit_policy(tmp_path):
    module = _module()
    target = tmp_path / "soft_history" / "cboe_equity_pcr.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "date,publish_date,equity_pcr,equity_pcr_pctl,source,is_proxy\n"
        "2026-07-09,2026-07-13,0.5,,CBOE_DAILY_HTML,False\n",
        encoding="utf-8",
    )
    spec = module.cboe_pcr_spec(target_path=target, min_rows=1)
    adapter = module.CboePcrAdapter(seed_path=target, fetch_text=lambda: _cboe_page())

    run = run_external_source_refresh(spec, adapter, tmp_path / "archive")
    frame = pd.read_csv(target)

    assert run.status == "OK"
    assert frame["publish_date"].tolist() == ["2026-07-10", "2026-07-11"]


def test_cot_adapter_aligns_tuesday_observation_to_friday_publication(tmp_path):
    module = _module()
    target = tmp_path / "soft_history" / "cot_nq.csv"
    raw = pd.DataFrame(
        [
            {
                "date": "2026-07-07",
                "open_interest": 1000,
                "asset_mgr_long": 400,
                "asset_mgr_short": 100,
                "lev_long": 200,
                "lev_short": 100,
            }
        ]
    )
    spec = module.cot_nq_spec(target_path=target, min_rows=1)
    adapter = module.CotNqAdapter(fetch_frame=lambda: raw)

    run = run_external_source_refresh(spec, adapter, tmp_path / "archive")
    frame = pd.read_csv(target)

    assert run.status == "OK"
    assert frame.iloc[0]["observation_date"] == "2026-07-07"
    assert frame.iloc[0]["date"] == "2026-07-10"
    assert frame.iloc[0]["publish_date"] == "2026-07-10"
    assert frame.iloc[0]["combined_net_oi_pct"] == 0.4


def test_occ_adapter_merges_new_week_through_runner(tmp_path):
    module = _module()
    target = tmp_path / "soft_history" / "occ_equity_pcr.csv"
    spec = module.occ_pcr_spec(target_path=target, min_rows=1)
    adapter = module.OccPcrAdapter(
        seed_path=target,
        today=date(2026, 7, 10),
        weeks=1,
        fetch_week=lambda friday: {
            "date": friday.isoformat(),
            "calls_total": 1000,
            "puts_total": 700,
            "pcr_total": 0.7,
            "calls_cust": 500,
            "puts_cust": 400,
            "pcr_cust": 0.8,
        },
    )

    run = run_external_source_refresh(spec, adapter, tmp_path / "archive")
    frame = pd.read_csv(target)

    assert run.status == "OK"
    assert frame.iloc[-1]["date"] == "2026-07-11"
    assert frame.iloc[-1]["publish_date"] == "2026-07-11"
    assert frame.iloc[-1]["pcr_cust"] == 0.8


def test_btc_micro_adapter_preserves_schema_and_real_provider(tmp_path):
    module = _module()
    target = tmp_path / "soft_history" / "btc_funding_basis.csv"
    spec = module.btc_micro_spec(target_path=target, min_rows=1)
    adapter = module.BtcMicroAdapter(
        seed_path=target,
        fetch_bundle=lambda _seed: {
            "funding_source": "deribit",
            "funding": [
                {
                    "date": "2026-07-10",
                    "btc_funding_8h_avg": 0.0001,
                    "btc_index_price": 100000.0,
                }
            ],
            "dvol": [{"date": "2026-07-10", "btc_dvol": 55.0}],
        },
    )

    run = run_external_source_refresh(spec, adapter, tmp_path / "archive")
    frame = pd.read_csv(target)

    assert run.status == "OK"
    assert frame.iloc[-1]["publish_date"] == "2026-07-10"
    assert bool(frame.iloc[-1]["is_proxy"]) is False
    assert frame.iloc[-1]["funding_source"] == "deribit"


def test_btc_micro_validator_applies_exchange_bounds_only_to_real_rows(tmp_path):
    module = _module()
    target = tmp_path / "soft_history" / "btc_funding_basis.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "date,publish_date,btc_funding_8h_avg,btc_funding_pctl,"
        "btc_basis_annual,btc_basis_pctl,is_proxy,funding_source\n"
        "2020-03-12,2020-03-12,-0.15,,-164.25,,True,proxy\n",
        encoding="utf-8",
    )
    spec = module.btc_micro_spec(target_path=target, min_rows=1)
    adapter = module.BtcMicroAdapter(
        seed_path=target,
        fetch_bundle=lambda _seed: {
            "funding_source": "deribit",
            "funding": [
                {
                    "date": "2026-07-10",
                    "btc_funding_8h_avg": 0.0001,
                    "btc_index_price": 100000.0,
                }
            ],
            "dvol": [],
        },
    )

    run = run_external_source_refresh(spec, adapter, tmp_path / "archive")

    assert run.status == "OK"


def test_btc_micro_refresh_preserves_previously_verified_real_rows(tmp_path):
    module = _module()
    target = tmp_path / "soft_history" / "btc_funding_basis.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "date,publish_date,btc_funding_8h_avg,btc_funding_pctl,"
        "btc_basis_annual,btc_basis_pctl,is_proxy,funding_source\n"
        "2026-07-09,2026-07-09,0.0002,,0.219,,False,deribit\n",
        encoding="utf-8",
    )
    spec = module.btc_micro_spec(target_path=target, min_rows=1)
    adapter = module.BtcMicroAdapter(
        seed_path=target,
        fetch_bundle=lambda _seed: {
            "funding_source": "deribit",
            "funding": [
                {
                    "date": "2026-07-10",
                    "btc_funding_8h_avg": 0.0001,
                    "btc_index_price": 100000.0,
                }
            ],
            "dvol": [],
        },
    )

    run = run_external_source_refresh(spec, adapter, tmp_path / "archive")
    frame = pd.read_csv(target)

    assert run.status == "OK"
    prior = frame.loc[frame["date"] == "2026-07-09"].iloc[0]
    assert bool(prior["is_proxy"]) is False
    assert prior["funding_source"] == "deribit"


def test_refresh_registry_exposes_all_migrated_sources(tmp_path):
    from hermes_escape_top.scripts import refresh_external

    factories = refresh_external.source_factories()

    assert {
        "cboe_equity_pcr",
        "cot_nq",
        "occ_equity_pcr",
        "btc_funding_basis",
    }.issubset(factories)
    config = {
        "paths": {
            "soft_history_dir": str(tmp_path / "soft_history"),
            "archive_dir": str(tmp_path / "archive"),
        }
    }
    spec, _adapter = factories["cboe_equity_pcr"](config)
    assert spec.target_path == tmp_path / "soft_history" / "cboe_equity_pcr.csv"
