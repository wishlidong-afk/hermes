from __future__ import annotations

from types import SimpleNamespace

from hermes_escape_top.core.data.market_admission import MarketAdmissionSession
from hermes_escape_top.scripts import run_daily_package as rdp


def test_refresh_external_sources_runs_registered_bundle_without_raising(monkeypatch):
    monkeypatch.setattr(
        rdp.refresh_external,
        "daily_source_check",
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
        "daily_source_check",
        lambda: {
            "ready": False,
            "blocking_sources": ["real_rate"],
                "warning_sources": [],
                "refresh": {
                    "runs": [
                        {
                            "source_id": source_id,
                            "status": "ERROR" if source_id == "real_rate" else "OK",
                            **({"error": "fred timeout"} if source_id == "real_rate" else {}),
                        }
                        for source_id in rdp.refresh_external.SOURCE_IDS
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


def test_refresh_soft_data_has_no_direct_canonical_writers_after_runner_migration(monkeypatch):
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
    assert only_args == []
    module_names = [
        args[args.index("-m") + 1]
        for args in calls
        if "-m" in args
    ]
    assert "hermes_escape_top.scripts.refresh_aaii_public" not in module_names
    assert "hermes_escape_top.scripts.backfill_cot" not in module_names
    assert "hermes_escape_top.scripts.backfill_occ_pcr" not in module_names
    assert "hermes_escape_top.scripts.refresh_cboe_daily_pcr" not in module_names
    assert "hermes_escape_top.scripts.backfill_crypto_micro" not in module_names
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


def test_execute_daily_attaches_external_source_status_to_returned_payload(monkeypatch):
    monkeypatch.setattr(rdp, "refresh_history", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(rdp, "_heal_lagging_symbols", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(rdp, "refresh_external_sources", lambda: [{"source_id": "dollar", "status": "OK"}])
    monkeypatch.setattr(
        rdp.refresh_external,
        "status",
        lambda *_args, **_kwargs: {"dollar": {"source_id": "dollar", "status": "OK"}},
    )
    monkeypatch.setattr(rdp, "refresh_soft_data", lambda: None)
    monkeypatch.setattr(rdp, "_preflight_report", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(rdp, "_history_integrity_scan", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(rdp, "run_score_pipeline", lambda *_args, **_kwargs: {"as_of": "2026-06-18"})
    monkeypatch.setattr(rdp, "translate", lambda _payload: {"orders_preview": {}})
    monkeypatch.setattr(rdp, "write_artifacts", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(rdp, "_post_run_diff", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(rdp, "_refresh_next5_unlock", lambda: None)
    args = SimpleNamespace(
        live=False,
        skip_refresh=False,
        as_of="2026-06-18",
        run_type="manual_rerun",
        commit_state=False,
    )

    payload = rdp._execute_daily(args=args, _lease=object(), _run_context={"step": "startup", "as_of": "2026-06-18"})

    assert payload["external_source_status"]["dollar"]["status"] == "OK"


def test_live_daily_attaches_nonblocking_market_witness(monkeypatch):
    monkeypatch.setattr(
        rdp,
        "refresh_history",
        lambda *_args, **_kwargs: {
            "mode": "enforce_consensus",
            "status": "OK",
            "admitted_rows": 3,
            "rejected_rows": 0,
        },
    )
    monkeypatch.setattr(rdp, "_heal_lagging_symbols", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(rdp, "refresh_external_sources", lambda: [])
    monkeypatch.setattr(rdp.refresh_external, "status", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(rdp, "refresh_soft_data", lambda: None)
    monkeypatch.setattr(
        rdp,
        "refresh_market_witness_status",
        lambda as_of: {"status": "WARN", "as_of": as_of, "summary": {"PRICE_MISMATCH": 1}},
    )
    monkeypatch.setattr(rdp, "_preflight_report", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(rdp, "_history_integrity_scan", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(rdp, "_refreeze_manifest", lambda: None)
    monkeypatch.setattr(rdp, "run_score_pipeline", lambda *_args, **_kwargs: {"as_of": "2026-07-10"})
    monkeypatch.setattr(rdp, "translate", lambda payload: {"orders_preview": {}, **payload})
    monkeypatch.setattr(rdp, "write_artifacts", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(rdp, "_post_run_diff", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(rdp, "_refresh_next5_unlock", lambda: None)
    monkeypatch.setattr("hermes_escape_top.core.data.audit.rotate_audit_log", lambda _path: None)
    args = SimpleNamespace(
        live=True,
        skip_refresh=False,
        as_of="2026-07-10",
        run_type="scheduled",
        commit_state=False,
    )

    payload = rdp._execute_daily(
        args=args,
        _lease=object(),
        _run_context={"step": "startup", "as_of": "2026-07-10"},
    )

    assert payload["market_witness_status"]["status"] == "WARN"
    assert payload["market_witness_status"]["summary"] == {"PRICE_MISMATCH": 1}
    assert payload["market_admission_status"]["status"] == "OK"
    assert payload["market_admission_status"]["admitted_rows"] == 3


def test_daily_prefers_current_session_error_over_stale_disk_ok(monkeypatch):
    session = MarketAdmissionSession(enabled=True, witness_bars={})
    session.run_error = "OSError: evidence disk full"
    score_calls = []
    monkeypatch.setattr(rdp, "_prepare_daily_market_admission", lambda *_args: session)
    monkeypatch.setattr(
        rdp,
        "refresh_history",
        lambda *_args, **_kwargs: {"mode": "enforce_consensus", "status": "OK"},
    )
    monkeypatch.setattr(rdp, "_heal_lagging_symbols", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        rdp,
        "read_market_admission_evidence",
        lambda *_args: {"mode": "enforce_consensus", "status": "OK"},
    )
    monkeypatch.setattr(rdp, "refresh_external_sources", lambda: [])
    monkeypatch.setattr(rdp.refresh_external, "status", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(rdp, "refresh_soft_data", lambda: None)
    monkeypatch.setattr(rdp, "_preflight_report", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(rdp, "_history_integrity_scan", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        rdp,
        "run_score_pipeline",
        lambda *_args, **kwargs: score_calls.append(kwargs) or {"as_of": "2026-07-13"},
    )
    monkeypatch.setattr(rdp, "translate", lambda payload: {"orders_preview": {}, **payload})
    monkeypatch.setattr(rdp, "write_artifacts", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(rdp, "_post_run_diff", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(rdp, "_refresh_next5_unlock", lambda: None)
    args = SimpleNamespace(
        live=False,
        skip_refresh=False,
        as_of="2026-07-13",
        run_type="manual_rerun",
        commit_state=False,
    )

    payload = rdp._execute_daily(
        args=args,
        _lease=object(),
        _run_context={"step": "startup", "as_of": "2026-07-13"},
    )

    assert payload["market_admission_status"]["status"] == "ERROR"
    assert "disk full" in payload["market_admission_status"]["run_error"]
    assert score_calls[0]["market_admission_status"]["operation_id"] == session.operation_id
