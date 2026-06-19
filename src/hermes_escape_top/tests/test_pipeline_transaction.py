from __future__ import annotations

import ast
from pathlib import Path
from unittest import mock

import pytest

from hermes_escape_top import pipeline
from hermes_escape_top.config import load_config, resolve_path
from hermes_escape_top.core.safe_io import assert_pipeline_lease, pipeline_lock


def test_public_score_pipeline_mints_active_lease():
    observed = {}

    def fake_locked(as_of, **kwargs):
        lease = kwargs.pop("_lease")
        assert_pipeline_lease(lease)
        observed["as_of"] = as_of
        observed["kwargs"] = kwargs
        return {"as_of": as_of, "ok": True}

    with mock.patch.object(pipeline, "_score_pipeline_locked", side_effect=fake_locked):
        payload = pipeline.score_pipeline("2026-05-29", include_ibkr=False)

    assert payload == {"as_of": "2026-05-29", "ok": True}
    assert observed["kwargs"]["include_ibkr"] is False


def test_locked_score_rejects_missing_lease_before_computation():
    with pytest.raises(RuntimeError, match="invalid pipeline lease"):
        pipeline._score_pipeline_locked("2026-05-29", _lease=None)


def test_locked_score_rejects_lease_for_wrong_data_dir(tmp_path):
    expected = resolve_path(load_config(), "archive_dir") / ".pipeline.lock"
    wrong = tmp_path / ".pipeline.lock"
    assert wrong.resolve() != expected.resolve()

    with pipeline_lock(blocking=False, path=wrong) as lease:
        with pytest.raises(RuntimeError, match="path mismatch"):
            pipeline._score_pipeline_locked("2026-05-29", _lease=lease)


def test_private_locked_score_has_only_approved_production_callers():
    package = Path(pipeline.__file__).resolve().parent
    approved = {
        package / "pipeline.py",
        package / "ibkr" / "live_check.py",
        package / "scripts" / "run_daily_package.py",
        package / "web" / "refresh.py",
        package / "web" / "server.py",
    }
    callers = set()
    for path in package.rglob("*.py"):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node.func) == "_score_pipeline_locked":
                callers.add(path)
    assert callers == approved


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None
