"""Guard production-like entrypoints against repository-local runtime data."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from ...config import DATA_DIR_ENV, PACKAGE_DIR


class RuntimeDataRootError(RuntimeError):
    """Raised when a source checkout would implicitly use package-local data."""


def require_explicit_runtime_data_root(operation: str) -> Path:
    """Return the selected data root, rejecting implicit roots in a checkout.

    R6 releases are packaged outside the repository ``src/`` layout and retain
    their package-level data symlink fallback. Tests, research runs, and direct
    source-checkout operations should set ``HERMES_DATA_DIR`` explicitly.
    """
    configured = str(os.environ.get(DATA_DIR_ENV) or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    checkout = _source_checkout_root(PACKAGE_DIR)
    if checkout is not None:
        raise RuntimeDataRootError(
            f"{operation}: refusing implicit package-local runtime data from git "
            f"checkout {checkout}; set {DATA_DIR_ENV} to an explicit isolated or "
            "live data root"
        )
    return PACKAGE_DIR.resolve()


def _source_checkout_root(package_dir: Path) -> Optional[Path]:
    """Recognize only the repository ``src/hermes_escape_top`` layout."""
    package_dir = package_dir.resolve()
    if package_dir.name != "hermes_escape_top" or package_dir.parent.name != "src":
        return None
    checkout = package_dir.parent.parent
    return checkout if (checkout / ".git").exists() else None
