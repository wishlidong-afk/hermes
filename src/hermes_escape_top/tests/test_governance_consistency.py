from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "check_governance_consistency.py"


def _module():
    spec = importlib.util.spec_from_file_location("check_governance_consistency", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_registry_parser_reads_on_and_off_defaults():
    module = _module()
    markdown = """
| Flag | Default | Status | What it gates |
|---|---|---|---|
| `flag_on` | **ON** ✅ | live | unit |
| `flag_off` | OFF | candidate | unit |
"""

    assert module.parse_registry_defaults(markdown) == {"flag_on": True, "flag_off": False}


def test_repository_governance_evidence_matches_config_and_baseline():
    module = _module()

    report = module.check_repository(ROOT)

    assert report["ok"], report["errors"]
    assert report["checks"]["config_invariants"] == "OK"
    assert report["checks"]["flag_registry"] == "OK"
    assert report["checks"]["context_snapshot"] == "OK"
    assert report["checks"]["baseline_metadata"] == "OK"


def test_stale_baseline_requires_explicit_labels_in_both_docs(tmp_path):
    module = _module()
    baseline = {
        "git_commit": "a" * 40,
        "equity_timing": "next_open",
        "evidence_status": "STALE",
        "metrics": {"cagr": 0.1, "max_drawdown": -0.2, "sharpe": 1.0},
    }
    baseline_doc = tmp_path / "BASELINE_CURRENT.md"
    gate_doc = tmp_path / "GATE_BASELINE_CURRENT.md"
    for path in (baseline_doc, gate_doc):
        path.write_text(
            f"{baseline['git_commit']} next_open 10.00% -20.00% 1.000\n",
            encoding="utf-8",
        )

    errors = module._baseline_errors(baseline, baseline_doc, gate_doc)

    assert any("STALE" in error for error in errors)

    for path in (baseline_doc, gate_doc):
        path.write_text(
            f"Status: **STALE**\n{baseline['git_commit']} next_open 10.00% -20.00% 1.000\n",
            encoding="utf-8",
        )
    assert module._baseline_errors(baseline, baseline_doc, gate_doc) == []
