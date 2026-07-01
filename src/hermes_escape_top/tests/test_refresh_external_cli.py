from __future__ import annotations

import json
from types import SimpleNamespace

from hermes_escape_top.core.data.external_sources.ledger import append_source_run
from hermes_escape_top.scripts import refresh_external


def _config(tmp_path):
    return {
        "paths": {
            "archive_dir": str(tmp_path / "archive"),
            "soft_history_dir": str(tmp_path / "soft_history"),
        },
        "features": {"data_dollar": True},
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
