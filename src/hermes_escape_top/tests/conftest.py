"""Session-wide data isolation for the test suite (roadmap T8c).

score_pipeline / bootstrap_history write into the package data dirs; without
isolation every test run dirties git-tracked runtime CSVs and sqlite files
(the old "never git add -A" footgun). This fixture re-roots all relative
config paths via HERMES_DATA_DIR (see config.resolve_path) to a throwaway
copy seeded only from Git-tracked package data plus explicit test fixtures.

audit_log.jsonl (hundreds of MB) is excluded from the seed: tests that need
audit history write their own entries into the empty copy.

Ignored runtime data must never affect test outcomes: CI does not have those
files, and copying them locally makes a dirty machine pass tests that fail in
a clean checkout.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_DATA = Path(__file__).resolve().parents[1] / "data"
TEST_DATA = Path(__file__).resolve().parent / "fixtures" / "data"
ARCHIVE_EXCLUDE = {"audit_log.jsonl"}


def _tracked_package_files() -> list[Path]:
    relative_data = PACKAGE_DATA.relative_to(REPO_ROOT)
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--", str(relative_data)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"unable to enumerate tracked test data: {result.stderr.strip()}")
    return [REPO_ROOT / item for item in result.stdout.split("\0") if item]


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


@pytest.fixture(scope="session", autouse=True)
def isolated_data_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("hermes_data")
    data_root = root / "data"
    data_root.mkdir()
    for src in _tracked_package_files():
        relative = src.relative_to(PACKAGE_DATA)
        if relative.parent.name == "archive" and relative.name in ARCHIVE_EXCLUDE:
            continue
        _copy_file(src, data_root / relative)
    if TEST_DATA.exists():
        for src in TEST_DATA.rglob("*"):
            if src.is_file():
                _copy_file(src, data_root / src.relative_to(TEST_DATA))

    previous = os.environ.get("HERMES_DATA_DIR")
    os.environ["HERMES_DATA_DIR"] = str(root)
    yield root
    if previous is None:
        os.environ.pop("HERMES_DATA_DIR", None)
    else:
        os.environ["HERMES_DATA_DIR"] = previous
