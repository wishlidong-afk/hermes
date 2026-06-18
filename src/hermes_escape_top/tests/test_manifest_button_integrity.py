"""The 'refresh manifest' button must verify history integrity BEFORE re-freezing.
Otherwise clicking it on corrupt / hand-edited CSVs re-certifies the damage as OK,
hiding a DRIFT that is real (the daily run already does verify-then-freeze; this
closes the same hole on the button path)."""
from __future__ import annotations

from hermes_escape_top.web import refresh as r


def test_force_refresh_refuses_when_bars_corrupt(monkeypatch):
    froze = {"called": False}
    monkeypatch.setattr(r, "_history_integrity_scan", lambda cfg: ["SOXL 2026-06-17 corrupt"])
    monkeypatch.setattr(r, "manifest_status", lambda cfg=None: {"status": "DRIFT"})
    monkeypatch.setattr(r, "_refresh_manifest",
                        lambda *a, **k: froze.__setitem__("called", True) or {"status": "OK"})
    out = r.force_refresh_manifest({"_test": 1})
    assert froze["called"] is False          # never re-froze corrupt data
    assert out["ok"] is False
    assert out["refrozen"] is False
    assert out["status"] != "OK"             # stays DRIFT, not certified OK
    assert out["offender_count"] == 1


def test_force_refresh_freezes_when_clean(monkeypatch):
    monkeypatch.setattr(r, "_history_integrity_scan", lambda cfg: [])
    monkeypatch.setattr(r, "_refresh_manifest", lambda *a, **k: {"status": "OK", "refrozen": True})
    monkeypatch.setattr(r, "manifest_status", lambda cfg=None: {"status": "OK"})
    out = r.force_refresh_manifest({"_test": 1})
    assert out["ok"] is True
