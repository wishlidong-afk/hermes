from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from hermes_escape_top.core.data.external_sources.profiles import profile_for
from hermes_escape_top.core.research.cftc_tff_asset_manager import (
    CANDIDATE_SPEC,
    aggregate_equity_asset_manager_exposure,
    normalize_tff_asset_manager_rows,
)
from hermes_escape_top.scripts import refresh_external


def _row(
    code: str,
    *,
    report_date: str = "2026-08-04T00:00:00.000",
    open_interest: str = "300000",
    long: str = "100000",
    short: str = "35000",
    spread: str = "5000",
    name: str = "NASDAQ MINI - CHICAGO MERCANTILE EXCHANGE",
) -> dict[str, str]:
    return {
        "cftc_contract_market_code": code,
        "market_and_exchange_names": name,
        "report_date_as_yyyy_mm_dd": report_date,
        "open_interest_all": open_interest,
        "asset_mgr_positions_long": long,
        "asset_mgr_positions_short": short,
        "asset_mgr_positions_spread": spread,
    }


def test_normalize_tff_uses_exact_market_codes_and_exact_release_dates():
    rows = [
        _row("209742"),
        _row(
            "13874A",
            open_interest="2100000",
            long="1160000",
            short="225000",
            spread="91000",
            name="E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
        ),
        _row("1170E1", name="VIX FUTURES - CBOE FUTURES EXCHANGE"),
        _row("not-nq", name="NASDAQ MINI - misleading name"),
    ]

    out = normalize_tff_asset_manager_rows(
        rows,
        release_dates={date(2026, 8, 4): date(2026, 8, 7)},
    )

    assert out["market"].tolist() == ["ES", "NQ"]
    assert out["market_code"].tolist() == ["13874A", "209742"]
    assert out["observation_date"].tolist() == ["2026-08-04", "2026-08-04"]
    assert out["publish_date"].tolist() == ["2026-08-07", "2026-08-07"]
    assert out["pit_status"].tolist() == ["EXACT_RELEASE", "EXACT_RELEASE"]
    nq = out.loc[out["market"] == "NQ"].iloc[0]
    assert nq["asset_manager_net"] == 65000.0
    assert nq["asset_manager_net_oi_pct"] == pytest.approx(65000 / 300000)


def test_normalize_tff_requires_exact_release_evidence_by_default():
    with pytest.raises(ValueError, match="exact CFTC release date missing"):
        normalize_tff_asset_manager_rows([_row("209742")])


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"open_interest": "0"}, "open interest must be positive"),
        ({"long": "not-a-number"}, "position fields must be numeric"),
    ],
)
def test_normalize_tff_rejects_invalid_official_fields(overrides, message):
    with pytest.raises(ValueError, match=message):
        normalize_tff_asset_manager_rows(
            [_row("209742", **overrides)],
            release_dates={date(2026, 8, 4): date(2026, 8, 7)},
        )


def test_normalize_tff_rejects_release_before_observation():
    with pytest.raises(ValueError, match="release date precedes observation"):
        normalize_tff_asset_manager_rows(
            [_row("209742")],
            release_dates={date(2026, 8, 4): date(2026, 8, 3)},
        )


def test_normalize_tff_rejects_duplicate_contract_date_rows():
    with pytest.raises(ValueError, match="duplicate CFTC market/date"):
        normalize_tff_asset_manager_rows(
            [_row("209742"), _row("209742", long="100001")],
            release_dates={date(2026, 8, 4): date(2026, 8, 7)},
        )


def test_aggregate_candidate_is_open_interest_weighted_across_es_and_nq():
    normalized = normalize_tff_asset_manager_rows(
        [
            _row("209742", open_interest="300", long="100", short="40"),
            _row(
                "13874A",
                open_interest="700",
                long="400",
                short="200",
                name="E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
            ),
        ],
        release_dates={date(2026, 8, 4): date(2026, 8, 7)},
    )

    out = aggregate_equity_asset_manager_exposure(normalized)

    assert out.to_dict("records") == [
        {
            "date": "2026-08-07",
            "publish_date": "2026-08-07",
            "observation_date": "2026-08-04",
            "asset_manager_net": 260.0,
            "open_interest": 1000.0,
            "asset_manager_net_oi_pct": 0.26,
            "markets_used": "ES,NQ",
            "pit_status": "EXACT_RELEASE",
        }
    ]


def test_candidate_is_research_only_and_does_not_revive_rejected_cot_nq():
    assert CANDIDATE_SPEC["candidate_id"] == "CFTC_TFF_ASSET_MANAGER_EQUITY_EXPOSURE"
    assert CANDIDATE_SPEC["status"] == "OFFLINE_RESEARCH_ONLY"
    assert CANDIDATE_SPEC["production_weight"] == 0.0
    assert CANDIDATE_SPEC["proposed_max_points"] == 2.0
    assert CANDIDATE_SPEC["displaces"] == "A2_NAAIM"
    assert CANDIDATE_SPEC["distinct_from_rejected"] == "data_cot_nq"
    assert CANDIDATE_SPEC["production_source_id"] is None
    assert profile_for("cftc_tff_asset_manager_equity_exposure") is None
    assert "cftc_tff_asset_manager_equity_exposure" not in refresh_external.source_factories()


def test_aggregate_rejects_non_exact_pit_rows():
    frame = pd.DataFrame(
        [
            {
                "market": "NQ",
                "observation_date": "2026-08-04",
                "publish_date": "2026-08-07",
                "asset_manager_net": 1.0,
                "open_interest": 10.0,
                "pit_status": "SCHEDULE_INFERRED",
            }
        ]
    )

    with pytest.raises(ValueError, match="EXACT_RELEASE"):
        aggregate_equity_asset_manager_exposure(frame)
