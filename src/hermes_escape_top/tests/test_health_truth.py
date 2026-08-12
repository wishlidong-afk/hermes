from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone

from hermes_escape_top.core.reporting.system_health import build_system_health_audit_dimensions
from hermes_escape_top.web.health import (
    compute_health,
    post_deploy_certification,
    runtime_release_identity,
)
from hermes_escape_top.web.refresh import _completed_trading_days_after


DAY = date(2026, 6, 18)
NOW = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)


def _payload() -> dict:
    return {
        "as_of": DAY.isoformat(),
        "cache_status": {"hit": True},
        "data_quality": {"level": "HIGH", "overall_score": 1.0},
        "data_quality_breakdown": {"sources": []},
        "ibkr": {
            "source": "tws",
            "sync_time": (NOW - timedelta(minutes=5)).isoformat(),
            "snapshot_stale": False,
        },
        "run_receipt": {
            "status": "OK",
            "run_type": "scheduled",
            "run_at": NOW.isoformat(),
            "started_at": (NOW - timedelta(minutes=5)).isoformat(),
            "finished_at": NOW.isoformat(),
            "ok": True,
            "checks": [],
        },
        "alpaca_daily_flow": {"as_of": DAY.isoformat()},
    }


def _health(payload: dict) -> dict:
    return compute_health(
        payload,
        {"status": "OK"},
        today=DAY,
        now=NOW,
        ibkr_max_age_seconds=900,
        receipt_timeout_seconds=7200,
    )


def test_ibkr_age_is_recomputed_from_sync_time_without_degrading_strategy_health():
    payload = _payload()
    payload["ibkr"]["sync_time"] = "2026-01-01T00:00:00+00:00"
    payload["ibkr"]["snapshot_stale"] = False

    health = _health(payload)

    assert health["level"] == "OK"
    assert health["layers"]["position_reconciliation"]["level"] == "INFO"
    assert health["ibkr_age_seconds"] > 900
    check = next(check for check in health["checks"] if "IBKR 快照陈旧" in check["label"])
    assert check["level"] == "INFO"
    assert check["layer"] == "position_reconciliation"


def test_ibkr_unavailable_is_auxiliary_not_strategy_degradation():
    payload = _payload()
    payload["ibkr"] = {
        "source": "unavailable",
        "error": "Gateway offline",
    }

    health = _health(payload)

    assert health["level"] == "OK"
    assert health["layers"]["position_reconciliation"]["level"] == "INFO"
    check = next(check for check in health["checks"] if "IBKR 未连接" in check["label"])
    assert check["level"] == "INFO"
    assert check["layer"] == "position_reconciliation"
    assert "Gateway offline" in check["detail"]


def test_failed_scheduled_receipt_is_critical():
    payload = _payload()
    payload["run_receipt"].update({
        "status": "FAILED",
        "ok": False,
        "failed_step": "artifact_write",
        "error": "OSError: disk full",
    })

    health = _health(payload)

    assert health["level"] == "CRITICAL"
    assert any("官方 run 失败" in check["label"] for check in health["checks"])


def test_stuck_running_receipt_is_critical():
    payload = _payload()
    payload["run_receipt"].update({
        "status": "RUNNING",
        "ok": False,
        "started_at": (NOW - timedelta(hours=3)).isoformat(),
        "finished_at": None,
    })

    health = _health(payload)

    assert health["level"] == "CRITICAL"
    assert any("官方 run 超时" in check["label"] for check in health["checks"])


def test_old_health_report_after_release_swap_is_visible_as_nonblocking_pending():
    payload = _payload()
    payload["system_health_report"] = {
        "generated_at": "2026-06-18T07:11:00+00:00",
        "generator_release_hash": "old123",
        "generator_policy_sha256": "policy-old",
    }
    payload["runtime_release_identity"] = {
        "release_hash": "new456",
        "policy_sha256": "policy-new",
        "attested_at": "2026-06-18T08:00:00+00:00",
    }

    health = _health(payload)

    assert health["level"] == "OK"
    assert health["post_deploy_certification"]["status"] == "PENDING_POST_DEPLOY"
    pending = next(
        row for row in health["checks"] if row["label"] == "新版本待自然日跑再认证"
    )
    assert pending["level"] == "INFO"
    assert pending["layer"] == "operations"


