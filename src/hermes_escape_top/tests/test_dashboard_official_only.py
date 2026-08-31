"""The default dashboard headline (as_of=latest) must be the official scheduled
run. An intraday manual_rerun / shadow preview must never silently masquerade as
today's advice — the SOXL REDUCE->EXIT->REDUCE scare was a preview flip."""
from __future__ import annotations

from hermes_escape_top.web.render import (
    _render_decision_revision_banner,
    _render_preview_banner,
)
from hermes_escape_top.web.server import _latest_score_payload


def _rec(as_of: str, run_type: str, status: str = "REDUCE") -> dict:
    return {"as_of": as_of, "run_type": run_type, "scores": {"SOXL": {"status": status}}}


def test_latest_prefers_scheduled_over_same_day_manual_rerun():
    # newest-first: a manual_rerun EXIT preview sits on top of the official REDUCE
    # for the same day. Default 'latest' must still surface the scheduled one.
    records = [
        _rec("2026-06-16", "manual_rerun", "EXIT"),
        _rec("2026-06-16", "scheduled", "REDUCE"),
        _rec("2026-06-15", "scheduled", "REDUCE"),
    ]
    out = _latest_score_payload("latest", records)
    assert out["run_type"] == "scheduled"
    assert out["scores"]["SOXL"]["status"] == "REDUCE"


def test_latest_ignores_manual_rerun_with_higher_as_of():
    # a manual_rerun previewing a LATER date must not become the headline.
    records = [
        _rec("2026-06-17", "manual_rerun", "EXIT"),
        _rec("2026-06-16", "scheduled", "REDUCE"),
    ]
    out = _latest_score_payload("latest", records)
    assert out["as_of"] == "2026-06-16"
    assert out["run_type"] == "scheduled"


def test_latest_falls_back_to_flagged_preview_when_no_scheduled():
    # only previews exist (rare): surface the newest, but flagged non_official so
    # render labels it — never silently pass a preview off as official.
    records = [
        _rec("2026-06-16", "manual_rerun", "EXIT"),
        _rec("2026-06-15", "manual_rerun", "REDUCE"),
    ]
    out = _latest_score_payload("latest", records)
    assert out is not None
    assert out["as_of"] == "2026-06-16"
    assert out["cache_status"].get("non_official") is True


def test_explicit_as_of_request_unchanged():
    records = [_rec("2026-06-16", "scheduled"), _rec("2026-06-15", "scheduled")]
    out = _latest_score_payload("2026-06-15", records)
    assert out["as_of"] == "2026-06-15"


def test_explicit_as_of_prefers_scheduled_over_preview():
    # 06-17 has both an official scheduled and a newer manual_rerun preview.
    # Navigating to / being redirected to 06-17 must show the OFFICIAL, not the
    # redundant preview (the 2026-06-18 confusion: refresh redirected to ?as_of=
    # 06-17 and showed the preview though an identical official existed).
    records = [
        _rec("2026-06-17", "manual_rerun", "EXIT"),
        _rec("2026-06-17", "scheduled", "REDUCE"),
    ]
    out = _latest_score_payload("2026-06-17", records)
    assert out["run_type"] == "scheduled"
    assert out["scores"]["SOXL"]["status"] == "REDUCE"
    assert out["cache_status"].get("non_official") in (None, False)


def test_explicit_as_of_shows_flagged_preview_when_no_scheduled():
    # a genuine pre-official preview (no scheduled yet for that day) still shows,
    # flagged non_official so the banner appears.
    records = [_rec("2026-06-17", "manual_rerun", "EXIT")]
    out = _latest_score_payload("2026-06-17", records)
    assert out["run_type"] == "manual_rerun"
    assert out["cache_status"].get("non_official") is True


def test_view_preview_returns_the_manual_rerun_but_default_stays_official():
    # #5: ?view=preview (the 更新策略数据 redirect) makes the intraday preview
    # reachable + labeled non_official; default (no flag) still shows the official.
    records = [
        _rec("2026-06-17", "manual_rerun", "EXIT"),
        _rec("2026-06-17", "scheduled", "REDUCE"),
    ]
    prev = _latest_score_payload("2026-06-17", records, prefer_preview=True)
    assert prev["run_type"] == "manual_rerun" and prev["cache_status"].get("non_official") is True
    assert _latest_score_payload("2026-06-17", records)["run_type"] == "scheduled"


def test_preview_banner_only_for_non_scheduled():
    assert _render_preview_banner({"run_type": "scheduled"}) == ""
    banner = _render_preview_banner({"run_type": "manual_rerun", "as_of": "2026-06-16"})
    assert "非官方" in banner and "盘中重算预览" in banner and "2026-06-16" in banner


def test_same_day_official_lookup_selects_highest_revision_even_when_records_are_unordered():
    revision_one = _rec("2026-08-28", "scheduled", "REDUCE")
    revision_one["decision_evidence"] = {
        "decision_id": "decision-r1",
        "decision_revision": 1,
        "bar_finality": "PROVISIONAL",
    }
    revision_two = _rec("2026-08-28", "scheduled", "EXIT")
    revision_two["decision_evidence"] = {
        "decision_id": "decision-r2",
        "decision_revision": 2,
        "bar_finality": "FINAL",
        "supersedes_decision_id": "decision-r1",
    }
    records = [revision_one, revision_two]

    latest = _latest_score_payload("latest", records)
    exact = _latest_score_payload("2026-08-28", records)

    assert latest["decision_evidence"]["decision_id"] == "decision-r2"
    assert exact["decision_evidence"]["decision_id"] == "decision-r2"
    assert latest["scores"]["SOXL"]["status"] == "EXIT"


def test_revision_banner_discloses_provisional_and_superseding_official_records():
    provisional = _render_decision_revision_banner({
        "run_type": "scheduled",
        "as_of": "2026-08-28",
        "decision_evidence": {
            "decision_id": "decision-r1",
            "decision_revision": 1,
            "bar_finality": "PROVISIONAL",
            "revision_reason": "INITIAL_CERTIFICATION",
        },
    })
    revised = _render_decision_revision_banner({
        "run_type": "scheduled",
        "as_of": "2026-08-28",
        "decision_evidence": {
            "decision_id": "decision-r2",
            "decision_revision": 2,
            "bar_finality": "FINAL",
            "revision_reason": "CANONICAL_EVIDENCE_CHANGED_AND_FINALIZED",
            "supersedes_decision_id": "decision-r1",
        },
    })

    assert "尚未最终化" in provisional and "r1" in provisional
    assert "官方结论已修订" in revised and "r2" in revised
    assert "decision-r1" in revised
    assert _render_decision_revision_banner({"run_type": "scheduled"}) == ""
