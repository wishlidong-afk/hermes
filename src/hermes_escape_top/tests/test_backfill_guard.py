"""Download sanity guard (2026-06-12 cross-wired yfinance incident)."""
from __future__ import annotations

import pandas as pd

from hermes_escape_top.scripts.backfill_history import _sanity_check_download


def _frame(closes, start="2026-06-01"):
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({"Close": closes}, index=idx)


def test_cross_wired_append_rejected():
    existing = _frame([700, 705, 710])
    wrong_ticker = _frame([218, 217, 220], start="2026-06-04")
    ok, why = _sanity_check_download("QQQ", existing, wrong_ticker)
    assert not ok and "boundary jump" in why


def test_normal_append_accepted():
    existing = _frame([700, 705, 710])
    ok, _ = _sanity_check_download("QQQ", existing, _frame([715, 720], start="2026-06-04"))
    assert ok


def test_vol_index_gets_wider_band_but_still_catches_cross_wiring():
    existing = _frame([15.4])
    ok, _ = _sanity_check_download("^VIX", existing, _frame([38.0], start="2026-06-02"))
    assert ok  # VIX 2.5x in a day is a real regime, not corruption
    ok, why = _sanity_check_download("^VIX", existing, _frame([12906.0], start="2026-06-02"))
    assert not ok  # ^SOX values under a ^VIX name


def test_overlap_anchor_mismatch_rejected():
    existing = _frame([700, 705, 710, 715, 720])
    garbage_repair = _frame([210, 212, 215, 214], start="2026-06-02")
    ok, why = _sanity_check_download("QQQ", existing, garbage_repair)
    assert not ok and "anchor" in why


def test_overlap_anchor_match_accepts_repair():
    existing = _frame([700, 705, 31.4, 715, 720])      # one corrupt mid row
    repair = _frame([705, 708, 712, 718], start="2026-06-02")  # anchors on clean 705
    ok, _ = _sanity_check_download("FNGS", existing, repair)
    assert ok


def test_integrity_scan_flags_cross_wired_file(tmp_path, monkeypatch):
    import importlib
    rdp = importlib.import_module("hermes_escape_top.scripts.run_daily_package")
    hist = tmp_path / "data" / "history"
    hist.mkdir(parents=True)
    (hist / "QQQ.csv").write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-06-04,740,745,738,742,742,1000\n"
        "2026-06-05,741,744,700,705,705,1000\n"
        "2026-06-08,220,221,214,217,217,1000\n")
    (hist / "_VIX.csv").write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-06-04,15,16,14,15.4,15.4,0\n"
        "2026-06-05,20,22,19,21.5,21.5,0\n")
    (hist / "KLAC.csv").write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-06-05,2043,2055,1928,1929.2,1929.2,1000\n"
        "2026-06-08,203,214,200,210.8,210.8,10000\n")
    monkeypatch.setenv("HERMES_DATA_DIR", str(tmp_path))
    from hermes_escape_top.config import load_config
    offenders = rdp._history_integrity_scan(load_config())
    assert any("QQQ.csv" in o for o in offenders)          # cross-wired bar caught
    assert not any("_VIX" in o for o in offenders)          # real VIX spike tolerated
    assert not any("KLAC.csv" in o for o in offenders)      # component split does not block scoring


def test_web_refresh_integrity_scan_flags_cross_wired_file(tmp_path):
    import importlib
    refresh = importlib.import_module("hermes_escape_top.web.refresh")
    hist = tmp_path / "history"
    hist.mkdir()
    (hist / "QQQ.csv").write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-06-04,740,745,738,742,742,1000\n"
        "2026-06-05,741,744,700,705,705,1000\n"
        "2026-06-08,220,221,214,217,217,1000\n",
        encoding="utf-8",
    )
    (hist / "_VIX.csv").write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-06-04,15,16,14,15.4,15.4,0\n"
        "2026-06-05,20,22,19,21.5,21.5,0\n",
        encoding="utf-8",
    )
    (hist / "KLAC.csv").write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2026-06-05,2043,2055,1928,1929.2,1929.2,1000\n"
        "2026-06-08,203,214,200,210.8,210.8,10000\n",
        encoding="utf-8",
    )

    offenders = refresh._history_integrity_scan({"paths": {"history_dir": str(hist)}})

    assert any("QQQ.csv" in item for item in offenders)
    assert not any("_VIX" in item for item in offenders)
    assert not any("KLAC.csv" in item for item in offenders)


