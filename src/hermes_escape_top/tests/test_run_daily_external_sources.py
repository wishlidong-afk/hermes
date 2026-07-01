from __future__ import annotations

from types import SimpleNamespace

from hermes_escape_top.scripts import run_daily_package as rdp


def test_refresh_external_sources_runs_fred_bundle_without_raising(monkeypatch):
    calls = []

    def fake_refresh(source_id: str) -> dict:
        calls.append(source_id)
        return {"source_id": source_id, "status": "OK", "latest_promoted_as_of": "2026-06-26"}

    monkeypatch.setattr(rdp.refresh_external, "refresh_source", fake_refresh)

    out = rdp.refresh_external_sources()

    assert calls == list(rdp.refresh_external.SOURCE_IDS)
    assert [row["source_id"] for row in out] == list(rdp.refresh_external.SOURCE_IDS)
    assert all(row["status"] == "OK" for row in out)


def test_refresh_external_sources_keeps_daily_alive_on_single_source_failure(monkeypatch):
    def flaky(source_id: str) -> dict:
        if source_id == "real_rate":
            raise RuntimeError("fred timeout")
        return {"source_id": source_id, "status": "OK"}

    monkeypatch.setattr(rdp.refresh_external, "refresh_source", flaky)

    out = rdp.refresh_external_sources()

    assert [row["source_id"] for row in out] == list(rdp.refresh_external.SOURCE_IDS)
    by_source = {row["source_id"]: row for row in out}
    assert by_source["dollar"]["status"] == "OK"
    assert by_source["real_rate"]["status"] == "ERROR"
    assert "fred timeout" in by_source["real_rate"]["error"]
    assert by_source["fred_net_liquidity"]["status"] == "OK"


def test_execute_daily_runs_external_sources_before_legacy_soft_refresh(monkeypatch):
    calls = []

    monkeypatch.setattr(rdp, "refresh_history", lambda *_args, **_kwargs: calls.append("history"))
    monkeypatch.setattr(rdp, "_heal_lagging_symbols", lambda *_args, **_kwargs: calls.append("heal"))
    monkeypatch.setattr(rdp, "refresh_external_sources", lambda: calls.append("external") or [])
    monkeypatch.setattr(rdp, "refresh_soft_data", lambda: calls.append("soft"))
    monkeypatch.setattr(rdp, "_preflight_report", lambda *_args, **_kwargs: calls.append("preflight"))
    monkeypatch.setattr(rdp, "_history_integrity_scan", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(rdp, "run_score_pipeline", lambda *_args, **_kwargs: {"as_of": "2026-06-18"})
    monkeypatch.setattr(rdp, "translate", lambda _payload: {"orders_preview": {}})
    monkeypatch.setattr(rdp, "write_artifacts", lambda *_args, **_kwargs: calls.append("artifacts"))
    monkeypatch.setattr(rdp, "_post_run_diff", lambda *_args, **_kwargs: calls.append("diff"))
    monkeypatch.setattr(rdp, "_refresh_next5_unlock", lambda: calls.append("next5"))

    args = SimpleNamespace(
        live=False,
        skip_refresh=False,
        as_of="2026-06-18",
        run_type="manual_rerun",
        commit_state=False,
    )

    rdp._execute_daily(args=args, _lease=object(), _run_context={"step": "startup", "as_of": "2026-06-18"})

    assert calls[:4] == ["history", "heal", "external", "soft"]
