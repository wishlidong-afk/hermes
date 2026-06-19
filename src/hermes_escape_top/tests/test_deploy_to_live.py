"""Isolated failure-injection tests for ``scripts/deploy_to_live.sh``."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy_to_live.sh"


def _write(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_git(path: Path) -> None:
    _git(path, "init", "-q")
    _git(path, "config", "user.name", "Hermes Deploy Test")
    _git(path, "config", "user.email", "deploy-test@example.invalid")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "fixture baseline")


def _snapshot(*roots: tuple[str, Path]) -> dict[str, tuple[str, int, str | None]]:
    snapshot: dict[str, tuple[str, int, str | None]] = {}
    for label, root in roots:
        for path in sorted([root, *root.rglob("*")]):
            if path.name == ".pipeline.lock":
                continue
            relative = "." if path == root else path.relative_to(root).as_posix()
            key = f"{label}/{relative}"
            info = path.lstat()
            mode = stat.S_IMODE(info.st_mode)
            if path.is_symlink():
                snapshot[key] = ("symlink", mode, os.readlink(path))
            elif path.is_dir():
                snapshot[key] = ("dir", mode, None)
            else:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                snapshot[key] = ("file", mode, digest)
    return snapshot


@pytest.fixture
def deploy_fixture(tmp_path: Path) -> dict[str, object]:
    repo = tmp_path / "repo"
    hermes_home = tmp_path / "hermes-home"
    live = hermes_home / "skills" / "investment" / "escape-top"
    package = live / "hermes_escape_top"
    bin_dir = hermes_home / "bin"
    backup_dir = tmp_path / "backups"
    events = tmp_path / "deploy-events.log"

    _write(repo / "src/hermes_escape_top/core/keep.py", "VALUE = 'new'\n")
    _write(repo / "src/hermes_escape_top/core/added.py", "ADDED = True\n")
    _write(repo / "src/hermes_escape_top/config/config.json", "{}\n")
    _write(repo / "src/hermes_escape_top/data/soft_history/source.csv", "date,value\n2026-06-18,2\n")
    _write(repo / "ops/run_daily.sh", "#!/bin/sh\nexit 0\n", 0o755)
    _write(repo / "ops/serve_dashboard.sh", "#!/bin/sh\nexit 0\n", 0o755)
    _write(repo / "ops/run_daily.py", "print('new entry')\n", 0o755)
    _init_git(repo)

    _write(package / "core/keep.py", "VALUE = 'old'\n", 0o640)
    _write(package / "core/removed.py", "REMOVED = True\n", 0o600)
    _write(package / "config/config.json", "{}\n", 0o640)
    _write(package / "data/soft_history/runtime.csv", "date,value\n2026-06-17,1\n", 0o600)
    # S8 regression guard: a .py under data/ and config/ must NOT reach the .hermes
    # commit even with `git add -f` — the :(exclude) pathspecs keep them out.
    _write(package / "data/leak.py", "SECRET = 'runtime-data'\n", 0o600)
    _write(package / "config/leak.py", "SECRET = 'config'\n", 0o600)
    _write(package / "data/archive/.pipeline.lock", "", 0o644)
    _write(package / "VERSION", "old-version\n", 0o644)
    _write(live / "scripts/run_daily.py", "print('old entry')\n", 0o700)
    _write(bin_dir / "run_daily.sh", "#!/bin/sh\nexit 10\n", 0o750)
    _write(bin_dir / "serve_dashboard.sh", "#!/bin/sh\nexit 11\n", 0o740)
    # Replicate the real ~/.hermes/.gitignore: it ignores bin/ and tests/, so the
    # allowlist entry scripts are untracked+ignored and the commit step must
    # `git add -f`. The old fixture had no .gitignore (git add . tracked bin/), so
    # the success test passed while the real deploy's `git add` failed + rolled back.
    _write(hermes_home / ".gitignore", "bin/\ntests/\n")
    _init_git(hermes_home)

    repo_soft = repo / "src/hermes_escape_top/data/soft_history"
    roots = (
        ("package", package),
        ("live-scripts", live / "scripts"),
        ("bin", bin_dir),
        ("repo-soft", repo_soft),
    )
    quoted_events = str(events).replace("'", "'\\''")
    env = os.environ.copy()
    env.update(
        {
            "HERMES_DEPLOY_TEST_MODE": "1",
            "HERMES_DEPLOY_REPO": str(repo),
            "HERMES_DEPLOY_HOME": str(hermes_home),
            "HERMES_DEPLOY_LIVE": str(live),
            "HERMES_DEPLOY_PACKAGE": str(package),
            "HERMES_DEPLOY_BIN": str(bin_dir),
            "HERMES_DEPLOY_BACKUP_DIR": str(backup_dir),
            "HERMES_DEPLOY_PYTHON": sys.executable,
            "HERMES_DEPLOY_LOCK_PYTHONPATH": str(REPO_ROOT / "src"),
            "HERMES_DEPLOY_GUARD_CMD": f"echo guard >> '{quoted_events}'",
            "HERMES_DEPLOY_DASHBOARD_STOP_CMD": f"echo stop >> '{quoted_events}'",
            "HERMES_DEPLOY_SMOKE_IMPORT_CMD": (
                f"echo smoke-import-${{HERMES_PIPELINE_LOCK_FD:+locked}} >> '{quoted_events}'"
            ),
            "HERMES_DEPLOY_SMOKE_CMD": (
                f"echo smoke-${{HERMES_PIPELINE_LOCK_FD:+locked}} >> '{quoted_events}'"
            ),
            "HERMES_DEPLOY_DASHBOARD_RESTART_CMD": (
                f"echo restart-${{HERMES_PIPELINE_LOCK_FD:+locked}} >> '{quoted_events}'"
            ),
            "HERMES_DEPLOY_DASHBOARD_HEALTH_CMD": (
                f"echo health-${{HERMES_PIPELINE_LOCK_FD:+locked}} >> '{quoted_events}'"
            ),
            "HERMES_DEPLOY_VERIFY_CMD": (
                f"echo verify-${{HERMES_PIPELINE_LOCK_FD:+locked}} >> '{quoted_events}'"
            ),
        }
    )
    return {
        "repo": repo,
        "hermes_home": hermes_home,
        "live": live,
        "package": package,
        "bin": bin_dir,
        "backup": backup_dir,
        "events": events,
        "roots": roots,
        "before": _snapshot(*roots),
        "before_status": _git(hermes_home, "status", "--porcelain=v1").stdout,
        "before_index": _git(hermes_home, "ls-files", "--stage").stdout,
        "env": env,
    }


def _run(fixture: dict[str, object], fail_at: str | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(fixture["env"])
    if fail_at:
        env["HERMES_DEPLOY_FAIL_AT"] = fail_at
    return subprocess.run(
        ["bash", str(DEPLOY_SCRIPT)],
        input="N\n",
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_deploy_script_exposes_isolated_fixture_contract() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    for marker in (
        "HERMES_DEPLOY_TEST_MODE",
        "HERMES_DEPLOY_REPO",
        "HERMES_DEPLOY_LIVE",
        "HERMES_DEPLOY_BACKUP_DIR",
        "HERMES_DEPLOY_DASHBOARD_STOP_CMD",
        "HERMES_DEPLOY_DASHBOARD_RESTART_CMD",
        "HERMES_DEPLOY_FAIL_AT",
        "--locked-swap",
        "--locked-rollback",
        "HERMES_PIPELINE_LOCK_FD",
        "DOUBLE FAILURE",
    ):
        assert marker in script


@pytest.mark.parametrize(
    ("fail_at", "expected_code"),
    [
        ("post_sync", 1),
        ("smoke", 2),
        ("dashboard_restart", 2),
        ("verify_live", 3),
        ("hermes_commit", 3),
    ],
)
def test_failure_injection_restores_paths_hashes_and_modes(
    deploy_fixture: dict[str, object], fail_at: str, expected_code: int
) -> None:
    result = _run(deploy_fixture, fail_at)

    assert result.returncode == expected_code
    assert "ROLLBACK" in result.stderr
    assert "deploy OK" not in result.stdout + result.stderr
    assert _snapshot(*deploy_fixture["roots"]) == deploy_fixture["before"]
    assert not (deploy_fixture["package"] / "core/added.py").exists()
    events = Path(deploy_fixture["events"]).read_text(encoding="utf-8").splitlines()
    assert "restart-locked" not in events
    assert events[0:2] == ["guard", "stop"]
    assert events[-1] == "restart-"
    if fail_at == "hermes_commit":
        hermes_home = Path(deploy_fixture["hermes_home"])
        assert _git(hermes_home, "status", "--porcelain=v1").stdout == deploy_fixture["before_status"]
        assert _git(hermes_home, "ls-files", "--stage").stdout == deploy_fixture["before_index"]
        assert _git(hermes_home, "diff", "--cached", "--name-only").stdout == ""


def test_rollback_failure_is_loud_and_retains_backup(deploy_fixture: dict[str, object]) -> None:
    env = dict(deploy_fixture["env"])
    env["HERMES_DEPLOY_FAIL_AT"] = "smoke"
    env["HERMES_DEPLOY_FAIL_ROLLBACK"] = "1"
    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT)],
        input="N\n",
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )

    assert result.returncode != 0
    assert "DOUBLE FAILURE" in result.stderr
    backups = list(Path(deploy_fixture["backup"]).glob("hermes_escape_top.predeploy_backup_*"))
    assert backups
    assert all(path.exists() for path in backups)
    assert "deploy OK" not in result.stdout + result.stderr


def test_isolated_success_reaches_single_success_exit(deploy_fixture: dict[str, object]) -> None:
    runtime = Path(deploy_fixture["package"]) / "data/soft_history/runtime.csv"
    runtime.write_text("date,value\n2026-06-17,999\n", encoding="utf-8")
    result = _run(deploy_fixture)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("deploy OK") == 1
    assert (deploy_fixture["package"] / "core/added.py").is_file()
    assert not (deploy_fixture["package"] / "core/removed.py").exists()
    subject = _git(Path(deploy_fixture["hermes_home"]), "log", "-1", "--format=%s").stdout
    assert subject.startswith("deploy escape-top @")
    committed = set(
        _git(
            Path(deploy_fixture["hermes_home"]),
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            "HEAD",
        ).stdout.splitlines()
    )
    assert committed == {
        "bin/run_daily.sh",
        "bin/serve_dashboard.sh",
        "skills/investment/escape-top/hermes_escape_top/VERSION",
        "skills/investment/escape-top/hermes_escape_top/core/added.py",
        "skills/investment/escape-top/hermes_escape_top/core/keep.py",
        "skills/investment/escape-top/hermes_escape_top/core/removed.py",
        "skills/investment/escape-top/scripts/run_daily.py",
    }
    assert not any("leak.py" in path for path in committed), (
        "git add -f leaked a data/ or config/ .py into the .hermes commit"
    )
    assert "999" in runtime.read_text(encoding="utf-8")
    assert _snapshot(("repo-soft", Path(deploy_fixture["repo"]) / "src/hermes_escape_top/data/soft_history")) == {
        key: value
        for key, value in deploy_fixture["before"].items()
        if key.startswith("repo-soft/")
    }
    events = Path(deploy_fixture["events"]).read_text(encoding="utf-8").splitlines()
    assert events == [
        "guard",
        "stop",
        "smoke-import-locked",
        "smoke-locked",
        "restart-",
        "health-",
        "verify-",
    ]


def test_internal_locked_swap_rejects_missing_inherited_fd(
    deploy_fixture: dict[str, object],
) -> None:
    env = dict(deploy_fixture["env"])
    env.pop("HERMES_PIPELINE_LOCK_FD", None)
    backup = Path(deploy_fixture["backup"]) / "manual-backup"
    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "--locked-swap", "manual", "deadbee", str(backup)],
        input="N\n",
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )

    assert result.returncode != 0
    assert "valid HERMES_PIPELINE_LOCK_FD" in result.stderr
    assert _snapshot(*deploy_fixture["roots"]) == deploy_fixture["before"]


def test_internal_locked_swap_rejects_open_but_unlocked_target_fd(
    deploy_fixture: dict[str, object],
) -> None:
    env = dict(deploy_fixture["env"])
    lock_path = Path(deploy_fixture["package"]) / "data/archive/.pipeline.lock"
    backup = Path(deploy_fixture["backup"]) / "manual-backup"
    lock_fd = os.open(lock_path, os.O_RDWR)
    env["HERMES_PIPELINE_LOCK_FD"] = str(lock_fd)
    try:
        result = subprocess.run(
            ["bash", str(DEPLOY_SCRIPT), "--locked-swap", "manual", "deadbee", str(backup)],
            input="N\n",
            capture_output=True,
            text=True,
            env=env,
            pass_fds=(lock_fd,),
            timeout=30,
        )
    finally:
        os.close(lock_fd)

    assert result.returncode != 0
    assert "target lock is not held" in result.stderr
    assert "requires the pipeline lock to be held" in result.stderr
    assert _snapshot(*deploy_fixture["roots"]) == deploy_fixture["before"]


def test_production_mode_ignores_all_test_path_overrides(
    deploy_fixture: dict[str, object], tmp_path: Path
) -> None:
    fake_home = tmp_path / "empty-production-home"
    fake_home.mkdir()
    env = dict(deploy_fixture["env"])
    env["HOME"] = str(fake_home)
    env["HERMES_DEPLOY_TEST_MODE"] = "0"
    env["HERMES_DEPLOY_FAIL_AT"] = "post_sync"
    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT)],
        input="N\n",
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )

    expected_repo = fake_home / "Documents/github/hermes"
    assert result.returncode == 64
    assert str(expected_repo) in result.stderr
    assert "injected failure" not in result.stderr
    assert _snapshot(*deploy_fixture["roots"]) == deploy_fixture["before"]


def test_pre_staged_allowlist_file_aborts_before_dashboard_stop(
    deploy_fixture: dict[str, object],
) -> None:
    hermes_home = Path(deploy_fixture["hermes_home"])
    staged = hermes_home / "skills/investment/escape-top/hermes_escape_top/core/keep.py"
    staged.write_text("VALUE = 'human-staged'\n", encoding="utf-8")
    _git(hermes_home, "add", str(staged.relative_to(hermes_home)))

    result = _run(deploy_fixture)

    assert result.returncode == 4
    assert "pre-staged deploy-allowlist" in result.stderr
    events = Path(deploy_fixture["events"]).read_text(encoding="utf-8").splitlines()
    assert events == ["guard"]
    assert not list(Path(deploy_fixture["backup"]).glob("hermes_escape_top.predeploy_backup_*"))
