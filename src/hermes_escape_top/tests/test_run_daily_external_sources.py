from __future__ import annotations

from types import SimpleNamespace

from hermes_escape_top.scripts import run_daily_package as rdp


def test_refresh_external_sources_runs_registered_bundle_without_raising(monkeypatch):
    monkeypatch.setattr(
        rdp.refresh_external,
        "pre_daily_check",
        lambda: {
            "ready": True,
            "blocking_sources": [],
            "warning_sources": [],
            "refresh": {
                "runs": [
                    {"source_id": source_id, "status": "OK", "latest_promoted_as_of": "2026-06-26"}
                    for source_id in rdp.refresh_external.SOURCE_IDS
                ]
            },
        },
    )

    out = rdp.refresh_external_sources()

    assert [row["source_id"] for row in out] == list(rdp.refresh_external.SOURCE_IDS)
    assert all(row["status"] == "OK" for row in out)


def test_refresh_external_sources_keeps_daily_alive_on_single_source_failure(monkeypatch):
    monkeypatch.setattr(
        rdp.refresh_external,
        "pre_daily_check",
        lambda: {
            "ready": False,
            "blocking_sources": ["real_rate"],
            "warning_sources": [],
            "refresh": {
                "runs": [
                    {"source_id": "dollar", "status": "OK"},
                    {"source_id": "real_rate", "status": "ERROR", "error": "fred timeout"},
                    {"source_id": "fred_net_liquidity", "status": "OK"},
                    {"source_id": "naaim_exposure", "status": "OK"},
                    {"source_id": "aaii_sentiment", "status": "OK"},
                ]
            },
        },
    )

    out = rdp.refresh_external_sources()

    assert [row["source_id"] for row in out] == list(rdp.refresh_external.SOURCE_IDS)
    by_source = {row["source_id"]: row for row in out}
    assert by_source["dollar"]["status"] == "OK"
    assert by_source["real_rate"]["status"] == "ERROR"
    assert "fred timeout" in by_source["real_rate"]["error"]
    assert by_source["fred_net_liquidity"]["status"] == "OK"


def test_refresh_soft_data_no_longer_refreshes_naaim_legacy(monkeypatch):
    calls = []

    def fake_run(args, **_kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(rdp.subprocess, "run", fake_run)

    rdp.refresh_soft_data()

    only_args = [
        args[args.index("--only") + 1]
        for args in calls
        if "--only" in args
    ]
    assert only_args == ["fred", "fred_risk", "cot"]
    assert "naaim" not in only_args


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
