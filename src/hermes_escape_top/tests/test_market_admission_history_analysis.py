from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "analyze_market_admission_history.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("market_admission_history_analysis", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(symbol: str, day: str, status: str, *, admitted: bool, volume: float = 0.0):
    return {
        "symbol": symbol,
        "date": day,
        "status": status,
        "admitted": admitted,
        "close_diff_pct": 0.0,
        "max_ohlc_diff_pct": 0.1,
        "volume_diff_pct": volume,
    }


def _artifact(run_day: str, completed: str, status: str, rows: list[dict]):
    return {
        "artifact_date": run_day,
        "completed_through": completed,
        "status": status,
        "evidence": rows,
    }


def test_analysis_deduplicates_sessions_and_tracks_next_run_recovery():
    module = _load_module()
    artifacts = [
        _artifact(
            "2026-07-21",
            "2026-07-20",
            "BLOCKED",
            [_row("BRK.B", "2026-07-20", "VOLUME_MISMATCH", admitted=False, volume=30.0)],
        ),
        _artifact(
            "2026-07-22",
            "2026-07-21",
            "BLOCKED",
            [
                _row("BRK.B", "2026-07-20", "MATCH", admitted=True, volume=0.2),
                _row("AMZN", "2026-07-21", "PRICE_MISMATCH", admitted=False),
                {
                    "symbol": "BTC-USD",
                    "date": "2026-07-21",
                    "status": "DEFERRED_UNFINALIZED",
                    "admitted": False,
                    "blocking": False,
                },
            ],
        ),
        _artifact(
            "2026-07-23",
            "2026-07-21",
            "OK",
            [_row("AMZN", "2026-07-21", "MATCH", admitted=True)],
        ),
    ]

    report = module.analyze_artifacts(artifacts, target_sessions=30)

    assert report["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert report["sample"]["available_sessions"] == 2
    assert report["sample"]["session_selection_policy"] == (
        "FIRST_ARTIFACT_PER_COMPLETED_THROUGH"
    )
    assert report["session_summary"]["blocked_sessions"] == 2
    assert report["session_summary"]["blocked_session_rate_pct"] == 100.0
    assert report["blocking_summary"]["unique_events"] == 2
    assert report["blocking_summary"]["matured_events"] == 2
    assert report["blocking_summary"]["recovered_events"] == 2
    assert report["blocking_summary"]["next_run_recoveries"] == 2
    assert report["blocking_summary"]["deferred_rows_excluded"] == 1


def test_analysis_keeps_latest_unresolved_event_pending():
    module = _load_module()
    artifacts = [
        _artifact(
            "2026-07-28",
            "2026-07-27",
            "BLOCKED",
            [_row("SMH", "2026-07-27", "VOLUME_MISMATCH", admitted=False, volume=26.0)],
        )
    ]

    report = module.analyze_artifacts(artifacts, target_sessions=1)

    assert report["evidence_status"] == "SUFFICIENT"
    assert report["blocking_summary"]["matured_events"] == 0
    assert report["blocking_summary"]["pending_events"] == 1
    assert report["events"][0]["resolution_status"] == "PENDING_NO_LATER_EVIDENCE"


def test_recovery_distance_counts_artifact_runs_not_only_reobservations():
    module = _load_module()
    artifacts = [
        _artifact(
            "2026-07-21",
            "2026-07-20",
            "BLOCKED",
            [_row("BRK.B", "2026-07-20", "VOLUME_MISMATCH", admitted=False, volume=30.0)],
        ),
        _artifact(
            "2026-07-22",
            "2026-07-21",
            "OK",
            [_row("SPY", "2026-07-21", "MATCH", admitted=True)],
        ),
        _artifact(
            "2026-07-23",
            "2026-07-22",
            "OK",
            [_row("BRK.B", "2026-07-20", "MATCH", admitted=True)],
        ),
    ]

    report = module.analyze_artifacts(artifacts, target_sessions=3)

    assert report["events"][0]["runs_to_recovery"] == 2
    assert report["blocking_summary"]["next_run_recoveries"] == 0


def test_loader_ignores_latest_alias_and_reads_dated_artifacts(tmp_path: Path):
    module = _load_module()
    payload = _artifact("ignored", "2026-07-27", "OK", [])
    dated = tmp_path / "market_admission_2026-07-28.json"
    dated.write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "market_admission_latest.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    artifacts = module.load_artifacts(tmp_path)

    assert len(artifacts) == 1
    assert artifacts[0]["artifact_date"] == "2026-07-28"
    assert artifacts[0]["artifact_sha256"] == hashlib.sha256(dated.read_bytes()).hexdigest()


def test_loader_ignores_separate_third_source_shadow_artifacts(tmp_path: Path):
    module = _load_module()
    payload = _artifact("ignored", "2026-08-05", "OK", [])
    (tmp_path / "market_admission_2026-08-06.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    shadow = {"schema_version": "hermes-market-admission-third-source-shadow-v1"}
    (tmp_path / "market_admission_third_source_2026-08-06.json").write_text(
        json.dumps(shadow),
        encoding="utf-8",
    )
    (tmp_path / "market_admission_third_source_latest.json").write_text(
        json.dumps(shadow),
        encoding="utf-8",
    )

    artifacts = module.load_artifacts(tmp_path)

    assert len(artifacts) == 1
    assert artifacts[0]["artifact_date"] == "2026-08-06"


def test_source_manifest_is_stable_across_archive_locations(tmp_path: Path):
    payload = _artifact("ignored", "2026-07-27", "OK", [])
    reports = []
    for name in ("first", "second"):
        archive = tmp_path / name
        archive.mkdir()
        (archive / "market_admission_2026-07-28.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )
        reports.append(module_report := _load_module().analyze_artifacts(
            _load_module().load_artifacts(archive),
            target_sessions=1,
        ))
        assert module_report["source_evidence"]["artifacts"][0]["path"] == (
            "market_admission_2026-07-28.json"
        )

    assert (
        reports[0]["source_evidence"]["artifact_manifest_sha256"]
        == reports[1]["source_evidence"]["artifact_manifest_sha256"]
    )


def test_field_aware_shadow_only_avoids_non_required_volume_blocks():
    module = _load_module()
    volume_only = _row(
        "BRK.B",
        "2026-08-05",
        "VOLUME_MISMATCH",
        admitted=False,
        volume=36.4139,
    )
    volume_only.update(
        price_evidence_status="MATCH",
        volume_evidence_status="MISMATCH",
    )
    price_mismatch = _row(
        "AMZN",
        "2026-08-05",
        "PRICE_MISMATCH",
        admitted=False,
    )
    price_mismatch.update(
        price_evidence_status="MISMATCH",
        volume_evidence_status="MATCH",
    )
    inventory = {
        "BRK.B": {"volume_required": False},
        "AMZN": {"volume_required": True},
    }

    report = module.analyze_artifacts(
        [
            _artifact(
                "2026-08-06",
                "2026-08-05",
                "BLOCKED",
                [volume_only, price_mismatch],
            )
        ],
        target_sessions=30,
        field_inventory=inventory,
    )

    assert report["policy_decision"] == "HOLD_FAIL_CLOSED_POLICY"
    assert report["field_aware_shadow"] == {
        "research_only": True,
        "current_blocked_sessions": 1,
        "simulated_blocked_sessions": 1,
        "avoided_blocked_sessions": 0,
        "eligible_volume_only_events": 1,
    }
    events = {event["symbol"]: event for event in report["events"]}
    assert events["BRK.B"]["field_aware_shadow_status"] == (
        "WOULD_ADMIT_PRICE_CONSENSUS"
    )
    assert events["AMZN"]["field_aware_shadow_status"] == "REMAINS_BLOCKED"


def test_field_aware_shadow_counts_session_avoided_when_all_blocks_are_eligible():
    module = _load_module()
    row = _row(
        "BRK.B",
        "2026-08-05",
        "VOLUME_MISMATCH",
        admitted=False,
        volume=36.4139,
    )
    row.update(price_evidence_status="MATCH", volume_evidence_status="MISMATCH")

    report = module.analyze_artifacts(
        [_artifact("2026-08-06", "2026-08-05", "BLOCKED", [row])],
        target_sessions=30,
        field_inventory={"BRK.B": {"volume_required": False}},
    )

    assert report["field_aware_shadow"]["current_blocked_sessions"] == 1
    assert report["field_aware_shadow"]["simulated_blocked_sessions"] == 0
    assert report["field_aware_shadow"]["avoided_blocked_sessions"] == 1


def test_field_inventory_evidence_is_bound_and_order_independent():
    module = _load_module()
    artifacts = [_artifact("2026-08-06", "2026-08-05", "OK", [])]
    first = {
        "BRK.B": {"volume_required": False, "decision_fields": ["close"]},
        "QQQ": {"volume_required": True, "decision_fields": ["close", "volume"]},
    }
    second = dict(reversed(list(first.items())))

    report_a = module.analyze_artifacts(
        artifacts,
        target_sessions=30,
        field_inventory=first,
    )
    report_b = module.analyze_artifacts(
        artifacts,
        target_sessions=30,
        field_inventory=second,
    )

    evidence = report_a["field_inventory_evidence"]
    assert evidence["schema_version"] == "hermes-market-field-inventory-v1"
    assert evidence["symbols"] == first
    assert len(evidence["sha256"]) == 64
    assert evidence["sha256"] == report_b["field_inventory_evidence"]["sha256"]
