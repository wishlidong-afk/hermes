from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_legacy_core_pipeline_is_only_a_research_compatibility_shim():
    shim = ROOT / "src/hermes_escape_top/core/pipeline.py"
    tree = ast.parse(shim.read_text(encoding="utf-8"), filename=str(shim))

    assert "RETIRED_COMPATIBILITY_SHIM = True" in shim.read_text(encoding="utf-8")
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "score_pipeline"
        for node in ast.walk(tree)
    )


def test_phase_two_research_scripts_use_explicit_research_pipeline():
    for name in ("phase2_shadow_compare.py", "phase2_full_backtest_sensitivity.py"):
        text = (ROOT / "src/hermes_escape_top/scripts" / name).read_text(encoding="utf-8")
        assert "core.research.integration_pipeline import score_pipeline" in text
        assert "core.pipeline import score_pipeline" not in text


def test_production_modules_do_not_import_retired_core_pipeline():
    offenders = []
    package = ROOT / "src/hermes_escape_top"
    for path in package.rglob("*.py"):
        relative = path.relative_to(package)
        if relative.parts[0] == "tests" or path.name.startswith("phase2_"):
            continue
        text = path.read_text(encoding="utf-8")
        if "hermes_escape_top.core.pipeline" in text:
            offenders.append(str(relative))

    assert offenders == []