def test_health_report_generator_mismatch_after_deploy_is_critical():
    payload = _payload()
    payload["system_health_report"] = {
        "generated_at": "2026-06-18T08:01:00+00:00",
        "generator_release_hash": "old123",
        "generator_policy_sha256": "policy-old",
    }
    payload["runtime_release_identity"] = {
        "release_hash": "new456",
        "policy_sha256": "policy-new",
        "attested_at": "2026-06-18T08:00:00+00:00",
    }

    health = _health(payload)

    assert health["level"] == "CRITICAL"
    assert health["post_deploy_certification"]["status"] == "GENERATOR_MISMATCH"


def test_same_hash_redeploy_still_waits_for_a_post_attestation_report():
    certification = compute_health(
        {
            **_payload(),
            "system_health_report": {
                "generated_at": "2026-06-18T07:11:00+00:00",
                "generator_release_hash": "same123",
                "generator_policy_sha256": "same-policy",
            },
            "runtime_release_identity": {
                "release_hash": "same123",
                "policy_sha256": "same-policy",
                "attested_at": "2026-06-18T08:00:00+00:00",
            },
        },
        {"status": "OK"},
        today=DAY,
        now=NOW,
    )["post_deploy_certification"]

    assert certification["status"] == "PENDING_POST_DEPLOY"


def test_matching_post_deploy_report_waits_until_next_natural_schedule():
    runtime = {
        "release_hash": "same123",
        "policy_sha256": "same-policy",
        "attested_at": "2026-06-18T08:00:00+00:00",
    }
    before_schedule = post_deploy_certification(
        {
            "generated_at": "2026-06-18T08:01:00+00:00",
            "generator_release_hash": "same123",
            "generator_policy_sha256": "same-policy",
        },
        runtime,
    )
    after_schedule = post_deploy_certification(
        {
            "generated_at": "2026-06-18T23:11:00+00:00",
            "generator_release_hash": "same123",
            "generator_policy_sha256": "same-policy",
        },
        runtime,
    )

    assert before_schedule["status"] == "PENDING_POST_DEPLOY"
    assert before_schedule["next_scheduled_at"] == "2026-06-19T07:10:00+08:00"
    assert after_schedule["status"] == "CERTIFIED"


