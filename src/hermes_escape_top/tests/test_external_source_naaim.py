from __future__ import annotations

import datetime as dt
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd

from hermes_escape_top.core.data.external_sources.ledger import latest_source_run
from hermes_escape_top.core.data.external_sources.naaim import (
    NaaimExposureAdapter,
    NaaimExposureImportAdapter,
    discover_naaim_xlsx_url,
    naaim_exposure_spec,
)
from hermes_escape_top.core.data.external_sources.profiles import latest_import_file, profile_for
from hermes_escape_top.core.data.external_sources.runner import run_external_source_refresh


def _naaim_xlsx() -> bytes:
    out = BytesIO()
    rows = [
        ["Date", "NAAIM Number", "Mean/Average", "Deviation"],
        [dt.date(2026, 6, 3).isoformat(), 86.82, 90.0, 72.07],
        [dt.date(2026, 6, 10).isoformat(), 79.27, 88.0, 53.30],
        [dt.date(2026, 6, 17).isoformat(), 92.83, 95.0, 49.11],
        [dt.date(2026, 6, 24).isoformat(), 98.59, 98.0, 43.91],
    ]
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


def test_naaim_latest_import_file_checks_hermes_external_imports(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    import_dir = tmp_path / ".hermes" / "external_imports"
    import_dir.mkdir(parents=True)
    official = import_dir / "USE_Data-since-Inception.xlsx"
    official.write_bytes(_naaim_xlsx())

    assert latest_import_file(profile_for("naaim_exposure")) == official
