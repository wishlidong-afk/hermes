from __future__ import annotations

import datetime as dt
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd

from hermes_escape_top.core.data.external_sources.ledger import latest_source_run, source_status
from hermes_escape_top.core.data.external_sources.naaim import (
    NaaimExposureAdapter,
    NaaimExposureImportAdapter,
    NaaimSubscriberAdapter,
    discover_naaim_xlsx_url,
    naaim_exposure_spec,
)
from hermes_escape_top.core.data.external_sources.profiles import latest_import_file, profile_for
from hermes_escape_top.core.data.external_sources.runner import run_external_source_refresh
from hermes_escape_top.scripts.refresh_external import naaim_exposure_source


def _naaim_xlsx(data_rows=None) -> bytes:
    out = BytesIO()
    rows = [["Date", "NAAIM Number", "Mean/Average", "Deviation"]]
    rows.extend(data_rows or [
        [dt.date(2026, 6, 3).isoformat(), 86.82, 90.0, 72.07],
        [dt.date(2026, 6, 10).isoformat(), 79.27, 88.0, 53.30],
        [dt.date(2026, 6, 17).isoformat(), 92.83, 95.0, 49.11],
        [dt.date(2026, 6, 24).isoformat(), 98.59, 98.0, 43.91],
    ])
    sheet_rows = []
    for r_idx, row in enumerate(rows, start=1):
        cells = []
        for c_idx, value in enumerate(row, start=1):
            ref = f"{chr(64 + c_idx)}{r_idx}"
            if isinstance(value, str):
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>')
            else:
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
        sheet_rows.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>'
        f'{"".join(sheet_rows)}'
        '</sheetData>'
        '</worksheet>'
    )
    with ZipFile(out, "w", ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>'
        ))
        zf.writestr("_rels/.rels", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'
        ))
        zf.writestr("xl/workbook.xml", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>'
            '</workbook>'
        ))
        zf.writestr("xl/_rels/workbook.xml.rels", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>'
        ))
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
    return out.getvalue()


def test_discover_naaim_xlsx_url_prefers_since_inception_workbook():
    html = """
      <a href="https://naaim.org/wp-content/uploads/2026/06/small.xlsx">Small</a>
      <a href="/wp-content/uploads/2026/06/USE_Data-since-Inception_2026-06-24.xlsx">HERE</a>
    """

    url = discover_naaim_xlsx_url(html, "https://www.naaim.org/programs/naaim-exposure-index/")

    assert url == "https://www.naaim.org/wp-content/uploads/2026/06/USE_Data-since-Inception_2026-06-24.xlsx"


def test_discover_naaim_xlsx_url_selects_latest_dated_official_workbook():
    html = """
      <a href="/wp-content/uploads/2026/06/USE_Data-since-Inception_2026-06-24.xlsx">Old</a>
      <a data-href="https://naaim.org/wp-content/uploads/2026/07/USE_Data-since-Inception_2026-07-08.xlsx">Current</a>
      <a href="/wp-content/uploads/2026/07/USE_Data-since-Inception_2026-07-01.xlsx">Previous</a>
    """

    url = discover_naaim_xlsx_url(html, "https://www.naaim.org/programs/naaim-exposure-index/")

    assert url == "https://naaim.org/wp-content/uploads/2026/07/USE_Data-since-Inception_2026-07-08.xlsx"


def test_discover_naaim_xlsx_url_rejects_non_naaim_download_host():
    html = '<a href="https://example.com/USE_Data-since-Inception_2099-12-31.xlsx">HERE</a>'

    assert discover_naaim_xlsx_url(html) is None


def test_discover_naaim_xlsx_url_prefers_latest_issue_over_legacy_name():
    html = """
      <a href="/wp-content/uploads/2026/06/USE_Data-since-Inception_2026-06-24.xlsx">Old full history</a>
      <a href="/member-downloads/NAAIM_2026-07-08.xlsx">New subscription name</a>
    """

    assert discover_naaim_xlsx_url(html) == "https://www.naaim.org/member-downloads/NAAIM_2026-07-08.xlsx"


