from __future__ import annotations

from hermes_escape_top.core.data.external_sources.fred import (
    FredNetLiquidityAdapter,
    FredPercentileAdapter,
)
from hermes_escape_top.core.data.external_sources.fred_vintage import (
    FredVintageAdapter,
    FredVintageNetLiquidityAdapter,
    FredVintagePercentileAdapter,
)
from hermes_escape_top.scripts import refresh_external


def _config(tmp_path, *, enabled: bool) -> dict:
    return {
        "paths": {
            "archive_dir": str(tmp_path / "archive"),
            "soft_history_dir": str(tmp_path / "soft_history"),
        },
        "features": {"use_fred_vintage_pit": enabled},
        "fred_api_key": "test-key",
    }


def test_fred_vintage_flag_off_keeps_legacy_source_order_and_adapters(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    config = _config(tmp_path, enabled=False)

    assert refresh_external.configured_source_ids(config)[:3] == (
        "dollar",
        "real_rate",
        "fred_net_liquidity",
    )
    dollar = refresh_external.dollar_source(config)[1]
    real_rate = refresh_external.real_rate_source(config)[1]
    net_liquidity = refresh_external.fred_net_liquidity_source(config)[1]
    assert isinstance(dollar, FredPercentileAdapter)
    assert isinstance(real_rate, FredPercentileAdapter)
    assert isinstance(net_liquidity, FredNetLiquidityAdapter)
    assert dollar.publisher_release_ids == ("17",)
    assert real_rate.publisher_release_ids == ("18",)
    assert net_liquidity.publisher_release_ids == ("20", "379")
    assert dollar.config is config
    assert real_rate.config is config
    assert net_liquidity.config is config


def test_fred_vintage_flag_on_registers_event_store_before_exact_derivatives(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    config = _config(tmp_path, enabled=True)

    assert refresh_external.configured_source_ids(config)[:4] == (
        "fred_vintages",
        "dollar_vintage",
        "real_rate_vintage",
        "fred_net_liquidity_vintage",
    )
    vintage_spec, vintage_adapter = refresh_external.fred_vintages_source(config)
    dollar_spec, dollar_adapter = refresh_external.dollar_vintage_source(config)
    rate_spec, rate_adapter = refresh_external.real_rate_vintage_source(config)
    net_spec, net_adapter = refresh_external.fred_net_liquidity_vintage_source(config)

    assert vintage_spec.target_path.name == "fred_vintages.csv"
    assert isinstance(vintage_adapter, FredVintageAdapter)
    assert vintage_adapter.api_key == "test-key"
    assert dollar_spec.source_id == "dollar_vintage"
    assert dollar_spec.target_path.name == "dollar_vintage.csv"
    assert dollar_spec.date_column == "publish_date"
    assert dollar_spec.pit_rule == "exact_realtime_start_vintage"
    assert isinstance(dollar_adapter, FredVintagePercentileAdapter)
    assert isinstance(rate_adapter, FredVintagePercentileAdapter)
    assert rate_spec.source_id == "real_rate_vintage"
    assert rate_spec.target_path.name == "real_rate_vintage.csv"
    assert net_spec.source_id == "fred_net_liquidity_vintage"
    assert net_spec.target_path.name == "fred_net_liquidity_vintage.csv"
    assert net_spec.date_column == "publish_date"
    assert isinstance(net_adapter, FredVintageNetLiquidityAdapter)


def test_refresh_all_freezes_fred_derivatives_when_vintage_refresh_fails(
    monkeypatch,
    tmp_path,
) -> None:
    config = _config(tmp_path, enabled=True)
    config["features"]["data_cboe_pcr"] = True
    source_ids = (
        "fred_vintages",
        "dollar_vintage",
        "real_rate_vintage",
        "fred_net_liquidity_vintage",
        "cboe_equity_pcr",
    )
    calls: list[str] = []

    monkeypatch.setattr(refresh_external, "configured_source_ids", lambda _config: source_ids)

    def fake_refresh(source_id, _config, **_kwargs):
        calls.append(source_id)
        if source_id == "fred_vintages":
            return {"source_id": source_id, "status": "FETCH_ERROR"}
        return {"source_id": source_id, "status": "OK"}

    monkeypatch.setattr(refresh_external, "refresh_source", fake_refresh)

    result = refresh_external.refresh_all_sources(config)

    assert calls == ["fred_vintages", "cboe_equity_pcr"]
    skipped = {
        row["source_id"]: row
        for row in result["runs"]
        if row["source_id"]
        in {"dollar_vintage", "real_rate_vintage", "fred_net_liquidity_vintage"}
    }
    assert set(skipped) == {
        "dollar_vintage",
        "real_rate_vintage",
        "fred_net_liquidity_vintage",
    }
    assert {row["status"] for row in skipped.values()} == {"SKIPPED_DEPENDENCY"}
    assert all(row["dependency"] == "fred_vintages" for row in skipped.values())
    assert result["runs"][-1]["source_id"] == "cboe_equity_pcr"


def test_refresh_all_runs_exact_derivatives_after_successful_vintage_refresh(
    monkeypatch,
    tmp_path,
) -> None:
    config = _config(tmp_path, enabled=True)
    source_ids = (
        "fred_vintages",
        "dollar_vintage",
        "real_rate_vintage",
        "fred_net_liquidity_vintage",
    )
    calls: list[str] = []

    monkeypatch.setattr(refresh_external, "configured_source_ids", lambda _config: source_ids)
    monkeypatch.setattr(
        refresh_external,
        "refresh_source",
        lambda source_id, _config, **_kwargs: calls.append(source_id)
        or {"source_id": source_id, "status": "OK"},
    )

    result = refresh_external.refresh_all_sources(config)

    assert result["ok"] is True
    assert calls == list(source_ids)


def test_retry_freezes_selected_derivatives_when_vintage_retry_fails(
    monkeypatch,
    tmp_path,
) -> None:
    config = _config(tmp_path, enabled=True)
    config["features"]["data_cboe_pcr"] = True
    source_ids = (
        "fred_vintages",
        "dollar_vintage",
        "real_rate_vintage",
        "fred_net_liquidity_vintage",
        "cboe_equity_pcr",
    )
    calls: list[str] = []
    retry_row = {
        "status": "FETCH_ERROR",
        "freshness_status": "UNKNOWN",
        "evidence_status": "NO_LEDGER",
        "active": True,
    }

    monkeypatch.setattr(refresh_external, "configured_source_ids", lambda _config: source_ids)
    monkeypatch.setattr(
        refresh_external,
        "status",
        lambda _config, today=None: {source_id: dict(retry_row) for source_id in source_ids},
    )

    def fake_refresh(source_id, _config, **_kwargs):
        calls.append(source_id)
        return {
            "source_id": source_id,
            "status": "FETCH_ERROR" if source_id == "fred_vintages" else "OK",
        }

    monkeypatch.setattr(refresh_external, "refresh_source", fake_refresh)

    result = refresh_external.refresh_retry_sources(config)

    assert calls == ["fred_vintages", "cboe_equity_pcr"]
    assert [row["status"] for row in result["runs"]] == [
        "FETCH_ERROR",
        "SKIPPED_DEPENDENCY",
        "SKIPPED_DEPENDENCY",
        "SKIPPED_DEPENDENCY",
        "OK",
    ]


def test_cli_source_choices_include_fred_vintage_store() -> None:
    assert "fred_vintages" in refresh_external.ALL_SOURCE_IDS
