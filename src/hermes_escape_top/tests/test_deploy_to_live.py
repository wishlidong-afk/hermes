"""Isolated failure-injection tests for ``scripts/deploy_to_live.sh``."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy_to_live.sh"


def _semantic_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_live_config_policy(
    repo: Path,
    *,
    repo_config: dict,
    live_config: dict,
    approved_feature_diff: dict | None = None,
) -> None:
    _write(
        repo / "src/hermes_escape_top/governance/approved_live_config.json",
        json.dumps(
            {
                "schema_version": "hermes-approved-live-config-v1",
                "repo_config_semantic_sha256": _semantic_sha256(repo_config),
                "live_config_semantic_sha256": _semantic_sha256(live_config),
                "approved_feature_diff": approved_feature_diff or {},
                "required_values": {"ibkr.readonly": True},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


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
    launchagents_dir = tmp_path / "LaunchAgents"
    backup_dir = tmp_path / "backups"
    events = tmp_path / "deploy-events.log"

    _write(repo / "src/hermes_escape_top/core/keep.py", "VALUE = 'new'\n")
    _write(repo / "src/hermes_escape_top/core/added.py", "ADDED = True\n")
    _write(repo / "src/hermes_escape_top/core/data/keep.py", "DATA_CODE = True\n")
    repo_config = {"features": {}, "ibkr": {"readonly": True}}
    live_config = {"features": {}, "ibkr": {"readonly": True}}
    _write(
        repo / "src/hermes_escape_top/config/config.json",
        json.dumps(repo_config) + "\n",
    )
    _write_live_config_policy(
        repo,
        repo_config=repo_config,
        live_config=live_config,
    )
    validator_source = (
        REPO_ROOT / "src/hermes_escape_top/governance/live_config_policy.py"
    )
    _write(
        repo / "src/hermes_escape_top/governance/live_config_policy.py",
        validator_source.read_text(encoding="utf-8"),
    )
    _write(repo / "src/hermes_escape_top/governance/__init__.py", "\n")
    _write(repo / "src/hermes_escape_top/data/soft_history/source.csv", "date,value\n2026-06-18,2\n")
    _write(repo / "requirements.lock", "numpy==2.0.2 --hash=sha256:fixture\n")
    _write(repo / "ops/run_daily.sh", "#!/bin/sh\nexit 0\n", 0o755)
    _write(repo / "ops/serve_dashboard.sh", "#!/bin/sh\nexit 0\n", 0o755)
    _write(repo / "ops/refresh_external_precheck.sh", "#!/bin/sh\nexit 0\n", 0o755)
    _write(repo / "ops/refresh_external.sh", "#!/bin/sh\nexit 0\n", 0o755)
    _write(repo / "ops/hermes_watchdog.py", "#!/usr/bin/env python3\nprint('new watchdog')\n", 0o644)
    _write(repo / "ops/prune_runtime_artifacts.py", "#!/usr/bin/env python3\nprint('new retention')\n", 0o644)
    _write(repo / "ops/launchagents/com.hermes.external-precheck.plist", "<plist><dict><key>new</key><true/></dict></plist>\n")
    _write(repo / "ops/launchagents/com.hermes.runtime-retention.plist", "<plist><dict><key>new-retention</key><true/></dict></plist>\n")
    _write(repo / "ops/run_daily.py", "print('new entry')\n", 0o755)
    _init_git(repo)

    _write(package / "core/keep.py", "VALUE = 'old'\n", 0o640)
    _write(package / "core/removed.py", "REMOVED = True\n", 0o600)
    _write(
        package / "config/config.json",
        json.dumps(live_config) + "\n",
        0o640,
    )
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
    _write(bin_dir / "refresh_external_precheck.sh", "#!/bin/sh\nexit 12\n", 0o730)
    _write(bin_dir / "refresh_external.sh", "#!/bin/sh\nexit 13\n", 0o720)
    _write(bin_dir / "hermes_watchdog.py", "#!/usr/bin/env python3\nprint('old watchdog')\n", 0o640)
    _write(bin_dir / "prune_runtime_artifacts.py", "#!/usr/bin/env python3\nprint('old retention')\n", 0o640)
    _write(launchagents_dir / "com.hermes.external-precheck.plist", "<plist><dict><key>old</key><true/></dict></plist>\n")
    _write(launchagents_dir / "com.hermes.runtime-retention.plist", "<plist><dict><key>old-retention</key><true/></dict></plist>\n")
    # Replicate the real ~/.hermes/.gitignore: it ignores bin/ and tests/, so the
    # allowlist entry scripts are untracked+ignored and the commit step must
    # `git add -f`. The old fixture had no .gitignore (git add . tracked bin/), so
    # the success test passed while the real deploy's `git add` failed + rolled back.
    _write(hermes_home / ".gitignore", "bin/\ntests/\n")
    _init_git(hermes_home)

    repo_soft = repo / "src/hermes_escape_top/data/soft_history"
    roots = (
        ("live", live),
        ("package", package),
        ("live-scripts", live / "scripts"),
        ("bin", bin_dir),
        ("launchagents", launchagents_dir),
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
            "HERMES_DEPLOY_LAUNCHAGENTS_DIR": str(launchagents_dir),
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
            "HERMES_DEPLOY_EXTERNAL_PRECHECK_RELOAD_CMD": (
                f"echo external-reload-${{HERMES_PIPELINE_LOCK_FD:+locked}} >> '{quoted_events}'"
            ),
            "HERMES_DEPLOY_RETENTION_RELOAD_CMD": (
                f"echo retention-reload-${{HERMES_PIPELINE_LOCK_FD:+locked}} >> '{quoted_events}'"
            ),
            "HERMES_DEPLOY_RUNTIME_PREP_CMD": (
                f"echo runtime-prep >> '{quoted_events}'"
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
        "launchagents": launchagents_dir,
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


def _promote_fixture_to_existing_r6(fixture: dict[str, object]) -> Path:
    live = Path(fixture["live"])
    shared = live / "shared/hermes_escape_top"
    _write(shared / "data/archive/.pipeline.lock", "", 0o644)
    _write(shared / "data/soft_history/runtime.csv", "date,value\n2026-06-17,1\n", 0o600)
    _write(
        shared / "config/config.json",
        (Path(fixture["package"]) / "config/config.json").read_text(encoding="utf-8"),
        0o640,
    )

    old_release = live / "releases/old_release"
    old_package = old_release / "hermes_escape_top"
    _write(old_package / "core/keep.py", "VALUE = 'old release'\n", 0o640)
    _write(old_package / "VERSION", "old-release\n", 0o644)
    _write(old_release / "scripts/run_daily.py", "print('old release entry')\n", 0o700)
    (old_package / "data").symlink_to(shared / "data", target_is_directory=True)
    (old_package / "config").symlink_to(shared / "config", target_is_directory=True)
    (live / "current").symlink_to(Path("releases/old_release"), target_is_directory=True)
    return old_release


def test_deploy_script_exposes_isolated_fixture_contract() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    for marker in (
        "HERMES_DEPLOY_TEST_MODE",
        "HERMES_DEPLOY_REPO",
        "HERMES_DEPLOY_LIVE",
        "HERMES_DEPLOY_BACKUP_DIR",
        "HERMES_DEPLOY_DASHBOARD_STOP_CMD",
        "HERMES_DEPLOY_DASHBOARD_RESTART_CMD",
        "HERMES_DEPLOY_EXTERNAL_PRECHECK_RELOAD_CMD",
        "HERMES_DEPLOY_RETENTION_RELOAD_CMD",
        "HERMES_DEPLOY_FAIL_AT",
        "--locked-swap",
        "--locked-rollback",
        "HERMES_PIPELINE_LOCK_FD",
        "DOUBLE FAILURE",
    ):
        assert marker in script
    assert 'chmod +x "$BIN/hermes_watchdog.py" || return 1' in script


@pytest.mark.parametrize(
    ("relative_path", "replacement"),
    [
        ("src/hermes_escape_top/core/keep.py", "VALUE = 'dirty code'\n"),
        (
            "src/hermes_escape_top/governance/approved_live_config.json",
            '{"schema_version":"self-authorized-dirty-policy"}\n',
        ),
        (
            "src/hermes_escape_top/governance/live_config_policy.py",
            "# dirty validator bypass\n",
        ),
        (
            "src/hermes_escape_top/config/config.json",
            '{"features":{"dirty":true},"ibkr":{"readonly":true}}\n',
        ),
        ("ops/run_daily.py", "print('dirty entry')\n"),
    ],
)
def test_deploy_rejects_dirty_managed_source_before_dashboard_stop(
    deploy_fixture: dict[str, object],
    relative_path: str,
    replacement: str,
) -> None:
    repo = Path(deploy_fixture["repo"])
    _write(repo / relative_path, replacement)

    result = _run(deploy_fixture)

    assert result.returncode == 4
    assert "source tree differs from captured HEAD" in result.stderr
    events = Path(deploy_fixture["events"])
    assert not events.exists(), "source guard must run before runtime prep or dashboard stop"
    assert "deploy OK" not in result.stdout + result.stderr


def test_deploy_rejects_untracked_python_in_managed_source(
    deploy_fixture: dict[str, object],
) -> None:
    repo = Path(deploy_fixture["repo"])
    _write(repo / "src/hermes_escape_top/core/untracked.py", "UNREVIEWED = True\n")

    result = _run(deploy_fixture)

    assert result.returncode == 4
    assert "source tree differs from captured HEAD" in result.stderr
    assert not Path(deploy_fixture["events"]).exists()


def test_stable_entry_install_and_restore_use_same_directory_atomic_replace() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert "install_entry_atomic()" in script
    assert 'temp=$(mktemp "$directory/.${name}.deploy.XXXXXX")' in script
    assert 'mv -f "$temp" "$destination"' in script
    assert 'install_entry_atomic "$BACKUP/bin/$name" "$target"' in script
    assert 'install_entry_atomic "$src" "$BIN/run_daily.sh"' in script
    assert 'install_entry_atomic "$src" "$dst"' in script
    assert (
        'restore_entry "$LIVE/scripts/run_daily.py" live_run_daily.py' in script
    )
    assert '"$BACKUP/live_scripts/" "$LIVE/scripts/"' not in script
    assert 'cp "$src" "$dst"' not in script


@pytest.mark.parametrize(
    ("fail_at", "expected_code"),
    [
        ("post_sync", 1),
        ("smoke", 2),
        ("external_precheck_reload", 2),
        ("runtime_retention_reload", 2),
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
    assert (Path(deploy_fixture["bin"]) / "hermes_watchdog.py").read_text(
        encoding="utf-8"
    ) == "#!/usr/bin/env python3\nprint('old watchdog')\n"
    events = Path(deploy_fixture["events"]).read_text(encoding="utf-8").splitlines()
    assert "restart-locked" not in events
    assert events[0:3] == ["runtime-prep", "guard", "stop"]
    assert events[-1] == "restart-"
    if fail_at == "hermes_commit":
        hermes_home = Path(deploy_fixture["hermes_home"])
        assert _git(hermes_home, "status", "--porcelain=v1").stdout == deploy_fixture["before_status"]
        assert _git(hermes_home, "ls-files", "--stage").stdout == deploy_fixture["before_index"]
        assert _git(hermes_home, "diff", "--cached", "--name-only").stdout == ""


def test_first_retention_install_can_roll_back_to_absent_launchagent(
    deploy_fixture: dict[str, object],
) -> None:
    retention_plist = (
        Path(deploy_fixture["launchagents"]) / "com.hermes.runtime-retention.plist"
    )
    retention_plist.unlink()
    deploy_fixture["env"]["HERMES_DEPLOY_RETENTION_RELOAD_CMD"] = (
        f"test -e '{retention_plist}'"
    )
    deploy_fixture["before"] = _snapshot(*deploy_fixture["roots"])

    result = _run(deploy_fixture, "dashboard_restart")

    assert result.returncode == 2
    assert "ROLLBACK" in result.stderr
    assert "DOUBLE FAILURE" not in result.stderr
    assert not retention_plist.exists()
    assert _snapshot(*deploy_fixture["roots"]) == deploy_fixture["before"]


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
    live = Path(deploy_fixture["live"])
    current = live / "current"
    assert current.is_symlink()
    release = current.resolve()
    assert release.parent == live / "releases"
    assert (release / "hermes_escape_top/core/added.py").is_file()
    assert (release / "hermes_escape_top/core/data/keep.py").is_file()
    assert not (release / "hermes_escape_top/core/removed.py").exists()
    assert (release / "hermes_escape_top/data").is_symlink()
    assert (release / "hermes_escape_top/config").is_symlink()
    attestation_path = release / "hermes_escape_top/LIVE_CONFIG_ATTESTATION.json"
    assert attestation_path.is_file()
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    assert attestation["schema_version"] == "hermes-live-config-attestation-v2"
    assert attestation["release_hash"] == release.name.split("_", 1)[0]
    assert attestation["live_config_sha256"] == hashlib.sha256(
        (release / "hermes_escape_top/config/config.json").read_bytes()
    ).hexdigest()
    assert (release / "data").is_symlink()
    assert (release / "reports").is_symlink()
    assert (release / "orders").is_symlink()
    assert not (Path(deploy_fixture["package"]) / "core/added.py").exists()
    subject = _git(Path(deploy_fixture["hermes_home"]), "log", "-1", "--format=%s").stdout
    assert subject.startswith("deploy escape-top @")
    release_prefix = f"skills/investment/escape-top/releases/{release.name}"
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
        "bin/refresh_external_precheck.sh",
        "bin/refresh_external.sh",
        "bin/hermes_watchdog.py",
        "bin/prune_runtime_artifacts.py",
        "skills/investment/escape-top/current",
        f"{release_prefix}/data",
        f"{release_prefix}/hermes_escape_top/config",
        f"{release_prefix}/hermes_escape_top/data",
        f"{release_prefix}/hermes_escape_top/VERSION",
        f"{release_prefix}/hermes_escape_top/RUNTIME_LOCK_SHA256",
        f"{release_prefix}/hermes_escape_top/LIVE_CONFIG_ATTESTATION.json",
        f"{release_prefix}/hermes_escape_top/governance/approved_live_config.json",
        f"{release_prefix}/hermes_escape_top/governance/__init__.py",
        f"{release_prefix}/hermes_escape_top/governance/live_config_policy.py",
        f"{release_prefix}/hermes_escape_top/core/added.py",
        f"{release_prefix}/hermes_escape_top/core/data/keep.py",
        f"{release_prefix}/hermes_escape_top/core/keep.py",
        f"{release_prefix}/orders",
        f"{release_prefix}/reports",
        f"{release_prefix}/scripts/run_daily.py",
        "skills/investment/escape-top/scripts/run_daily.py",
    }
    assert not any("leak.py" in path for path in committed), (
        "git add -f leaked a data/ or config/ .py into the .hermes commit"
    )
    assert (
        Path(deploy_fixture["launchagents"]) / "com.hermes.external-precheck.plist"
    ).read_text(encoding="utf-8") == "<plist><dict><key>new</key><true/></dict></plist>\n"
    assert (
        Path(deploy_fixture["launchagents"]) / "com.hermes.runtime-retention.plist"
    ).read_text(encoding="utf-8") == "<plist><dict><key>new-retention</key><true/></dict></plist>\n"
    watchdog = Path(deploy_fixture["bin"]) / "hermes_watchdog.py"
    assert watchdog.read_text(encoding="utf-8") == "#!/usr/bin/env python3\nprint('new watchdog')\n"
    assert watchdog.stat().st_mode & stat.S_IXUSR
    retention = Path(deploy_fixture["bin"]) / "prune_runtime_artifacts.py"
    assert retention.read_text(encoding="utf-8") == "#!/usr/bin/env python3\nprint('new retention')\n"
    assert retention.stat().st_mode & stat.S_IXUSR
    assert "999" in runtime.read_text(encoding="utf-8")
    assert _snapshot(("repo-soft", Path(deploy_fixture["repo"]) / "src/hermes_escape_top/data/soft_history")) == {
        key: value
        for key, value in deploy_fixture["before"].items()
        if key.startswith("repo-soft/")
    }
    events = Path(deploy_fixture["events"]).read_text(encoding="utf-8").splitlines()
    assert events == [
        "runtime-prep",
        "guard",
        "stop",
        "smoke-import-locked",
        "smoke-locked",
        "external-reload-",
        "retention-reload-",
        "restart-",
        "health-",
        "verify-",
    ]


def test_live_config_attestation_contains_only_hashes_and_boolean_feature_diff(
    deploy_fixture: dict[str, object],
) -> None:
    repo_config = {
        "features": {"use_market_admission_gate": False, "repo_only": True},
        "fred": {"api_key": "repo-secret"},
        "ibkr": {"readonly": True},
    }
    live_config = {
        "features": {"use_market_admission_gate": True, "live_only": True},
        "fred": {"api_key": "live-secret"},
        "ibkr": {"readonly": True},
    }
    _write(
        Path(deploy_fixture["repo"]) / "src/hermes_escape_top/config/config.json",
        json.dumps(repo_config) + "\n",
    )
    _write(
        Path(deploy_fixture["package"]) / "config/config.json",
        json.dumps(live_config) + "\n",
        0o640,
    )
    _write_live_config_policy(
        Path(deploy_fixture["repo"]),
        repo_config=repo_config,
        live_config=live_config,
        approved_feature_diff={
            "live_only": {"live": True, "repo": False},
            "repo_only": {"live": False, "repo": True},
            "use_market_admission_gate": {"live": True, "repo": False},
        },
    )
    _git(Path(deploy_fixture["repo"]), "add", ".")
    _git(
        Path(deploy_fixture["repo"]),
        "commit",
        "-q",
        "-m",
        "approved attestation fixture",
    )

    result = _run(deploy_fixture)

    assert result.returncode == 0, result.stdout + result.stderr
    current = Path(deploy_fixture["live"]) / "current/hermes_escape_top"
    path = current / "LIVE_CONFIG_ATTESTATION.json"
    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert "repo-secret" not in text
    assert "live-secret" not in text
    assert payload["feature_diff"] == {
        "live_only": {"live": True, "repo": False},
        "repo_only": {"live": False, "repo": True},
        "use_market_admission_gate": {"live": True, "repo": False},
    }
    assert payload["retention_policy_active_since"]
    assert payload["retention_first_expected_at"]
    assert payload["policy_sha256"] == hashlib.sha256(
        (
            Path(deploy_fixture["repo"])
            / "src/hermes_escape_top/governance/approved_live_config.json"
        ).read_bytes()
    ).hexdigest()


def test_deploy_rejects_live_config_not_approved_by_repository_policy(
    deploy_fixture: dict[str, object],
) -> None:
    repo = Path(deploy_fixture["repo"])
    package = Path(deploy_fixture["package"])
    repo_config = {"features": {"rogue": False}, "ibkr": {"readonly": True}}
    unapproved_live = {"features": {"rogue": True}, "ibkr": {"readonly": True}}
    approved_live = {"features": {"rogue": False}, "ibkr": {"readonly": True}}
    _write(
        repo / "src/hermes_escape_top/config/config.json",
        json.dumps(repo_config) + "\n",
    )
    _write(
        package / "config/config.json",
        json.dumps(unapproved_live) + "\n",
        0o640,
    )
    _write_live_config_policy(
        repo,
        repo_config=repo_config,
        live_config=approved_live,
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "approved policy fixture")

    result = _run(deploy_fixture)

    assert result.returncode != 0
    assert "live config policy" in (result.stdout + result.stderr).lower()
    assert "deploy OK" not in result.stdout + result.stderr


def test_existing_r6_success_switches_current_and_preserves_old_as_previous(
    deploy_fixture: dict[str, object],
) -> None:
    old_release = _promote_fixture_to_existing_r6(deploy_fixture)

    result = _run(deploy_fixture)

    assert result.returncode == 0, result.stdout + result.stderr
    live = Path(deploy_fixture["live"])
    assert (live / "current").resolve() != old_release
    assert (live / "previous").resolve() == old_release
    watchdog = Path(deploy_fixture["bin"]) / "hermes_watchdog.py"
    assert watchdog.read_text(encoding="utf-8") == "#!/usr/bin/env python3\nprint('new watchdog')\n"
    assert watchdog.stat().st_mode & stat.S_IXUSR


def test_existing_r6_failure_restores_current_shared_and_watchdog(
    deploy_fixture: dict[str, object],
) -> None:
    old_release = _promote_fixture_to_existing_r6(deploy_fixture)
    before = _snapshot(*deploy_fixture["roots"])

    result = _run(deploy_fixture, "smoke")

    assert result.returncode == 2
    assert "ROLLBACK" in result.stderr
    assert _snapshot(*deploy_fixture["roots"]) == before
    live = Path(deploy_fixture["live"])
    assert (live / "current").resolve() == old_release
    watchdog = Path(deploy_fixture["bin"]) / "hermes_watchdog.py"
    assert watchdog.read_text(encoding="utf-8") == "#!/usr/bin/env python3\nprint('old watchdog')\n"
    assert stat.S_IMODE(watchdog.stat().st_mode) == 0o640


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
    staged = hermes_home / "bin/run_daily.sh"
    staged.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    _git(hermes_home, "add", "-f", str(staged.relative_to(hermes_home)))

    result = _run(deploy_fixture)

    assert result.returncode == 4
    assert "pre-staged deploy-allowlist" in result.stderr
    events = Path(deploy_fixture["events"]).read_text(encoding="utf-8").splitlines()
    assert events == ["runtime-prep", "guard"]
    assert not list(Path(deploy_fixture["backup"]).glob("hermes_escape_top.predeploy_backup_*"))