def test_naaim_adapter_promotes_existing_soft_history_shape(tmp_path):
    xlsx_url = "https://naaim.org/wp-content/uploads/2026/06/USE_Data-since-Inception_2026-06-24.xlsx"
    html = f'<a href="{xlsx_url}">Download EXCEL file with data since inception</a>'
    adapter = NaaimExposureAdapter(
        fetch_text=lambda _url: html,
        fetch_bytes=lambda url: _naaim_xlsx() if url == xlsx_url else b"",
        percentile_window=3,
        min_periods=1,
    )
    target = tmp_path / "soft_history" / "naaim_exposure.csv"
    spec = naaim_exposure_spec(target_path=target, min_rows=4)

    run = run_external_source_refresh(spec, adapter, tmp_path / "archive")

    out = pd.read_csv(target)
    assert run.status == "OK"
    assert list(out.columns) == ["date", "publish_date", "naaim_exposure", "naaim_pctl", "is_proxy"]
    assert out["date"].tolist() == ["2026-06-03", "2026-06-10", "2026-06-17", "2026-06-24"]
    assert out["publish_date"].tolist() == ["2026-06-04", "2026-06-11", "2026-06-18", "2026-06-25"]
    assert out["naaim_exposure"].tolist() == [86.82, 79.27, 92.83, 98.59]
    assert out["naaim_pctl"].round(2).tolist() == [100.0, 50.0, 100.0, 100.0]
    assert out["is_proxy"].tolist() == [False, False, False, False]
    ledger = latest_source_run(tmp_path / "archive", "naaim_exposure")
    assert ledger["latest_promoted_as_of"] == "2026-06-24"
    assert ledger["source_url"] == xlsx_url


def test_naaim_subscriber_adapter_uses_auth_without_persisting_secret(tmp_path):
    captured = {}
    signed_url = (
        "https://www.naaim.org/member-downloads/latest.xlsx"
        "?token=signed-secret&expires=9999999999"
    )

    def fetch(url, headers):
        captured.update({"url": url, "headers": headers})
        return _naaim_xlsx()

    adapter = NaaimSubscriberAdapter(
        download_url=signed_url,
        bearer_token="top-secret-token",
        fetch_authenticated=fetch,
        percentile_window=3,
        min_periods=1,
    )
    target = tmp_path / "soft_history/naaim_exposure.csv"

    run = run_external_source_refresh(
        naaim_exposure_spec(target_path=target, min_rows=4),
        adapter,
        tmp_path / "archive",
    )

    assert run.status == "OK"
    assert captured["url"] == signed_url
    assert captured["headers"]["Authorization"] == "Bearer top-secret-token"
    raw_json = next((tmp_path / "archive/external_sources/naaim_exposure").rglob("raw.json"))
    raw_text = raw_json.read_text(encoding="utf-8")
    raw = json.loads(raw_text)
    assert "top-secret-token" not in raw_text
    assert "signed-secret" not in raw_text
    assert raw["auth_mode"] == "bearer"
    assert raw["xlsx_url"] == "https://www.naaim.org/member-downloads/latest.xlsx"
    ledger = latest_source_run(tmp_path / "archive", "naaim_exposure")
    assert ledger["source_url"] == "https://www.naaim.org/member-downloads/latest.xlsx"


def test_naaim_subscriber_fetch_error_redacts_transport_secrets_everywhere(tmp_path):
    signed_url = (
        "https://www.naaim.org/member-downloads/latest.xlsx"
        "?token=signed-secret&expires=9999999999"
    )

    def fetch(url, headers):
        raise RuntimeError(
            f"403 for {url}; Authorization: {headers['Authorization']}; "
            "Cookie: session=transport-secret; csrf=cookie-tail-secret"
        )

    target = tmp_path / "soft_history/naaim_exposure.csv"
    spec = naaim_exposure_spec(target_path=target, min_rows=4)
    run = run_external_source_refresh(
        spec,
        NaaimSubscriberAdapter(
            download_url=signed_url,
            bearer_token="top-secret-token",
            fetch_authenticated=fetch,
        ),
        tmp_path / "archive",
    )

    status = source_status(tmp_path / "archive", [spec])["naaim_exposure"]
    persisted = json.dumps(
        {
            "run": run.to_dict(),
            "ledger": latest_source_run(tmp_path / "archive", "naaim_exposure"),
            "status": status,
        },
        sort_keys=True,
    )
    for secret in (
        "signed-secret",
        "top-secret-token",
        "transport-secret",
        "cookie-tail-secret",
    ):
        assert secret not in persisted
    assert "https://www.naaim.org/member-downloads/latest.xlsx" in persisted
    assert "Authorization=<redacted>" in persisted
    assert "Cookie=<redacted>" in persisted


