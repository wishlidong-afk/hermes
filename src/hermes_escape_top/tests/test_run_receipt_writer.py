"""The run receipt is the trust attestation, so it must be written LAST and must
go RED when a required step failed — never certify green just because the
data-state self-checks pass (the 2026-06-18 review: receipt was stamped before
commit_state, so a failed state commit could still show '自检全绿')."""
from __future__ import annotations

import json

from hermes_escape_top.scripts import run_daily_package as rdp


def _patch(monkeypatch, tmp_path):
    monkeypatch.setattr(rdp, "load_config", lambda: {"_t": 1})
    monkeypatch.setattr(rdp, "_last_bar_dates", lambda: {})
    monkeypatch.setattr("hermes_escape_top.config.resolve_path", lambda c, k: tmp_path)
    monkeypatch.setattr("hermes_escape_top.web.refresh.manifest_status", lambda c=None: {"status": "OK"})


def test_receipt_red_when_a_required_step_failed(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    rdp._write_run_receipt("2026-06-17", "scheduled", steps_ok=False, step_error="state commit failed: boom")
    r = json.loads((tmp_path / "run_receipt.json").read_text())
    assert r["ok"] is False
    assert any(c["name"] == "run_steps" and not c["ok"] for c in r["checks"])
    assert "boom" in next(c["detail"] for c in r["checks"] if c["name"] == "run_steps")


def test_receipt_green_when_steps_ok_and_checks_pass(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    rdp._write_run_receipt("2026-06-17", "scheduled", steps_ok=True)
    r = json.loads((tmp_path / "run_receipt.json").read_text())
    assert r["ok"] is True
    assert not any(c["name"] == "run_steps" for c in r["checks"])  # no failure check added
