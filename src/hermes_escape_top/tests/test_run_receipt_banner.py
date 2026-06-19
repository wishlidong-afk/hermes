"""Run-receipt banner: a positive 'official run ran today + self-checked green'
signal — the one thing health.py can't infer from data state. Catches a job that
silently didn't run (stale run_at) or ran stale code that skipped a step (failed
self-check) even when the displayed data still looks fresh."""
from __future__ import annotations

from datetime import datetime, timedelta

from hermes_escape_top.web.render import _render_run_receipt_banner, _run_receipt_when


def _iso(days_ago: int = 0, hours_ago: int = 0) -> str:
    return (datetime.now().astimezone() - timedelta(days=days_ago, hours=hours_ago)).isoformat(timespec="seconds")


def test_green_when_ran_today_and_ok():
    b = _render_run_receipt_banner({"run_receipt": {
        "run_at": _iso(0), "as_of": "2026-06-16", "ok": True,
        "checks": [{"name": "manifest", "ok": True, "detail": "OK"}]}})
    assert "var(--green)" in b and "官方 run" in b and "自检全绿" in b and "今天" in b


def test_red_when_a_check_failed():
    b = _render_run_receipt_banner({"run_receipt": {
        "run_at": _iso(0), "as_of": "2026-06-16", "ok": False,
        "checks": [{"name": "manifest", "ok": False, "detail": "DRIFT"}]}})
    assert "var(--red)" in b and "回执异常" in b and "DRIFT" in b


def test_red_when_run_stale_even_if_checks_passed():
    # ran 2 days ago (>30h): a daily cycle was missed even though its checks
    # passed — the 'job silently stopped but data still looks fresh' case.
    b = _render_run_receipt_banner({"run_receipt": {
        "run_at": _iso(2), "as_of": "2026-06-14", "ok": True, "checks": []}})
    assert "var(--red)" in b and "已停摆" in b


def test_green_when_recent_but_before_todays_run():
    # ~24h old (yesterday's run; today's 07:10 hasn't fired yet) — must stay GREEN,
    # not flip red just because run_at isn't literally today (the morning false-red).
    b = _render_run_receipt_banner({"run_receipt": {
        "run_at": _iso(hours_ago=24), "as_of": "2026-06-16", "ok": True,
        "checks": [{"name": "manifest", "ok": True, "detail": "OK"}]}})
    assert "var(--green)" in b and "官方 run" in b


def test_amber_when_no_receipt():
    b = _render_run_receipt_banner({})
    assert "无运行回执" in b and "var(--amber)" in b


def test_running_receipt_is_amber_not_false_green():
    b = _render_run_receipt_banner({"run_receipt": {
        "status": "RUNNING", "run_at": _iso(0), "started_at": _iso(0),
        "as_of": "2026-06-18", "ok": False, "checks": []}})
    assert "var(--amber)" in b and "正在执行" in b
    assert "自检全绿" not in b


def test_failed_receipt_shows_failed_step_and_error():
    b = _render_run_receipt_banner({"run_receipt": {
        "status": "FAILED", "run_at": _iso(0), "as_of": "2026-06-18",
        "ok": False, "failed_step": "artifact_write", "error": "disk full",
        "checks": []}})
    assert "var(--red)" in b and "artifact_write" in b and "disk full" in b


def test_when_formatter_buckets():
    assert _run_receipt_when(_iso(0)).startswith("今天")
    assert _run_receipt_when(_iso(1)).startswith("昨天")
    assert "天前" in _run_receipt_when(_iso(3))
    assert _run_receipt_when("garbage") == "garbage"