def test_web_refresh_aborts_before_scoring_on_integrity_failure(tmp_path, monkeypatch):
    import importlib
    refresh = importlib.import_module("hermes_escape_top.web.refresh")
    cfg = {
        "paths": {
            "archive_dir": str(tmp_path / "archive"),
            "history_dir": str(tmp_path / "history"),
        },
        "symbols": {"MSTR": {}, "FNGU": {}, "SOXL": {}},
        "market_symbols": [],
        "radars": {},
        "component_proxies": {},
    }
    captured = {}

    monkeypatch.setattr(refresh, "load_config", lambda: cfg)
    monkeypatch.setattr(refresh, "latest_history_date", lambda *_args, **_kwargs: "2026-06-11")
    monkeypatch.setattr(refresh, "_history_is_fresh", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(refresh, "_stale_symbols", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(refresh, "_history_integrity_scan", lambda _cfg: ["QQQ.csv 2026-06-05 705.00 -> 2026-06-08 217.00"])
    monkeypatch.setattr(refresh, "score_pipeline", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("score_pipeline should not run")))

    def fake_write_refresh_run(*_args, **kwargs):
        captured.update(kwargs)
        return {"state_db_path": str(tmp_path / "archive" / "hermes_state.sqlite"), "refresh_run_id": 1}

    monkeypatch.setattr(refresh, "write_refresh_run", fake_write_refresh_run)

    try:
        refresh.refresh_score_with_market_data("latest")
    except RuntimeError as exc:
        assert "history integrity failed" in str(exc)
    else:
        raise AssertionError("refresh should abort on history integrity failure")

    assert captured["status"] == "ERROR"
    assert captured["refresh_status"]["history_integrity"]["offender_count"] == 1


def test_cboe_daily_pcr_parse_and_cross_check():
    from hermes_escape_top.scripts.refresh_cboe_daily_pcr import parse_page, validate
    body = ('x"EQUITY OPTIONS\\":[{\\"name\\":\\"VOLUME\\",\\"call\\":2598064,\\"put\\":1454199,'
            '\\"total\\":4052263}]y\\"selectedDate\\":\\"2026-06-11\\"z'
            '\\"EQUITY PUT/CALL RATIO\\",\\"value\\":\\"0.56\\"w')
    rec = parse_page(body)
    assert rec == {"date": "2026-06-11", "ratio": 0.56,
                   "call_volume": 2598064, "put_volume": 1454199}
    assert validate(rec, "2026-06-10") is None
    assert "not newer" in validate(rec, "2026-06-11")
    bad = dict(rec, ratio=0.90)
    assert "cross-check" in validate(bad, "2026-06-10")


def test_aaii_public_parse_and_validation():
    from datetime import date
    from hermes_escape_top.scripts.refresh_aaii_public import parse_rows, validate
    body = ('<td align="left" class="tableTxt">Jun 10</td>'
            '<td align="right" class="tableTxt">30.4% </td>'
            '<td align="right" class="tableTxt">22.0%</td>'
            '<td align="right" class="tableTxt">47.7% </td>'
            '<td align="left" class="tableTxt">Dec 31</td>'
            '<td align="right" class="tableTxt">40.0% </td>'
            '<td align="right" class="tableTxt">30.0%</td>'
            '<td align="right" class="tableTxt">30.0% </td>')
    rows = parse_rows(body, today=date(2026, 6, 12))
    assert rows[0]["reported"] == date(2026, 6, 10)
    assert rows[1]["reported"] == date(2025, 12, 31)   # year boundary inferred
    assert validate(rows[0]) is None
    assert "sum" in validate({"bull": 0.2, "neutral": 0.2, "bear": 0.2})
