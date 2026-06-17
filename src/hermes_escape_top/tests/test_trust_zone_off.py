"""Trust zone: a feature-disabled candidate factor (hy_oas / nfci / yield_curve)
is not scored, so its staleness is moot — it must show OFF (neutral), never a red
SLO breach. That false 'STALE' on disabled sources is the C "假陈旧" alarm that
pulled them onto the worry list."""
from __future__ import annotations

from hermes_escape_top.web.render import _normalize_trust_row


def test_disabled_source_shows_off_not_red_slo():
    row = {"name": "hy_oas", "reason": "feature disabled: data_hy_oas",
           "status": "MISSING", "latest_data_date": "2026-06-04"}
    out = _normalize_trust_row("hy_oas", row, {"as_of": "2026-06-16"})
    assert out["truth_kind"] == "未启用"
    assert out["slo_kind"] == "watch"          # neutral, NOT "danger"
    assert "OFF" in out["slo_text"]


def test_enabled_source_not_mislabeled_off():
    # an enabled source must never get the OFF override, even if stale.
    row = {"name": "real_rate", "latest_data_date": "2026-05-01",
           "latency_days": 46, "max_age_days": 3}
    out = _normalize_trust_row("real_rate", row, {"as_of": "2026-06-16"})
    assert out["truth_kind"] != "未启用"
    assert "OFF" not in out["slo_text"]
    assert out["slo_kind"] == "danger"         # 46d past a 3d SLO still breaches
