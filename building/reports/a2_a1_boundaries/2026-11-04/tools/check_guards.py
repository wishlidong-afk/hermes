"""Exercise local tool refusals without calling the scoring pipeline."""

import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "boundaries", ROOT / "verify_boundaries.py"
)
assert spec and spec.loader
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
results: list[dict[str, object]] = []


def refused(label, call):
    try:
        call()
    except (
        AssertionError,
        RuntimeError,
        FileNotFoundError,
        FileExistsError,
        ValueError,
    ):
        results.append({"case": label, "refused": True})
    else:
        raise AssertionError(label + " was unexpectedly accepted")


tool.verify_gate()
refused("direct_worker_without_launch", lambda: tool.worker("old_r1"))
binding = ROOT / "source-binding-execution.json"
with tempfile.TemporaryDirectory(dir=ROOT) as directory:
    root = Path(directory)
    with patch.object(tool, "ROOT", root):
        refused("missing_prepared_binding", tool.verify_gate)
        record = json.loads(binding.read_text())
        record["helper_sha256"] = "0" * 64
        (root / binding.name).write_text(json.dumps(record))
        refused("wrong_helper_binding", tool.verify_gate)
        record = json.loads(binding.read_text())
        record["prepared_artifacts"] = {}
        (root / binding.name).write_text(json.dumps(record))
        refused("empty_replacement_inventory", tool.verify_gate)
    outside = root / "outside.txt"
    outside.write_text("untouched")
    link = ROOT / "linked-output.txt"
    link.symlink_to(outside)
    try:
        refused("linked_output", lambda: tool.output_bytes(link, b"bad"))
        assert outside.read_text() == "untouched"
    finally:
        link.unlink()
    existing = ROOT / "existing-output.txt"
    existing.write_text("untouched")
    try:
        refused("existing_output", lambda: tool.output_bytes(existing, b"bad"))
        assert existing.read_text() == "untouched"
    finally:
        existing.unlink()
    extra = tool.PACKAGES["second"] / "unexpected_import.py"
    extra.write_text("VALUE = 1\n")
    try:
        refused("extra_importable_python", tool.verify_gate)
    finally:
        extra.unlink()
    linked_private = root / "private-link"
    linked_private.symlink_to(tool.PRIVATE, target_is_directory=True)
    with patch.object(tool, "PRIVATE", linked_private):
        refused("private_parent_symlink_before_any_unlink", tool.verify_gate)
for label, path in (
    ("second_release_config_drift", tool.PACKAGES["second"] / "config/config.json"),
    ("second_release_version_drift", tool.PACKAGES["second"] / "VERSION"),
    ("old_source_drift", tool.PACKAGES["old"] / "core/data/decision_revision.py"),
):
    original = path.read_bytes()
    try:
        path.write_bytes(original + b"\n")
        refused(label, tool.verify_gate)
    finally:
        path.write_bytes(original)
    assert path.read_bytes() == original
tool.verify_gate()
output = ROOT / "guards-execution.json"
assert not output.exists()
output.write_text(
    json.dumps(
        {
            "status": "PASS",
            "checks": results,
            "scoring_invoked": False,
            "tool_sha256": hashlib.sha256(
                (ROOT / "verify_boundaries.py").read_bytes()
            ).hexdigest(),
        },
        indent=2,
    )
    + "\n"
)
print(output.read_text())
