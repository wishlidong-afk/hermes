from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

from hermes_escape_top.core.data.external_sources.ledger import append_source_run
from hermes_escape_top.scripts import refresh_external


def _config(tmp_path):
    return {
        "paths": {
            "archive_dir": str(tmp_path / "archive"),
            "soft_history_dir": str(tmp_path / "soft_history"),
        },
        "features": {
            "data_dollar": True,
            "data_real_rate": True,
            "data_net_liquidity": True,
            "data_naaim": True,
            "data_aaii": True,
        },
    }


def test_refresh_external_source_dollar_calls_runner(monkeypatch, tmp_path):
    calls = {}

    def fake_runner(spec, adapter, archive_dir):
        calls["spec"] = spec
        calls["adapter"] = adapter
        calls["archive_dir"] = archive_dir
        return SimpleNamespace(to_dict=lambda: {"source_id": spec.source_id, "status": "OK"})

    monkeypatch.setattr(refresh_external, "load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(refresh_external, "run_external_source_refresh", fake_runner)

    result = refresh_external.refresh_source("dollar")

    assert result["status"] == "OK"
    assert calls["spec"].source_id == "dollar"
    assert calls["spec"].target_path == tmp_path / "soft_history" / "dollar.csv"
    assert calls["adapter"].series_id == "DTWEXBGS"
    assert calls["archive_dir"] == tmp_path / "archive"


def test_refresh_external_source_real_rate_calls_runner(monkeypatch, tmp_path):
    calls = {}

    def fake_runner(spec, adapter, archive_dir):
        calls["spec"] = spec
        calls["adapter"] = adapter
        calls["archive_dir"] = archive_dir
        return SimpleNamespace(to_dict=lambda: {"source_id": spec.source_id, "status": "OK"})

    monkeypatch.setattr(refresh_external, "load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(refresh_external, "run_external_source_refresh", fake_runner)

    result = refresh_external.refresh_source("real_rate")

    assert result["status"] == "OK"
    assert calls["spec"].source_id == "real_rate"
    assert calls["spec"].target_path == tmp_path / "soft_history" / "real_rate.csv"
    assert calls["adapter"].series_id == "DFII10"
    assert calls["adapter"].field == "real_rate_10y"
    assert calls["archive_dir"] == tmp_path / "archive"


def test_refresh_external_source_fred_net_liquidity_calls_runner(monkeypatch, tmp_path):
    calls = {}

    def fake_runner(spec, adapter, archive_dir):
        calls["spec"] = spec
        calls["adapter"] = adapter
        calls["archive_dir"] = archive_dir
        return SimpleNamespace(to_dict=lambda: {"source_id": spec.source_id, "status": "OK"})

    monkeypatch.setattr(refresh_external, "load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(refresh_external, "run_external_source_refresh", fake_runner)

    result = refresh_external.refresh_source("fred_net_liquidity")

    assert result["status"] == "OK"
    assert calls["spec"].source_id == "fred_net_liquidity"
    assert calls["spec"].target_path == tmp_path / "soft_history" / "fred_net_liquidity.csv"
    assert calls["spec"].required_columns == (
        "date",
        "publish_date",
        "walcl",
        "wtregen",
        "rrp",
        "net_liq",
        "net_liq_chg10",
        "net_liq_chg10_pctl",
    )
    assert calls["archive_dir"] == tmp_path / "archive"


def test_refresh_external_source_naaim_calls_runner(monkeypatch, tmp_path):
    calls = {}

    def fake_runner(spec, adapter, archive_dir):
        calls["spec"] = spec
        calls["adapter"] = adapter
        calls["archive_dir"] = archive_dir
        return SimpleNamespace(to_dict=lambda: {"source_id": spec.source_id, "status": "OK"})

    monkeypatch.setattr(refresh_external, "load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(refresh_external, "run_external_source_refresh", fake_runner)

    result = refresh_external.refresh_source("naaim_exposure")

    assert result["status"] == "OK"
    assert calls["spec"].source_id == "naaim_exposure"
    assert calls["spec"].target_path == tmp_path / "soft_history" / "naaim_exposure.csv"
    assert calls["spec"].required_columns == (
        "date",
        "publish_date",
        "naaim_exposure",
        "naaim_pctl",
        "is_proxy",
    )
    assert calls["adapter"].index_url.endswith("/programs/naaim-exposure-index/")
    assert calls["archive_dir"] == tmp_path / "archive"


def test_refresh_external_source_aaii_calls_runner(monkeypatch, tmp_path):
    calls = {}

    def fake_runner(spec, adapter, archive_dir):
        calls["spec"] = spec
        calls["adapter"] = adapter
        calls["archive_dir"] = archive_dir
        return SimpleNamespace(to_dict=lambda: {"source_id": spec.source_id, "status": "OK"})

    monkeypatch.setattr(refresh_external, "load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(refresh_external, "run_external_source_refresh", fake_runner)

    result = refresh_external.refresh_source("aaii_sentiment")

    assert result["status"] == "OK"
    assert calls["spec"].source_id == "aaii_sentiment"
    assert calls["spec"].target_path == tmp_path / "soft_history" / "aaii_sentiment.csv"
    assert calls["spec"].required_columns == (
        "date",
        "publish_date",
        "aaii_bull",
        "aaii_bear",
        "aaii_bull_bear_spread",
        "aaii_bull_pctl",
        "aaii_spread_pctl",
    )
    assert calls["adapter"].url.endswith("/sentimentsurvey/sent_results")
    assert calls["archive_dir"] == tmp_path / "archive"


def test_refresh_external_status_prints_latest_ledger(monkeypatch, tmp_path, capsys):
    cfg = _config(tmp_path)
    append_source_run(
        tmp_path / "archive",
        {
            "source_id": "dollar",
            "status": "OK",
            "latest_promoted_as_of": "2026-06-30",
        },
    )
    monkeypatch.setattr(refresh_external, "load_config", lambda: cfg)

    rc = refresh_external.main(["--status"])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["dollar"]["status"] == "OK"
    assert out["dollar"]["latest_promoted_as_of"] == "2026-06-30"
    assert out["real_rate"]["status"] == "MISSING"
    assert out["fred_net_liquidity"]["status"] == "MISSING"
    assert out["naaim_exposure"]["status"] == "MISSING"
    assert out["aaii_sentiment"]["status"] == "MISSING"


def test_refresh_external_status_adds_profile_and_freshness(monkeypatch, tmp_path):
    cfg = _config(tmp_path)
    append_source_run(
        tmp_path / "archive",
        {
            "source_id": "dollar",
            "status": "OK",
            "latest_promoted_as_of": "2026-06-18",
        },
    )
    append_source_run(
        tmp_path / "archive",
        {
            "source_id": "aaii_sentiment",
            "status": "FETCH_ERROR",
            "error_message": "AAII public endpoint blocked",
        },
    )

    out = refresh_external.status(cfg, today=date(2026, 7, 2))

    assert out["dollar"]["cadence"] == "weekly"
    assert out["dollar"]["max_age_days"] == 10
    assert out["dollar"]["age_days"] == 14
    assert out["dollar"]["freshness_status"] == "STALE"
    assert out["dollar"]["next_action"].startswith("run refresh_external")
    assert out["aaii_sentiment"]["failure_kind"] == "AUTH_REQUIRED"
    assert "--import-file" in out["aaii_sentiment"]["next_action"]


def test_refresh_external_status_explains_due_soon_after_same_day_success(tmp_path):
    cfg = _config(tmp_path)
    append_source_run(
        tmp_path / "archive",
        {
            "source_id": "dollar",
            "status": "OK",
            "latest_promoted_as_of": "2026-06-26",
            "finished_at": "2026-07-04T12:56:31+00:00",
        },
    )

    out = refresh_external.status(cfg, today=date(2026, 7, 4))

    assert out["dollar"]["freshness_status"] == "DUE_SOON"
    assert out["dollar"]["publisher_status"] == "UNCHANGED_AFTER_REFRESH"
    assert "wait for publisher update" in out["dollar"]["next_action"]
    assert "run refresh_external --source dollar" not in out["dollar"]["next_action"]


def test_refresh_external_all_sources_keeps_going_on_single_failure(monkeypatch, tmp_path):
    calls = []
    cfg = _config(tmp_path)

    def fake_refresh(source_id: str, config=None, **_kwargs):
        assert config is cfg
        calls.append(source_id)
        if source_id == "aaii_sentiment":
            raise RuntimeError("blocked")
        return {"source_id": source_id, "status": "OK"}

    monkeypatch.setattr(refresh_external, "load_config", lambda: cfg)
    monkeypatch.setattr(refresh_external, "refresh_source", fake_refresh)

    result = refresh_external.refresh_all_sources()

    assert calls == list(refresh_external.SOURCE_IDS)
    assert result["ok"] is False
    assert result["ok_count"] == len(refresh_external.SOURCE_IDS) - 1
    assert result["error_count"] == 1
    assert [row["source_id"] for row in result["runs"]] == list(refresh_external.SOURCE_IDS)
    assert result["runs"][-1]["status"] == "ERROR"
    assert "blocked" in result["runs"][-1]["error"]


def test_refresh_external_pre_daily_check_marks_stale_sources_not_ready(monkeypatch, tmp_path):
    cfg = _config(tmp_path)
    monkeypatch.setattr(
        refresh_external,
        "refresh_all_sources",
        lambda config=None, auto_import=True: {"ok": True, "ok_count": 5, "error_count": 0, "runs": []},
    )
    monkeypatch.setattr(
        refresh_external,
        "status",
        lambda config=None, today=None: {
            "dollar": {"source_id": "dollar", "status": "OK", "freshness_status": "STALE", "next_action": "refresh dollar"},
            "real_rate": {"source_id": "real_rate", "status": "OK", "freshness_status": "OK"},
        },
    )

    result = refresh_external.pre_daily_check(cfg, today=date(2026, 7, 2))

    assert result["ready"] is False
    assert result["blocking_sources"] == ["dollar"]
    assert result["sources"]["dollar"]["next_action"] == "refresh dollar"


def test_refresh_external_source_auto_imports_latest_official_file_after_fetch_error(monkeypatch, tmp_path):
    cfg = _config(tmp_path)
    import_path = tmp_path / "sentiment.xls"
    import_path.write_bytes(b"official file")
    calls = []

    def fake_runner(spec, adapter, archive_dir):
        calls.append(type(adapter).__name__)
        if len(calls) == 1:
            return SimpleNamespace(to_dict=lambda: {
                "source_id": spec.source_id,
                "status": "FETCH_ERROR",
                "error_message": "AAII public endpoint blocked",
            })
        return SimpleNamespace(to_dict=lambda: {
            "source_id": spec.source_id,
            "status": "OK",
            "latest_promoted_as_of": "2026-06-25",
        })

    monkeypatch.setattr(refresh_external, "run_external_source_refresh", fake_runner)
    monkeypatch.setattr(refresh_external, "latest_import_file", lambda _profile: import_path)

    result = refresh_external.refresh_source("aaii_sentiment", cfg, auto_import=True)

    assert calls == ["AaiiSentimentAdapter", "AaiiSentimentImportAdapter"]
    assert result["status"] == "OK"
    assert result["latest_promoted_as_of"] == "2026-06-25"
    assert result["fallback_from_status"] == "FETCH_ERROR"
    assert result["fallback_import_file"] == str(import_path)


def test_open_official_download_waits_for_new_file_and_imports(monkeypatch, tmp_path):
    opened = []
    downloaded = tmp_path / "sentiment.xls"

    def fake_opener(url: str) -> None:
        opened.append(url)
        downloaded.write_bytes(b"official xls")

    monkeypatch.setattr(
        refresh_external,
        "refresh_source",
        lambda source_id, config=None, import_file=None, **_kwargs: {
            "source_id": source_id,
            "status": "OK",
            "import_file": import_file,
        },
    )

    result = refresh_external.open_official_download_and_import(
        "aaii_sentiment",
        _config(tmp_path),
        downloads_dir=tmp_path,
        opener=fake_opener,
        timeout_seconds=0.1,
        poll_seconds=0.01,
    )

    assert opened == ["https://www.aaii.com/files/surveys/sentiment.xls"]
    assert result["status"] == "OK"
    assert result["import_file"] == str(downloaded)
    assert result["downloaded_file"] == str(downloaded)


def test_refresh_external_cli_accepts_real_rate(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(refresh_external, "load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        refresh_external,
        "run_external_source_refresh",
        lambda spec, adapter, archive_dir: SimpleNamespace(to_dict=lambda: {"source_id": spec.source_id, "status": "OK"}),
    )

    rc = refresh_external.main(["--source", "real_rate"])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["source_id"] == "real_rate"
    assert out["status"] == "OK"


def test_refresh_external_cli_accepts_naaim(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(refresh_external, "load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        refresh_external,
        "run_external_source_refresh",
        lambda spec, adapter, archive_dir: SimpleNamespace(to_dict=lambda: {"source_id": spec.source_id, "status": "OK"}),
    )

    rc = refresh_external.main(["--source", "naaim_exposure"])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["source_id"] == "naaim_exposure"
    assert out["status"] == "OK"


def test_refresh_external_cli_accepts_aaii(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(refresh_external, "load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        refresh_external,
        "run_external_source_refresh",
        lambda spec, adapter, archive_dir: SimpleNamespace(to_dict=lambda: {"source_id": spec.source_id, "status": "OK"}),
    )

    rc = refresh_external.main(["--source", "aaii_sentiment"])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["source_id"] == "aaii_sentiment"
    assert out["status"] == "OK"


def test_refresh_external_cli_accepts_aaii_import_file(monkeypatch, tmp_path, capsys):
    calls = {}
    import_path = tmp_path / "sentiment.csv"
    import_path.write_text("Reported,Bullish,Neutral,Bearish,Bull-Bear\n2026-07-02,38.2,28.0,33.8,4.4\n", encoding="utf-8")

    def fake_runner(spec, adapter, archive_dir):
        calls["adapter"] = adapter
        return SimpleNamespace(to_dict=lambda: {"source_id": spec.source_id, "status": "OK"})

    monkeypatch.setattr(refresh_external, "load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(refresh_external, "run_external_source_refresh", fake_runner)

    rc = refresh_external.main(["--source", "aaii_sentiment", "--import-file", str(import_path)])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["source_id"] == "aaii_sentiment"
    assert out["status"] == "OK"
    assert calls["adapter"].import_path == import_path


def test_refresh_external_cli_accepts_naaim_import_file(monkeypatch, tmp_path, capsys):
    calls = {}
    import_path = tmp_path / "naaim.xlsx"
    import_path.write_bytes(b"fake workbook")

    def fake_runner(spec, adapter, archive_dir):
        calls["spec"] = spec
        calls["adapter"] = adapter
        return SimpleNamespace(to_dict=lambda: {"source_id": spec.source_id, "status": "OK"})

    monkeypatch.setattr(refresh_external, "load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(refresh_external, "run_external_source_refresh", fake_runner)

    rc = refresh_external.main(["--source", "naaim_exposure", "--import-file", str(import_path)])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["source_id"] == "naaim_exposure"
    assert out["status"] == "OK"
    assert calls["spec"].source_id == "naaim_exposure"
    assert calls["adapter"].import_path == import_path


def test_refresh_external_cli_rejects_import_file_without_source(capsys):
    with pytest.raises(SystemExit) as exc:
        refresh_external.main(["--import-file", "/tmp/sentiment.csv"])

    assert exc.value.code == 2
    assert "--import-file requires --source" in capsys.readouterr().err


def test_refresh_external_cli_rejects_import_file_for_unsupported_source(capsys):
    with pytest.raises(SystemExit) as exc:
        refresh_external.main(["--source", "dollar", "--import-file", "/tmp/dollar.csv"])

    assert exc.value.code == 2
    assert "--import-file is supported only for" in capsys.readouterr().err


def test_refresh_external_cli_accepts_all(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(refresh_external, "load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        refresh_external,
        "refresh_all_sources",
        lambda **_kwargs: {"ok": True, "ok_count": 5, "error_count": 0, "runs": []},
    )

    rc = refresh_external.main(["--all"])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["ok"] is True
    assert out["ok_count"] == 5