def test_naaim_public_parse_error_raw_evidence_redacts_signed_url(tmp_path):
    signed_url = (
        "https://www.naaim.org/data/latest.xlsx"
        "?token=public-signed-secret&expires=9999999999"
    )
    adapter = NaaimExposureAdapter(
        fetch_text=lambda _url: f'<a href="{signed_url}">xlsx</a>',
        fetch_bytes=lambda _url: b"not-an-xlsx",
    )
    spec = naaim_exposure_spec(
        target_path=tmp_path / "soft_history/naaim_exposure.csv",
        min_rows=1,
    )

    run = run_external_source_refresh(spec, adapter, tmp_path / "archive")

    raw_text = Path(run.raw_path).read_text(encoding="utf-8")
    persisted = json.dumps(
        {
            "run": run.to_dict(),
            "ledger": latest_source_run(tmp_path / "archive", "naaim_exposure"),
            "raw": json.loads(raw_text),
        },
        sort_keys=True,
    )
    assert run.status == "PARSE_ERROR"
    assert "public-signed-secret" not in persisted
    assert "https://www.naaim.org/data/latest.xlsx" in persisted


def test_naaim_public_adapter_identifies_automatic_official_channel():
    xlsx_url = "https://www.naaim.org/data/USE_Data-since-Inception_2026-07-15.xlsx"
    adapter = NaaimExposureAdapter(
        fetch_text=lambda _url: f'<a href="{xlsx_url}">xlsx</a>',
        fetch_bytes=lambda _url: _naaim_xlsx(),
    )

    raw = adapter.fetch_raw()

    assert raw["source"] == "naaim_public_workbook"


def test_naaim_subscriber_adapter_rejects_non_naaim_credential_target():
    adapter = NaaimSubscriberAdapter(
        download_url="https://example.com/latest.xlsx",
        bearer_token="secret",
        fetch_authenticated=lambda _url, _headers: _naaim_xlsx(),
    )

    try:
        adapter.fetch_raw()
    except ValueError as exc:
        assert "naaim.org" in str(exc)
    else:
        raise AssertionError("subscriber credentials must not be sent to another host")


def test_naaim_subscriber_adapter_rejects_url_userinfo():
    adapter = NaaimSubscriberAdapter(
        download_url="https://user:password@www.naaim.org/member-downloads/latest.xlsx",
        bearer_token="secret",
        fetch_authenticated=lambda _url, _headers: _naaim_xlsx(),
    )

    try:
        adapter.fetch_raw()
    except ValueError as exc:
        assert "userinfo" in str(exc)
    else:
        raise AssertionError("subscriber URL userinfo must be rejected")


def test_naaim_source_factory_selects_subscriber_only_when_configured(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "NAAIM_SUBSCRIBER_URL",
        "https://www.naaim.org/member-downloads/latest.xlsx",
    )
    monkeypatch.setenv("NAAIM_SUBSCRIBER_BEARER_TOKEN", "secret")

    _spec, adapter = naaim_exposure_source(
        {"paths": {"soft_history_dir": str(tmp_path / "soft_history")}}
    )

    assert isinstance(adapter, NaaimSubscriberAdapter)


def test_naaim_fetch_failure_preserves_certified_canonical(tmp_path):
    target = tmp_path / "soft_history" / "naaim_exposure.csv"
    target.parent.mkdir(parents=True)
    certified = b"date,publish_date,naaim_exposure,naaim_pctl,is_proxy\n2026-06-24,2026-06-25,98.59,100.0,False\n"
    target.write_bytes(certified)
    adapter = NaaimExposureAdapter(fetch_text=lambda _url: (_ for _ in ()).throw(RuntimeError("subscription required")))

    run = run_external_source_refresh(
        naaim_exposure_spec(target_path=target, min_rows=1),
        adapter,
        tmp_path / "archive",
    )

    assert run.status == "FETCH_ERROR"
    assert target.read_bytes() == certified


