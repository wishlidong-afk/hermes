"""Refuse invalid entry points without invoking a scoring worker."""

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
DRIVER = ROOT / "verify_v2_rollback.py"
spec = importlib.util.spec_from_file_location("rollback_tool", DRIVER)
assert spec and spec.loader
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
results: list[dict[str, object]] = []

for label, arguments, code, detail in (
    ("undeclared_case", ["worker", "unknown", "old_r1"], 2, "invalid choice"),
    ("wrong_stage_for_case", ["worker", "pending", "capture_active"], 2, "declared case and stage"),
    ("parent_with_worker_arguments", ["run", "pending"], 2, "parent mode takes no worker arguments"),
    ("unsandboxed_worker", ["worker", "pending", "old_blocked"], 1, "active OS network isolation"),
):
    result = subprocess.run([sys.executable, "-B", str(DRIVER), *arguments], capture_output=True, text=True, timeout=10)
    assert result.returncode == code and detail in result.stderr, label
    results.append({"case": label, "refused": True, "exit_code": result.returncode})
base = tool.load_base("pending")
tool.gate(base)
with tempfile.TemporaryDirectory(dir=ROOT) as directory:
    root = Path(directory)
    (root / "tool-binding.json").write_text(json.dumps({"driver_sha256": "0" * 64}))
    with patch.object(tool, "ROOT", root):
        try:
            tool.gate(base)
        except AssertionError:
            results.append({"case": "wrong_driver_binding", "refused": True})
        else:
            raise AssertionError("wrong driver binding accepted")
    link = root / "linked-report.json"
    outside = root / "outside.json"
    outside.write_text("untouched")
    link.symlink_to(outside)
    with patch.object(base, "ROOT", root):
        try:
            tool.write(base, link, {"bad": True})
        except FileExistsError:
            results.append({"case": "linked_report", "refused": True})
        else:
            raise AssertionError("linked report was overwritten")
    assert outside.read_text() == "untouched"
output = ROOT / "guards.json"
late_summary = ROOT / "cases/committed_clean/summary.json"
with tempfile.TemporaryDirectory(dir=ROOT) as directory:
    outside = Path(directory) / "outside.json"
    outside.write_text("untouched")
    for linked in (False, True):
        if linked:
            late_summary.symlink_to(outside)
        else:
            late_summary.write_text("conflict")
        with patch.object(tool, "launch") as launch:
            try:
                tool.run()
            except AssertionError:
                assert launch.call_count == 0
                results.append(
                    {
                        "case": "late_summary_link" if linked else "late_summary_existing",
                        "refused": True,
                        "scoring_launches": 0,
                    }
                )
            else:
                raise AssertionError("late output conflict was accepted")
            finally:
                late_summary.unlink()
        assert outside.read_text() == "untouched"
with tempfile.TemporaryDirectory(dir=ROOT) as directory:
    root = Path(directory)
    (root / "cases").symlink_to(ROOT / "cases", target_is_directory=True)
    with patch.object(tool, "ROOT", root):
        try:
            tool.load_base("pending")
        except AssertionError:
            results.append({"case": "linked_cases_parent", "refused": True})
        else:
            raise AssertionError("linked cases parent accepted")
with output.open("x") as stream:
    stream.write(
        json.dumps(
            {
                "status": "PASS",
                "checks": results,
                "scoring_invoked": False,
                "driver_sha256": hashlib.sha256(DRIVER.read_bytes()).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )
print(output.read_text())
