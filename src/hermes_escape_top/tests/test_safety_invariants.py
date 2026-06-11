"""Repository-level safety guards for the read-only Hermes red lines."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION_ROOTS = [
    REPO_ROOT / "src" / "hermes_escape_top",
    REPO_ROOT / "scripts",
]
FORBIDDEN_TLS_PATTERNS = [
    "ssl.CERT_NONE",
    "CERT_NONE",
    "verify=False",
    "verify = False",
    "check_hostname = False",
    "check_hostname=False",
]
FORBIDDEN_IBKR_METHODS = {
    "placeOrder",
    "place_order",
    "cancelOrder",
    "bracketOrder",
    "oneCancelsAll",
    "reqGlobalCancel",
}


def _production_python_files() -> list[Path]:
    files: list[Path] = []
    for root in PRODUCTION_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            rel_parts = path.relative_to(REPO_ROOT).parts
            if "tests" in rel_parts or "__pycache__" in rel_parts:
                continue
            files.append(path)
    return sorted(files)


def test_no_tls_verification_bypass_in_production_code() -> None:
    offenders: list[str] = []
    for path in _production_python_files():
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_TLS_PATTERNS:
            if pattern in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)} contains {pattern}")
    assert not offenders, "\n".join(offenders)


def test_no_ibkr_order_methods_in_production_code() -> None:
    offenders: list[str] = []
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_IBKR_METHODS:
                offenders.append(f"{path.relative_to(REPO_ROOT)} uses .{node.attr}")
            elif isinstance(node, ast.Name) and node.id in FORBIDDEN_IBKR_METHODS:
                offenders.append(f"{path.relative_to(REPO_ROOT)} references {node.id}")
    assert not offenders, "\n".join(offenders)


def test_ibkr_config_readonly_is_true() -> None:
    config_path = REPO_ROOT / "src" / "hermes_escape_top" / "config" / "config.json"
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    assert cfg["ibkr"]["readonly"] is True


def test_runtime_data_is_isolated_from_repo() -> None:
    """T8: with the conftest isolation fixture active, no relative data path
    may resolve inside the git-tracked package dir — tests must not dirty
    tracked runtime CSVs/sqlite."""
    from hermes_escape_top.config import PACKAGE_DIR, load_config, resolve_path

    cfg = load_config()
    for key in ("history_dir", "archive_dir", "soft_history_dir"):
        resolved = resolve_path(cfg, key)
        assert PACKAGE_DIR not in resolved.parents, (
            f"paths.{key} resolves inside the package while HERMES_DATA_DIR "
            f"isolation is active: {resolved}"
        )


def test_ibkr_connect_calls_are_readonly() -> None:
    offenders: list[str] = []
    for path in (REPO_ROOT / "src" / "hermes_escape_top" / "ibkr").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\.connect\((?P<args>.*?)\)", text, re.S):
            args = match.group("args")
            if "readonly=True" not in args and "readonly = True" not in args:
                offenders.append(f"{path.relative_to(REPO_ROOT)} has IBKR connect without readonly=True")
    assert not offenders, "\n".join(offenders)
