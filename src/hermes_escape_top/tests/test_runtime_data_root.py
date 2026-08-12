from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_escape_top import cli
from hermes_escape_top.core.data import runtime_root
from hermes_escape_top.core.data.runtime_root import (
    RuntimeDataRootError,
    require_explicit_runtime_data_root,
)
from hermes_escape_top.scripts import run_daily_package
from hermes_escape_top.web import server as web_server

REPO_ROOT = Path(__file__).resolve().parents[3]


def _source_checkout(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    package = repo / "src" / "hermes_escape_top"
    package.mkdir(parents=True)
    (repo / ".git").write_text("gitdir: /tmp/example\n", encoding="utf-8")
    return package


def test_repo_runtime_guard_rejects_implicit_package_data_without_writes(
    monkeypatch,
    tmp_path,
):
    package = _source_checkout(tmp_path)
    monkeypatch.setattr(runtime_root, "PACKAGE_DIR", package)
    monkeypatch.delenv("HERMES_DATA_DIR", raising=False)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    with pytest.raises(RuntimeDataRootError, match=r"score.*HERMES_DATA_DIR"):
        require_explicit_runtime_data_root("score")

    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert after == before


def test_explicit_isolated_data_root_is_accepted(monkeypatch, tmp_path):
    package = _source_checkout(tmp_path)
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    monkeypatch.setattr(runtime_root, "PACKAGE_DIR", package)
    monkeypatch.setenv("HERMES_DATA_DIR", str(isolated))

    assert require_explicit_runtime_data_root("score") == isolated.resolve()


def test_packaged_r6_root_is_accepted_without_repo_data_override(monkeypatch, tmp_path):
    hermes_home = tmp_path / ".hermes"
    (hermes_home / ".git").mkdir(parents=True)
    package = (
        hermes_home
        / "skills/investment/escape-top/releases/test-release/hermes_escape_top"
    )
    package.mkdir(parents=True)
    monkeypatch.setattr(runtime_root, "PACKAGE_DIR", package)
    monkeypatch.delenv("HERMES_DATA_DIR", raising=False)

    assert require_explicit_runtime_data_root("daily") == package.resolve()


@pytest.mark.parametrize("command", ["score", "dashboard"])
def test_repo_cli_production_entrypoints_reject_implicit_data_root(
    command,
    monkeypatch,
):
    monkeypatch.delenv("HERMES_DATA_DIR", raising=False)
    argv = ["hermes", command, "--as-of", "2026-07-10"]
    if command == "dashboard":
        argv.extend(["--output", "/tmp/should-not-exist.html"])
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(
        cli,
        "score_pipeline",
        lambda *_args, **_kwargs: pytest.fail("score pipeline must not be reached"),
    )

    with pytest.raises(RuntimeDataRootError, match=rf"{command}.*HERMES_DATA_DIR"):
        cli.main()


def test_repo_web_refresh_server_rejects_implicit_data_root(monkeypatch):
    monkeypatch.delenv("HERMES_DATA_DIR", raising=False)
    server = None
    try:
        with pytest.raises(RuntimeDataRootError, match=r"dashboard.*HERMES_DATA_DIR"):
            server = web_server.create_server("127.0.0.1", 0, "2026-07-10")
    finally:
        if server is not None:
            server.server_close()


def test_repo_daily_rejects_implicit_data_root_before_lock_or_receipt(
    monkeypatch,
):
    monkeypatch.delenv("HERMES_DATA_DIR", raising=False)

    class _Parser:
        @staticmethod
        def parse_args():
            return SimpleNamespace(
                as_of="2026-07-10",
                skip_refresh=True,
                live=True,
                commit_state=False,
                run_type="scheduled",
                lock_timeout=0.0,
            )

    @contextlib.contextmanager
    def _unexpected_lock(*_args, **_kwargs):
        pytest.fail("pipeline lock must not be reached")
        yield

    monkeypatch.setattr(run_daily_package, "_build_daily_parser", lambda: _Parser())
    monkeypatch.setattr(
        "hermes_escape_top.core.safe_io.pipeline_lock",
        _unexpected_lock,
    )

    with pytest.raises(RuntimeDataRootError, match=r"daily.*HERMES_DATA_DIR"):
        run_daily_package.main()


@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        (
            "score",
            ["-m", "hermes_escape_top.cli", "score", "--as-of", "2026-07-10"],
        ),
        (
            "dashboard",
            [
                "-m",
                "hermes_escape_top.cli",
                "dashboard",
                "--as-of",
                "2026-07-10",
                "--output",
                "/tmp/hermes-implicit-dashboard-must-not-exist.html",
            ],
        ),
        (
            "dashboard",
            [
                "-c",
                "from hermes_escape_top.web.server import create_server; "
                "create_server('127.0.0.1', 0, '2026-07-10')",
            ],
        ),
        (
            "daily",
            [
                "-m",
                "hermes_escape_top.scripts.run_daily_package",
                "--as-of",
                "2026-07-10",
                "--skip-refresh",
            ],
        ),
        (
            "refresh",
            [
                "-m",
                "hermes_escape_top.scripts.refresh_external",
                "--status",
            ],
        ),
    ],
)
def test_repo_production_processes_exit_nonzero_before_runtime_writes(
    operation,
    arguments,
    tmp_path,
):
    dashboard_output = tmp_path / "implicit-dashboard-must-not-exist.html"
    arguments = [
        str(dashboard_output) if value == "/tmp/hermes-implicit-dashboard-must-not-exist.html" else value
        for value in arguments
    ]
    env = os.environ.copy()
    env.pop("HERMES_DATA_DIR", None)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    package_data = REPO_ROOT / "src/hermes_escape_top/data"
    before = {
        path.relative_to(package_data): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in package_data.rglob("*")
        if path.is_file()
    }

    result = subprocess.run(
        [sys.executable, *arguments],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )

    after = {
        path.relative_to(package_data): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in package_data.rglob("*")
        if path.is_file()
    }
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert operation in output
    assert "HERMES_DATA_DIR" in output
    assert after == before
    assert not dashboard_output.exists()
