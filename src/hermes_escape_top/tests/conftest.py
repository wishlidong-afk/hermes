"""Session-wide data isolation for the test suite (roadmap T8c).

score_pipeline / bootstrap_history write into the package data dirs; without
isolation every test run dirties git-tracked runtime CSVs and sqlite files
(the old "never git add -A" footgun). This fixture re-roots all relative
config paths via HERMES_DATA_DIR (see config.resolve_path) to a throwaway
copy seeded from the real package data.

audit_log.jsonl (hundreds of MB) is excluded from the seed: tests that need
audit history write their own entries into the empty copy.

APFS clonefile (cp -c) makes the seed copy near-instant and space-free;
falls back to a regular copy on other filesystems.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

PACKAGE_DATA = Path(__file__).resolve().parents[1] / "data"
SEED_SUBDIRS = ("history", "soft_history")
ARCHIVE_EXCLUDE = {"audit_log.jsonl"}


def _clone(src: Path, dst: Path) -> None:
    result = subprocess.run(["cp", "-Rc", str(src), str(dst)],
                            capture_output=True)
    if result.returncode != 0:
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)


@pytest.fixture(scope="session", autouse=True)
def isolated_data_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("hermes_data")
    data_root = root / "data"
    data_root.mkdir()
    for sub in SEED_SUBDIRS:
        src = PACKAGE_DATA / sub
        if src.exists():
            _clone(src, data_root / sub)
    src_archive = PACKAGE_DATA / "archive"
    if src_archive.exists():
        dst_archive = data_root / "archive"
        dst_archive.mkdir()
        for item in src_archive.iterdir():
            if item.name not in ARCHIVE_EXCLUDE:
                _clone(item, dst_archive / item.name)
    for extra in ("sentiment.xls",):
        src = PACKAGE_DATA / extra
        if src.exists():
            _clone(src, data_root / extra)

    previous = os.environ.get("HERMES_DATA_DIR")
    os.environ["HERMES_DATA_DIR"] = str(root)
    yield root
    if previous is None:
        os.environ.pop("HERMES_DATA_DIR", None)
    else:
        os.environ["HERMES_DATA_DIR"] = previous
