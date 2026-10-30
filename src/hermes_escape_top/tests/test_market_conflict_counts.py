"""Admission retry counts are diagnostic, never permission to admit a bar."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone

import pytest

from hermes_escape_top.web.health import compute_health


NOW = datetime(2026, 10, 24, 1, 13, tzinfo=timezone.utc)


def _payload():
    row = {
        "symbol": "FNGU",
        "date": "2026-10-23",
        "status": "VOLUME_MISMATCH",
        "admitted": False,
        "candidate_sha256": "a" * 64,
        "witness_sha256": "b" * 64,
        "decision_roles": ["scored_symbol"],
        "decision_impact": "STRATEGY_BLOCKING",
        "price_evidence_status": "MATCH",
        "volume_evidence_status": "MISMATCH",
        "volume_diff_pct": 25.1322,
    }
    return {
        "as_of": "2026-10-23",
        "cache_status": {"hit": True},
        "data_quality": {"level": "HIGH"},
        "data_quality_breakdown": {"sources": []},
        "run_receipt": {
            "status": "OK", "ok": True, "run_type": "scheduled",
            "run_at": NOW.isoformat(), "finished_at": NOW.isoformat(),
        },
        "market_admission_status": {
            "mode": "enforce_consensus", "status": "BLOCKED",
            "rejected_rows": 3, "strategy_blocking_rejected_rows": 3,
            "component_flow_rejected_rows": 0,
            "rows": [deepcopy(row) for _ in range(3)],
        },
    }


def _health(payload):
    return compute_health(payload, {"status": "OK"}, today=date(2026, 10, 24), now=NOW)


def _quarantine(health):
    return next(row for row in health["checks"] if row["label"].endswith("行情候选已隔离"))


def test_identical_rejections_are_one_conflict_and_three_attempts():
    payload = _payload()
    before = deepcopy(payload)

    health = _health(payload)
    check = _quarantine(health)

    assert "unique_conflicts=1" in check["detail"]
    assert "attempts=3" in check["detail"]
    assert "rejected=3" in check["detail"]
    assert "FNGU 2026-10-23 VOLUME_MISMATCH" in check["detail"]
    assert check["layer"] == "strategy_data"
    assert health["layers"]["strategy_data"]["level"] == "DEGRADED"
    assert payload == before


@pytest.mark.parametrize("field,value", [
    ("candidate_sha256", "c" * 64),
    ("witness_sha256", "d" * 64),
    ("symbol", "SOXL"),
    ("date", "2026-10-22"),
    ("status", "PRICE_MISMATCH"),
])
def test_materially_different_comparisons_are_not_collapsed(field, value):
    payload = _payload()
    payload["market_admission_status"]["rows"][1][field] = value

    health = _health(payload)

    assert "unique_conflicts=2" in _quarantine(health)["detail"]
    assert "attempts=3" in _quarantine(health)["detail"]
    assert health["layers"]["strategy_data"]["level"] == "DEGRADED"


@pytest.mark.parametrize("field,value", [
    ("candidate_sha256", None),
    ("witness_sha256", "unknown"),
    ("candidate_sha256", "g" * 64),
    ("witness_sha256", []),
    ("symbol", None),
    ("date", ""),
    ("status", 42),
])
def test_incomplete_evidence_does_not_claim_one_verified_conflict(field, value):
    payload = _payload()
    payload["market_admission_status"]["rows"][0][field] = value

    health = _health(payload)

    assert "unique_conflicts=UNKNOWN" in _quarantine(health)["detail"]
    assert "attempts=3" in _quarantine(health)["detail"]
    assert health["layers"]["strategy_data"]["level"] == "DEGRADED"


@pytest.mark.parametrize("reported", [None, 2, 4, "3", True])
def test_nonreconciled_counts_remain_unknown_and_blocking(reported):
    payload = _payload()
    payload["market_admission_status"]["rejected_rows"] = reported

    health = _health(payload)

    assert "unique_conflicts=UNKNOWN attempts=UNKNOWN" in _quarantine(health)["detail"]
    assert health["layers"]["strategy_data"]["level"] == "DEGRADED"


@pytest.mark.parametrize("rows", [None, {}, [None]])
def test_malformed_row_collection_does_not_manufacture_counts(rows):
    payload = _payload()
    payload["market_admission_status"]["rows"] = rows

    health = _health(payload)

    assert "unique_conflicts=UNKNOWN attempts=UNKNOWN" in _quarantine(health)["detail"]
    assert health["layers"]["strategy_data"]["level"] == "DEGRADED"


def test_admitted_and_deferred_rows_do_not_inflate_rejection_attempts():
    payload = _payload()
    rows = payload["market_admission_status"]["rows"]
    rows.extend([
        dict(rows[0], admitted=True, status="MATCH"),
        dict(rows[0], symbol="BTC-USD", blocking=False, status="DEFERRED_UNFINALIZED"),
    ])

    check = _quarantine(_health(payload))

    assert "unique_conflicts=1 attempts=3" in check["detail"]


def test_component_only_classification_is_not_changed_by_count_presentation():
    payload = _payload()
    admission = payload["market_admission_status"]
    admission["strategy_blocking_rejected_rows"] = 0
    admission["component_flow_rejected_rows"] = 3
    for row in admission["rows"]:
        row["decision_roles"] = ["component_flow"]
        row["decision_impact"] = "COMPONENT_FLOW_ONLY"

    health = _health(payload)

    assert "unique_conflicts=1 attempts=3" in _quarantine(health)["detail"]
    assert health["layers"]["strategy_data"]["level"] == "OK"
    assert health["layers"]["auxiliary_flows"]["level"] == "DEGRADED"