def test_naaim_direct_and_official_import_paths_are_canonical_equivalent(tmp_path):
    xlsx_url = "https://naaim.org/wp-content/uploads/2026/06/USE_Data-since-Inception_2026-06-24.xlsx"
    workbook = _naaim_xlsx()
    html = f'<a href="{xlsx_url}">Download EXCEL file with data since inception</a>'
    direct_target = tmp_path / "direct" / "naaim_exposure.csv"
    direct = NaaimExposureAdapter(
        fetch_text=lambda _url: html,
        fetch_bytes=lambda _url: workbook,
        percentile_window=3,
        min_periods=1,
    )
    import_path = tmp_path / "USE_Data-since-Inception_2026-06-24.xlsx"
    import_path.write_bytes(workbook)
    imported_target = tmp_path / "imported" / "naaim_exposure.csv"
    imported = NaaimExposureImportAdapter(
        import_path=import_path,
        percentile_window=3,
        min_periods=1,
    )

    direct_run = run_external_source_refresh(
        naaim_exposure_spec(target_path=direct_target, min_rows=4),
        direct,
        tmp_path / "direct_archive",
    )
    import_run = run_external_source_refresh(
        naaim_exposure_spec(target_path=imported_target, min_rows=4),
        imported,
        tmp_path / "import_archive",
    )

    assert direct_run.status == "OK"
    assert import_run.status == "OK"
    assert direct_target.read_bytes() == imported_target.read_bytes()
    assert direct_run.official_file_sha256 == import_run.official_file_sha256


def test_naaim_import_adapter_promotes_official_workbook_through_ledger(tmp_path):
    import_path = tmp_path / "USE_Data-since-Inception_2026-06-24.xlsx"
    import_path.write_bytes(_naaim_xlsx())
    target = tmp_path / "soft_history" / "naaim_exposure.csv"
    adapter = NaaimExposureImportAdapter(
        import_path=import_path,
        percentile_window=3,
        min_periods=1,
    )

    run = run_external_source_refresh(naaim_exposure_spec(target_path=target, min_rows=4), adapter, tmp_path / "archive")

    out = pd.read_csv(target)
    ledger = latest_source_run(tmp_path / "archive", "naaim_exposure")
    assert run.status == "OK"
    assert run.latest_promoted_as_of == "2026-06-24"
    assert out["date"].tolist() == ["2026-06-03", "2026-06-10", "2026-06-17", "2026-06-24"]
    assert out["naaim_exposure"].tolist() == [86.82, 79.27, 92.83, 98.59]
    assert ledger["status"] == "OK"
    assert ledger["official_file_name"] == "USE_Data-since-Inception_2026-06-24.xlsx"
    assert ledger["official_file_sha256"]
    assert ledger["official_issue_as_of"] == "2026-06-24"
    assert ledger["pit_rule"] == "issue_date_plus_one_day"
    assert ledger["source_url"] == "https://www.naaim.org/programs/naaim-exposure-index/"


def test_naaim_import_merges_partial_new_issue_with_certified_history(tmp_path):
    target = tmp_path / "soft_history" / "naaim_exposure.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "date,publish_date,naaim_exposure,naaim_pctl,is_proxy\n"
        "2026-06-24,2026-06-25,98.59,100.0,False\n",
        encoding="utf-8",
    )
    import_path = tmp_path / "NAAIM_2026-07-01.csv"
    import_path.write_text(
        "Date,NAAIM Number\n2026-07-01,75.0\n",
        encoding="utf-8",
    )
    adapter = NaaimExposureImportAdapter(
        import_path=import_path,
        seed_path=target,
        percentile_window=3,
        min_periods=1,
    )

    run = run_external_source_refresh(
        naaim_exposure_spec(target_path=target, min_rows=1),
        adapter,
        tmp_path / "archive",
    )

    assert run.status == "OK"
    out = pd.read_csv(target)
    assert out["date"].tolist() == ["2026-06-24", "2026-07-01"]
    assert out["naaim_exposure"].tolist() == [98.59, 75.0]
    assert out["naaim_pctl"].tolist() == [100.0, 50.0]


def test_naaim_import_rejects_file_older_than_certified_history(tmp_path):
    target = tmp_path / "soft_history" / "naaim_exposure.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "date,publish_date,naaim_exposure,naaim_pctl,is_proxy\n"
        "2026-06-24,2026-06-25,98.59,100.0,False\n",
        encoding="utf-8",
    )
    import_path = tmp_path / "NAAIM_2026-06-17.csv"
    import_path.write_text(
        "Date,NAAIM Number\n2026-06-17,85.0\n",
        encoding="utf-8",
    )
    adapter = NaaimExposureImportAdapter(
        import_path=import_path,
        seed_path=target,
        percentile_window=3,
        min_periods=1,
    )

    run = run_external_source_refresh(
        naaim_exposure_spec(target_path=target, min_rows=1),
        adapter,
        tmp_path / "archive",
    )

    assert run.status == "PARSE_ERROR"
    assert "older than current NAAIM seed" in str(run.error_message)
    assert pd.read_csv(target)["date"].tolist() == ["2026-06-24"]