def test_runtime_release_identity_fails_closed_on_policy_drift(tmp_path):
    policy = tmp_path / "governance/approved_live_config.json"
    policy.parent.mkdir(parents=True)
    policy.write_text('{"schema_version":"policy"}\n', encoding="utf-8")
    policy_sha = hashlib.sha256(policy.read_bytes()).hexdigest()
    (tmp_path / "VERSION").write_text("abc123 20260812_090000\n", encoding="utf-8")
    (tmp_path / "LIVE_CONFIG_ATTESTATION.json").write_text(
        json.dumps(
            {
                "release_hash": "abc123",
                "policy_sha256": policy_sha,
                "generated_at": "2026-08-12T09:00:00+08:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    verified = runtime_release_identity(tmp_path)
    policy.write_text('{"schema_version":"drifted"}\n', encoding="utf-8")
    drifted = runtime_release_identity(tmp_path)

    assert verified["status"] == "VERIFIED"
    assert verified["release_hash"] == "abc123"
    assert drifted["status"] == "INVALID"
    assert "policy sha256" in drifted["error"]


def test_stale_sip_as_of_degrades_without_failing_core_receipt():
    payload = _payload()
    payload["alpaca_daily_flow"]["as_of"] = "2026-06-15"

    health = _health(payload)

    assert health["level"] == "OK"
    assert health["layers"]["strategy_data"]["level"] == "OK"
    assert health["layers"]["auxiliary_flows"]["level"] == "DEGRADED"
    assert health["receipt_status"] == "OK"
    check = next(check for check in health["checks"] if "SIP 资金流陈旧" in check["label"])
    assert check["layer"] == "auxiliary_flows"


def test_observed_us_market_holiday_does_not_count_as_stale_trading_day():
    today = date(2026, 7, 4)
    now = datetime(2026, 7, 4, 8, 0, tzinfo=timezone.utc)
    payload = _payload()
    payload["as_of"] = "2026-07-02"
    payload["alpaca_daily_flow"]["as_of"] = "2026-07-02"
    payload["run_receipt"].update({
        "run_at": now.isoformat(),
        "started_at": (now - timedelta(minutes=2)).isoformat(),
        "finished_at": now.isoformat(),
    })

    health = compute_health(
        payload,
        {"status": "OK"},
        today=today,
        now=now,
        ibkr_max_age_seconds=900,
        receipt_timeout_seconds=7200,
    )

    assert health["level"] == "OK"
    assert health["stale_trading_days"] == 0
    assert not any("行情落后" in check["label"] for check in health["checks"])
    assert not any("SIP 资金流陈旧" in check["label"] for check in health["checks"])


def test_completed_trading_days_skip_good_friday_but_count_regular_session():
    assert _completed_trading_days_after("2026-04-02", date(2026, 4, 4)) == 0
    assert _completed_trading_days_after("2026-04-02", date(2026, 4, 7)) == 1


def test_completed_trading_days_keep_friday_open_before_saturday_new_year():
    assert _completed_trading_days_after("2027-12-29", date(2028, 1, 4)) == 3


def test_sip_refresh_error_degrades_without_failing_core_receipt():
    payload = _payload()
    payload.pop("alpaca_daily_flow")
    payload["alpaca_daily_flow_status"] = {"status": "ERROR", "error": "timeout"}

    health = _health(payload)

    assert health["level"] == "OK"
    assert health["layers"]["auxiliary_flows"]["level"] == "DEGRADED"
    assert health["receipt_status"] == "OK"
    check = next(check for check in health["checks"] if "SIP 资金流不可用" in check["label"])
    assert check["layer"] == "auxiliary_flows"


def test_external_source_failure_degrades_with_reason():
    payload = _payload()
    payload["external_source_status"] = {
        "dollar": {
            "source_id": "dollar",
            "status": "FETCH_ERROR",
            "error_message": "FRED 503",
        }
    }

    health = _health(payload)

    assert health["level"] == "DEGRADED"
    assert health["layers"]["strategy_data"]["level"] == "DEGRADED"
    assert any(
        "外部数据源刷新失败" in check["label"]
        and "dollar" in check["detail"]
        and "FRED 503" in check["detail"]
        for check in health["checks"]
    )


def test_latest_external_attempt_failure_is_operational_warn_when_canonical_is_certified_and_fresh():
    payload = _payload()
    payload["external_source_status"] = {
        "cboe_vix": {
            "source_id": "cboe_vix",
            "status": "OK",
            "freshness_status": "OK",
            "evidence_status": "MATCH",
            "latest_attempt_status": "VALIDATION_ERROR",
            "latest_attempt_finished_at": "2026-07-14T06:45:00+08:00",
            "latest_attempt_error_message": "Yahoo witness mismatch 2026-07-13",
        }
    }

    health = _health(payload)

    assert health["level"] == "OK"
    assert health["layers"]["strategy_data"]["level"] == "OK"
    assert health["layers"]["operations"]["level"] == "DEGRADED"
    check = next(
        check
        for check in health["checks"]
        if check["label"] == "外部数据源刷新失败（认证缓存仍有效）"
        and "cboe_vix" in check["detail"]
        and "Yahoo witness mismatch" in check["detail"]
    )
    assert check["layer"] == "operations"


def test_latest_external_attempt_failure_still_degrades_when_canonical_is_stale():
    payload = _payload()
    payload["external_source_status"] = {
        "naaim_exposure": {
            "source_id": "naaim_exposure",
            "status": "OK",
            "freshness_status": "STALE",
            "evidence_status": "MATCH",
            "latest_attempt_status": "FETCH_ERROR",
            "latest_attempt_error_message": "official workbook unavailable",
        }
    }

    health = _health(payload)

    assert health["level"] == "DEGRADED"
    assert health["layers"]["strategy_data"]["level"] == "DEGRADED"
    assert any(
        check["label"] == "外部数据源刷新失败"
        and "naaim_exposure" in check["detail"]
        for check in health["checks"]
    )


def test_retired_naaim_is_informational_and_does_not_degrade_strategy_health():
    payload = _payload()
    payload["data_quality_breakdown"] = {
        "sources": [
            {
                "name": "naaim",
                "status": "MISSING",
                "reason": "stale 14d exceeds max_age_days=13",
            }
        ]
    }
    payload["external_source_status"] = {
        "naaim_exposure": {
            "source_id": "naaim_exposure",
            "status": "OK",
            "freshness_status": "STALE",
            "evidence_status": "MATCH",
            "lifecycle_status": "RETIRED_PAYWALL",
            "lifecycle_reason": "public workbook retired behind paid subscription",
            "age_days": 14,
        }
    }

    health = _health(payload)

    assert health["level"] == "OK"
    assert health["layers"]["strategy_data"]["level"] == "OK"
    assert any(
        check["level"] == "INFO"
        and check["label"] == "外部数据源已付费退役"
        and "naaim_exposure" in check["detail"]
        for check in health["checks"]
    )
    assert not any(check["label"] == "软数据源过期 1" for check in health["checks"])


def test_retired_naaim_evidence_drift_remains_strategy_critical():
    payload = _payload()
    payload["external_source_status"] = {
        "naaim_exposure": {
            "source_id": "naaim_exposure",
            "status": "OK",
            "freshness_status": "STALE",
            "evidence_status": "EVIDENCE_DRIFT",
            "evidence_detail": "canonical sha256 mismatch",
            "lifecycle_status": "RETIRED_PAYWALL",
        }
    }

    health = _health(payload)

    assert health["level"] == "CRITICAL"
    assert health["layers"]["strategy_data"]["level"] == "CRITICAL"
    assert any(
        check["label"] == "外部数据证据失配"
        and "naaim_exposure" in check["detail"]
        for check in health["checks"]
    )


def test_retired_naaim_old_probe_failure_is_info_not_permanent_degradation():
    payload = _payload()
    payload["external_source_status"] = {
        "naaim_exposure": {
            "source_id": "naaim_exposure",
            "status": "OK",
            "freshness_status": "STALE",
            "evidence_status": "MATCH",
            "lifecycle_status": "RETIRED_PAYWALL",
            "lifecycle_reason": "public workbook retired behind paid subscription",
            "latest_attempt_status": "FETCH_ERROR",
            "latest_attempt_finished_at": "2026-06-12T06:45:00+08:00",
        }
    }

    health = _health(payload)

    assert health["level"] == "OK"
    assert health["layers"]["operations"]["level"] == "INFO"
    assert any(
        check["label"] == "外部数据源已付费退役（上次探测失败）"
        for check in health["checks"]
    )


def test_retired_naaim_same_day_probe_failure_degrades_operations_only():
    payload = _payload()
    payload["external_source_status"] = {
        "naaim_exposure": {
            "source_id": "naaim_exposure",
            "status": "OK",
            "freshness_status": "STALE",
            "evidence_status": "MATCH",
            "lifecycle_status": "RETIRED_PAYWALL",
            "latest_attempt_status": "FETCH_ERROR",
            "latest_attempt_finished_at": "2026-06-18T06:45:00+08:00",
        }
    }

    health = _health(payload)

    assert health["level"] == "OK"
    assert health["layers"]["strategy_data"]["level"] == "OK"
    assert health["layers"]["operations"]["level"] == "DEGRADED"


def test_system_health_reports_retired_naaim_scored_b6_gap_and_non_scoring_placeholders_separately():
    payload = _payload()
    payload["external_source_status"] = {
        "naaim_exposure": {
            "source_id": "naaim_exposure",
            "status": "OK",
            "lifecycle_status": "RETIRED_PAYWALL",
            "freshness_status": "OK",
            "evidence_status": "MATCH",
        }
    }
    payload["scores"] = {
        "MSTR": {
            "factor_scores": {
                "A": [
                    {
                        "factor_id": "A2_CNN_FEAR_GREED",
                        "max_score": 0,
                        "missing_fields": ["A2 cnn_fear_greed"],
                    },
                    {
                        "factor_id": "A2_NAAIM",
                        "max_score": 2,
                        "missing_fields": [],
                    },
                ],
                "B": [
                    {
                        "factor_id": "B5_SOCIAL_EUPHORIA",
                        "max_score": 0,
                        "missing_fields": ["B5 social"],
                    },
                    {
                        "factor_id": "B6_VALUATION_HEAT",
                        "max_score": 5,
                        "missing_fields": ["B6 valuation"],
                    },
                ],
                "D": [
                    {
                        "factor_id": "D_M4_BALANCE_SHEET_PROXY",
                        "max_score": 0,
                        "missing_fields": ["D-M4"],
                    },
                    {
                        "factor_id": "D_M5_CRYPTO_SENTIMENT",
                        "max_score": 0,
                        "missing_fields": ["D-M5"],
                    },
                ],
            }
        }
    }
    report = {
        "as_of": DAY.isoformat(),
        "health": {"layers": {}},
        "manifest_status": {"status": "OK"},
        "run_receipt": payload["run_receipt"],
    }

    dimensions = build_system_health_audit_dimensions(payload, report)
    lifecycle = next(row for row in dimensions if row["id"] == "factor_scores_present")

    assert lifecycle["status"] == "WARN"
    assert "NAAIM：已退役来源，等待 SLO 缺失路径" in lifecycle["detail"]
    assert "MSTR B6：计分输入缺失 5 分" in lifecycle["detail"]
    assert "非计分占位 4 项" in lifecycle["detail"]
    assert "A2_CNN_FEAR_GREED" not in lifecycle["detail"]


def test_market_admission_blocked_degrades_with_quarantine_count():
    payload = _payload()
    payload["market_admission_status"] = {
        "mode": "enforce_consensus",
        "status": "BLOCKED",
        "rejected_rows": 2,
        "summary": {"PRICE_MISMATCH": 1, "NO_WITNESS": 1},
    }

    health = _health(payload)

    assert health["level"] == "DEGRADED"
    assert any(
        check["label"] == "双源行情候选已隔离"
        and "rejected=2" in check["detail"]
        and "PRICE_MISMATCH" in check["detail"]
        for check in health["checks"]
    )


def test_market_admission_blocked_explains_price_and_volume_evidence():
    payload = _payload()
    payload["market_admission_status"] = {
        "mode": "enforce_consensus",
        "status": "BLOCKED",
        "rejected_rows": 1,
        "summary": {"VOLUME_MISMATCH": 1},
        "price_evidence_summary": {"MATCH": 1},
        "volume_evidence_summary": {"MISMATCH": 1},
    }

    health = _health(payload)

    check = next(
        check
        for check in health["checks"]
        if check["label"] == "双源行情候选已隔离"
    )
    assert "price[MATCH=1]" in check["detail"]
    assert "volume[MISMATCH=1]" in check["detail"]


def test_market_admission_blocked_names_the_first_quarantined_row():
    payload = _payload()
    payload["market_admission_status"] = {
        "mode": "enforce_consensus",
        "status": "BLOCKED",
        "rejected_rows": 1,
        "summary": {"VOLUME_MISMATCH": 1},
        "price_evidence_summary": {"MATCH": 1},
        "volume_evidence_summary": {"MISMATCH": 1},
        "rows": [
            {
                "symbol": "BRK.B",
                "date": "2026-08-05",
                "status": "VOLUME_MISMATCH",
                "admitted": False,
                "price_evidence_status": "MATCH",
                "volume_evidence_status": "MISMATCH",
                "volume_diff_pct": 36.4139,
            }
        ],
        "third_source_shadow": {
            "status": "OK",
            "research_only": True,
            "rows": [
                {
                    "symbol": "BRK.B",
                    "date": "2026-08-05",
                    "third_source_support": "ALPACA_WITNESS",
                }
            ],
        },
    }

    health = _health(payload)

    check = next(
        check
        for check in health["checks"]
        if check["label"] == "双源行情候选已隔离"
    )
    assert "BRK.B 2026-08-05" in check["detail"]
    assert "volume diff=36.4139%" in check["detail"]
    assert "price=MATCH" in check["detail"]
    assert "third=ALPACA_WITNESS" in check["detail"]


def test_market_admission_fetch_error_never_falls_back_silently():
    payload = _payload()
    payload["market_admission_status"] = {
        "mode": "enforce_consensus",
        "status": "FETCH_ERROR",
        "fetch_error": "TimeoutError: Alpaca unavailable",
        "rejected_rows": 3,
    }

    health = _health(payload)

    assert health["level"] == "DEGRADED"
    assert any(
        check["label"] == "双源行情见证不可用"
        and "Alpaca unavailable" in check["detail"]
        for check in health["checks"]
    )


def test_market_admission_run_error_is_visible_as_strategy_degradation():
    payload = _payload()
    payload["market_admission_status"] = {
        "mode": "enforce_consensus",
        "status": "ERROR",
        "run_error": "OSError: disk write failed",
    }

    health = _health(payload)

    assert health["level"] == "DEGRADED"
    assert any(
        check["label"] == "双源行情准入失败"
        and "disk write failed" in check["detail"]
        for check in health["checks"]
    )


def test_required_market_admission_evidence_cannot_be_missing_green() -> None:
    payload = _payload()
    payload["market_admission_status"] = {
        "mode": "enforce_consensus",
        "status": "MISSING",
    }

    health = _health(payload)

    assert health["level"] == "DEGRADED"
    assert any(
        check["label"] == "双源行情准入证据缺失"
        for check in health["checks"]
    )


def test_market_admission_evidence_drift_is_critical() -> None:
    payload = _payload()
    payload["market_admission_status"] = {
        "mode": "enforce_consensus",
        "status": "EVIDENCE_DRIFT",
        "evidence_detail": "QQQ.csv sha256 mismatch",
    }

    health = _health(payload)

    assert health["level"] == "CRITICAL"
    assert any(
        check["label"] == "双源行情证据漂移"
        and "QQQ.csv" in check["detail"]
        for check in health["checks"]
    )


def test_superseded_market_admission_is_degraded_not_critical() -> None:
    payload = _payload()
    payload["market_admission_status"] = {
        "mode": "enforce_consensus",
        "status": "SUPERSEDED_BY_NEWER_DATA",
        "evidence_detail": "new certified rows appended after official run: QQQ.csv",
    }

    health = _health(payload)

    assert health["level"] == "DEGRADED"
    assert any(
        check["label"] == "官方评分已有更新行情待重跑"
        for check in health["checks"]
    )


def test_external_source_evidence_drift_is_critical_even_when_runner_status_is_ok():
    payload = _payload()
    payload["external_source_status"] = {
        "dollar": {
            "source_id": "dollar",
            "status": "OK",
            "freshness_status": "OK",
            "evidence_status": "EVIDENCE_DRIFT",
            "evidence_detail": "canonical sha256 changed after promotion",
        }
    }

    health = _health(payload)

    assert health["level"] == "CRITICAL"
    assert any(
        check["label"] == "外部数据证据失配"
        and "dollar" in check["detail"]
        and "EVIDENCE_DRIFT" in check["detail"]
        for check in health["checks"]
    )


def test_missing_external_source_ledger_degrades_but_not_critical():
    payload = _payload()
    payload["external_source_status"] = {
        "dollar": {
            "source_id": "dollar",
            "status": "MISSING",
        }
    }

    health = _health(payload)

    assert health["level"] == "DEGRADED"
    assert any("外部数据源未自动刷新" in check["label"] for check in health["checks"])


def test_stale_external_source_profile_degrades_even_when_last_run_ok():
    payload = _payload()
    payload["external_source_status"] = {
        "dollar": {
            "source_id": "dollar",
            "status": "OK",
            "freshness_status": "STALE",
            "age_days": 14,
            "next_action": "run refresh_external --source dollar",
        }
    }

    health = _health(payload)

    assert health["level"] == "DEGRADED"
    assert any(
        "外部数据源陈旧" in check["label"]
        and "dollar" in check["detail"]
        and "run refresh_external --source dollar" in check["detail"]
        for check in health["checks"]
    )


def test_stale_active_research_source_is_visible_without_degrading_strategy():
    payload = _payload()
    payload["external_source_status"] = {
        "btc_funding_basis": {
            "source_id": "btc_funding_basis",
            "decision_role": "research",
            "active": True,
            "status": "OK",
            "freshness_status": "STALE",
            "age_days": 8,
        }
    }

    health = _health(payload)

    assert health["level"] == "OK"
    assert health["layers"]["strategy_data"]["level"] == "OK"
    check = next(
        check
        for check in health["checks"]
        if "btc_funding_basis" in check["detail"]
    )
    assert check["level"] == "INFO"
    assert check["layer"] == "auxiliary_flows"


def test_research_only_quality_penalty_is_visible_without_degrading_strategy():
    payload = _payload()
    payload["all_source_data_quality"] = {
        "level": "LOW",
        "overall_score": 61.0,
    }
    payload["data_quality_breakdown"] = {
        "sources": [
            {
                "name": "btc_funding_basis",
                "category": "soft",
                "status": "MISSING",
                "reason": "stale 8d exceeds max_age_days=6",
                "decision_role": "research",
            }
        ]
    }

    health = _health(payload)

    assert health["level"] == "OK"
    assert health["layers"]["strategy_data"]["level"] == "OK"
    check = next(
        check
        for check in health["checks"]
        if check["label"] == "研究数据源未就绪"
    )
    assert check["level"] == "INFO"
    assert check["layer"] == "auxiliary_flows"


def test_previous_receipt_expires_after_next_run_grace_window():
    # com.hermes.daily runs every calendar day at 07:10. The extra two hours
    # distinguish a missed daily job from normal weekend/holiday price staleness.
    payload = _payload()
    stale = NOW - timedelta(hours=26, seconds=1)
    payload["run_receipt"].update({"run_at": stale.isoformat(), "finished_at": stale.isoformat()})

    health = _health(payload)

    assert health["level"] == "CRITICAL"
    assert any("官方 run 已停摆" in check["label"] for check in health["checks"])
