from __future__ import annotations

from pathlib import Path

from hermes_escape_top.core.data.crypto import CryptoFundingSource
from hermes_escape_top.pipeline import _soft_snapshot


def _config(soft_history_dir: Path) -> dict:
    return {
        "features": {"data_btc_funding": True},
        "paths": {"soft_history_dir": str(soft_history_dir)},
    }


def _write_funding_row(path: Path, *, is_proxy: str, funding_source: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "btc_funding_basis.csv").write_text(
        "date,publish_date,btc_funding_8h_avg,btc_funding_pctl,"
        "btc_basis_annual,btc_basis_pctl,is_proxy,funding_source\n"
        f"2026-07-15,2026-07-15,0.0001,72.0,0.04,65.0,{is_proxy},{funding_source}\n",
        encoding="utf-8",
    )


def test_real_deribit_funding_keeps_basis_proxy_penalty(tmp_path: Path) -> None:
    _write_funding_row(tmp_path, is_proxy="False", funding_source="deribit")

    record = CryptoFundingSource().fetch("2026-07-15", _config(tmp_path))

    assert record.data_available is True
    assert record.source == "BTC_MICRO_MIXED"
    assert record.is_proxy is True
    assert record.quality_penalty == 2.0
    assert record.value == 0.0001
    assert record.field_provenance["btc_funding_8h_avg"] == {
        "source": "DERIBIT",
        "is_proxy": False,
        "quality_penalty": 0.0,
    }
    assert record.field_provenance["btc_basis_annual"] == {
        "source": "BTC_BASIS_FROM_FUNDING_PROXY",
        "is_proxy": True,
        "quality_penalty": 2.0,
    }


def test_soft_snapshot_applies_field_level_btc_provenance(tmp_path: Path) -> None:
    _write_funding_row(tmp_path, is_proxy="False", funding_source="deribit")
    record = CryptoFundingSource().fetch("2026-07-15", _config(tmp_path)).to_dict()

    snapshot = _soft_snapshot({"records": {"btc_funding_basis": record}}, "2026-07-15")

    funding = snapshot.fields["btc_funding_8h_avg"]
    basis = snapshot.fields["btc_basis_annual"]
    assert (funding.source, funding.is_proxy, funding.quality_penalty) == (
        "DERIBIT",
        False,
        0.0,
    )
    assert (basis.source, basis.is_proxy, basis.quality_penalty) == (
        "BTC_BASIS_FROM_FUNDING_PROXY",
        True,
        2.0,
    )


def test_legacy_proxy_funding_retains_proxy_provenance_and_penalty(tmp_path: Path) -> None:
    _write_funding_row(tmp_path, is_proxy="True", funding_source="proxy")

    record = CryptoFundingSource().fetch("2026-07-15", _config(tmp_path))

    assert record.data_available is True
    assert record.source == "BTC_FUNDING_PROXY"
    assert record.is_proxy is True
    assert record.quality_penalty == 2.0
    assert all(item["is_proxy"] for item in record.field_provenance.values())


def test_provenance_change_does_not_change_scoring_fields(tmp_path: Path) -> None:
    _write_funding_row(tmp_path, is_proxy="False", funding_source="deribit")
    direct = CryptoFundingSource().fetch("2026-07-15", _config(tmp_path))
    _write_funding_row(tmp_path, is_proxy="True", funding_source="proxy")
    proxy = CryptoFundingSource().fetch("2026-07-15", _config(tmp_path))

    assert direct.value == proxy.value
    assert direct.fields == proxy.fields
    assert direct.data_available == proxy.data_available