def test_naaim_public_rejects_newer_workbook_that_truncates_certified_history(tmp_path):
    target = tmp_path / "soft_history/naaim_exposure.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "date,publish_date,naaim_exposure,naaim_pctl,is_proxy\n"
        "2026-06-03,2026-06-04,86.82,100.0,False\n"
        "2026-06-10,2026-06-11,79.27,50.0,False\n",
        encoding="utf-8",
    )
    certified = target.read_bytes()
    xlsx_url = "https://naaim.org/data/NAAIM_2026-07-01.xlsx"
    workbook = _naaim_xlsx([
        ["2026-06-10", 79.27, 88.0, 53.30],
        ["2026-07-01", 75.0, 80.0, 40.0],
    ])
    adapter = NaaimExposureAdapter(
        seed_path=target,
        fetch_text=lambda _url: f'<a href="{xlsx_url}">xlsx</a>',
        fetch_bytes=lambda _url: workbook,
        percentile_window=3,
        min_periods=1,
    )

    run = run_external_source_refresh(
        naaim_exposure_spec(target_path=target, min_rows=1),
        adapter,
        tmp_path / "archive",
    )

    assert run.status == "PARSE_ERROR"
    assert "truncates certified history" in str(run.error_message)
    assert target.read_bytes() == certified


def test_naaim_subscriber_rejects_newer_workbook_that_truncates_certified_history(tmp_path):
    target = tmp_path / "soft_history/naaim_exposure.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "date,publish_date,naaim_exposure,naaim_pctl,is_proxy\n"
        "2026-06-03,2026-06-04,86.82,100.0,False\n"
        "2026-06-10,2026-06-11,79.27,50.0,False\n",
        encoding="utf-8",
    )
    certified = target.read_bytes()
    workbook = _naaim_xlsx([
        ["2026-06-10", 79.27, 88.0, 53.30],
        ["2026-07-01", 75.0, 80.0, 40.0],
    ])
    adapter = NaaimSubscriberAdapter(
        download_url="https://www.naaim.org/member-downloads/latest.xlsx",
        bearer_token="secret",
        seed_path=target,
        fetch_authenticated=lambda _url, _headers: workbook,
        percentile_window=3,
        min_periods=1,
    )

    run = run_external_source_refresh(
        naaim_exposure_spec(target_path=target, min_rows=1),
        adapter,
        tmp_path / "archive",
    )

    assert run.status == "PARSE_ERROR"
    assert "truncates certified history" in str(run.error_message)
    assert target.read_bytes() == certified


def test_naaim_import_rejects_changes_to_overlapping_certified_rows(tmp_path):
    target = tmp_path / "soft_history/naaim_exposure.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "date,publish_date,naaim_exposure,naaim_pctl,is_proxy\n"
        "2026-06-24,2026-06-25,98.59,100.0,False\n",
        encoding="utf-8",
    )
    certified = target.read_bytes()
    import_path = tmp_path / "NAAIM_2026-07-01.csv"
    import_path.write_text(
        "Date,NAAIM Number\n"
        "2026-06-24,40.0\n"
        "2026-07-01,75.0\n",
        encoding="utf-8",
    )
    adapter = NaaimExposureImportAdapter(
        import_path=import_path,
        seed_path=target,
        percentile_window=3,
        min_periods=1,
    )

    run = run_external_source_refresh(
        naaim_exposure_spec(target_path=target, min_rows=1),
        adapter,
        tmp_path / "archive",
    )

    assert run.status == "PARSE_ERROR"
    assert "changed certified row 2026-06-24" in str(run.error_message)
    assert target.read_bytes() == certified


def test_naaim_latest_import_file_checks_hermes_external_imports(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    import_dir = tmp_path / ".hermes" / "external_imports"
    import_dir.mkdir(parents=True)
    official = import_dir / "USE_Data-since-Inception.xlsx"
    official.write_bytes(_naaim_xlsx())

    assert latest_import_file(profile_for("naaim_exposure")) == official
