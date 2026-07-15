from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hermes_escape_top.core.backtest.gate_policy import (
    LEGACY_RATE_LABEL,
    assess_legacy_gate,
)
from hermes_escape_top.scripts import generate_baseline_doc


REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_equity(path: Path, values: list[float]) -> None:
    dates = [f"2026-01-{day:02d}" for day in range(2, 2 + len(values))]
    path.write_text(json.dumps(dict(zip(dates, values))), encoding="utf-8")


def test_legacy_gate_can_report_checks_but_never_authorize() -> None:
    result = assess_legacy_gate(
        beats_baseline=True,
        bottom_half_rate=0.0,
        drawdown_ok=True,
        evidence_status="FRESH",
    )

    assert result["legacy_checks"] == "MEETS LEGACY CHECKS"
    assert result["authorization"] == "FROZEN"
    assert "formal IS->OOS PBO" in result["reason"]


def test_legacy_gate_explains_stale_evidence_and_failed_diagnostics() -> None:
    result = assess_legacy_gate(
        beats_baseline=False,
        bottom_half_rate=0.75,
        drawdown_ok=False,
        evidence_status="STALE",
    )

    assert result["authorization"] == "FROZEN"
    assert result["legacy_checks"].startswith("FAILS LEGACY CHECKS")
    assert "OOS<=baseline" in result["legacy_checks"]
    assert "bottom-half>=0.5" in result["legacy_checks"]
    assert "MaxDD" in result["legacy_checks"]
    assert "stale evidence" in result["reason"]


def test_legacy_gate_preserves_unverified_evidence_label() -> None:
    result = assess_legacy_gate(
        beats_baseline=True,
        bottom_half_rate=0.0,
        drawdown_ok=True,
        evidence_status="UNVERIFIED",
    )

    assert "unverified evidence" in result["reason"]


def test_legacy_metric_name_is_not_pbo() -> None:
    assert LEGACY_RATE_LABEL == "OOS bottom-half rate (diagnostic)"
    assert "PBO" not in LEGACY_RATE_LABEL


def test_baseline_generator_marks_legacy_evidence_stale() -> None:
    doc = generate_baseline_doc.build_doc()

    assert generate_baseline_doc.DEFAULT_OUT.name == "BASELINE_2026_06_11.md"
    assert generate_baseline_doc.DEFAULT_OUT.parent.name == "history"
    assert "STALE RESEARCH EVIDENCE" in doc
    assert "OOS bottom-half rate" in doc
    assert "Benchmark PBO / DSR" not in doc
    assert "PBO≥.5" not in doc
    assert "Routing-gate note (contains legacy PBO wording)" in doc


def test_baseline_generator_updates_current_context_section(tmp_path) -> None:
    context = tmp_path / "context.md"
    context.write_text(
        "# Context\n\n## 11. 当前性能基线\n\nold evidence\n\n---\n\n## 12. Tests\n",
        encoding="utf-8",
    )

    generate_baseline_doc.update_context(context, "unused")

    updated = context.read_text(encoding="utf-8")
    assert "## 11. 当前性能基线" in updated
    assert "STALE RESEARCH EVIDENCE" in updated
    assert "old evidence" not in updated
    assert "## 12. Tests" in updated


def test_flag_gate_report_cannot_emit_pass(tmp_path, monkeypatch) -> None:
    mod = _load_script("flag_gate")
    monkeypatch.setattr(mod, "DIR", tmp_path)
    monkeypatch.setattr(
        mod,
        "walk_forward_splits",
        lambda dates: [SimpleNamespace(test_idx=np.asarray([0, 1, 2, 3]))],
    )
    monkeypatch.setattr(
        mod,
        "artifact_freshness",
        lambda variant, **window: {"status": "STALE", "mismatches": ["cache_key"]},
    )
    _write_equity(tmp_path / "baseline_equity.json", [100.0, 101.0, 102.0, 103.0])
    _write_equity(tmp_path / "candidate_equity.json", [100.0, 102.0, 104.0, 106.0])

    mod.main(["candidate"])

    report = (tmp_path / "GATE_REPORT_candidate.md").read_text(encoding="utf-8")
    assert "EVIDENCE STATUS: STALE" in report
    assert LEGACY_RATE_LABEL in report
    assert "AUTHORIZATION: FROZEN" in report
    assert "✅ PASS" not in report


def test_routing_gate_report_cannot_emit_pass(tmp_path, monkeypatch) -> None:
    mod = _load_script("routing_gate")
    monkeypatch.setattr(mod, "DIR", tmp_path)
    monkeypatch.setattr(
        mod,
        "walk_forward_splits",
        lambda dates: [SimpleNamespace(test_idx=np.asarray([0, 1, 2, 3]))],
    )
    _write_equity(tmp_path / "baseline_equity.json", [100.0, 101.0, 102.0, 103.0])
    _write_equity(tmp_path / "combo_equity.json", [100.0, 102.0, 104.0, 106.0])

    mod.main(["combo"])

    report = (tmp_path / "ROUTING_GATE_REPORT.md").read_text(encoding="utf-8")
    assert "EVIDENCE STATUS: UNVERIFIED" in report
    assert LEGACY_RATE_LABEL in report
    assert "AUTHORIZATION: FROZEN" in report
    assert "✅ PASS" not in report
