"""Deployment previews must be private, cached-only, and fail on network use."""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_escape_top.scripts import run_daily_package as daily


@pytest.fixture
def preview(monkeypatch, tmp_path):
    container = tmp_path / "hermes-deploy-verify.test"
    container.mkdir(mode=0o700)
    root = container / "runtime"
    root.mkdir(mode=0o700)
    (container / ".deploy-verify").write_text("hermes-deploy-verify-v1\n")
    monkeypatch.setenv("HERMES_DATA_DIR", str(root))
    monkeypatch.setenv("HERMES_DEPLOY_VERIFY_ROOT", str(root))
    monkeypatch.chdir(root)
    args = SimpleNamespace(deploy_verify=True, live=True, run_type="manual_rerun",
                           commit_state=False, skip_refresh=True)
    return root, args


def test_deploy_parser_accepts_explicit_offline_mode():
    args = daily._build_daily_parser().parse_args(["--deploy-verify", "--live", "--skip-refresh"])
    assert args.deploy_verify and args.skip_refresh


@pytest.mark.parametrize("change", ["scheduled", "commit", "refresh", "shadow", "missing_root", "wrong_root", "marker"])
def test_invalid_preview_refuses_before_any_pipeline_work(preview, monkeypatch, change):
    root, args = preview
    if change == "scheduled":
        args.run_type = "scheduled"
    elif change == "commit":
        args.commit_state = True
    elif change == "refresh":
        args.skip_refresh = False
    elif change == "shadow":
        args.live = False
    elif change == "missing_root":
        monkeypatch.delenv("HERMES_DEPLOY_VERIFY_ROOT")
    elif change == "wrong_root":
        monkeypatch.setenv("HERMES_DATA_DIR", str(root.parent))
    else:
        (root.parent / ".deploy-verify").unlink()
    with pytest.raises(ValueError, match="deploy verification"):
        with daily._deploy_verification_guard(args):
            pytest.fail("invalid deployment preview reached pipeline work")
    assert not (root / "data").exists()


def test_preview_rejects_a_different_working_directory(preview, monkeypatch):
    root, args = preview
    monkeypatch.chdir(root.parent)
    with pytest.raises(ValueError, match="deploy verification"):
        with daily._deploy_verification_guard(args):
            pytest.fail("preview accepted a different working directory")
    assert not (root / "data").exists()


@pytest.mark.parametrize("transport", ["connect", "connect_ex", "dns", "subprocess", "udp", "connection"])
def test_swallowed_network_or_child_attempt_still_fails_preview(preview, transport):
    _, args = preview
    with pytest.raises(RuntimeError, match="deploy verification forbids"):
        with daily._deploy_verification_guard(args):
            try:
                if transport == "dns":
                    socket.getaddrinfo("example.invalid", 443)
                elif transport == "subprocess":
                    subprocess.run(["curl", "https://example.invalid"], check=False)
                elif transport == "udp":
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
                        connection.sendto(b"forbidden", ("127.0.0.1", 7497))
                elif transport == "connection":
                    socket.create_connection(("127.0.0.1", 7497))
                else:
                    with socket.socket() as connection:
                        getattr(connection, transport)(("127.0.0.1", 7497))
            except RuntimeError:
                pass


def test_preview_score_explicitly_disables_both_broker_readers(monkeypatch):
    calls = []
    monkeypatch.setattr(daily.pipeline, "_score_pipeline_locked", lambda *a, **kw: calls.append(kw) or {})
    daily.run_score_pipeline("2026-05-29", _lease=object(), include_ibkr=False)
    assert calls[0]["include_ibkr"] is False


@pytest.mark.parametrize("unsafe", ["outside", "shell", "executable", "environment"])
def test_private_copy_allowlist_cannot_start_another_command(preview, tmp_path, unsafe):
    root, args = preview
    source = root / "source"
    source.write_bytes(b"private input")
    command = ["/bin/cp", "-c", str(source), str(root / "copy")]
    kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
    if unsafe == "outside":
        command[3] = str(tmp_path / "outside")
    elif unsafe == "shell":
        kwargs["shell"] = True
    elif unsafe == "executable":
        kwargs["executable"] = "/bin/sh"
    else:
        kwargs["env"] = dict(os.environ)
    with pytest.raises(RuntimeError, match="deploy verification forbids"):
        with daily._deploy_verification_guard(args):
            subprocess.Popen(command, **kwargs)
    assert not (root / "copy").exists()
    assert not (tmp_path / "outside").exists()


@pytest.mark.parametrize("stream_name", ["stdout", "stderr", "inherit", "missing"])
def test_private_copy_refuses_uncontrolled_output(preview, tmp_path, stream_name):
    root, args = preview
    source = root / "source"
    source.write_bytes(b"private input")
    outside = tmp_path / "outside-output"
    outside.write_bytes(b"untouched\n")
    with outside.open("ab") as stream:
        kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
        if stream_name in {"stdout", "stderr"}:
            kwargs[stream_name] = stream
        elif stream_name == "inherit":
            kwargs["stdout"] = None
        else:
            kwargs = {}
        with pytest.raises(RuntimeError, match="deploy verification forbids"):
            with daily._deploy_verification_guard(args):
                subprocess.run(["/bin/cp", "-c", str(source), str(root / "copy")], check=False, **kwargs)
    assert not (root / "copy").exists()
    assert outside.read_bytes() == b"untouched\n"


def test_optional_cpu_probe_is_disabled_without_starting_a_child(preview, monkeypatch):
    _, args = preview
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("CPU probe started a child"))
    with daily._deploy_verification_guard(args):
        with pytest.raises(FileNotFoundError, match="optional CPU probe disabled"):
            subprocess.run("lscpu", capture_output=True, text=True, check=False)


def test_ordinary_runs_do_not_install_deployment_guards(monkeypatch):
    connect, popen = socket.socket.connect, subprocess.Popen
    monkeypatch.setattr(daily, "load_config", lambda: pytest.fail("ordinary mode loaded verification config"))
    with daily._deploy_verification_guard(SimpleNamespace(deploy_verify=False)):
        assert socket.socket.connect is connect and subprocess.Popen is popen


@pytest.mark.parametrize("path_kind", ["absolute", "absolute_parent", "symlink", "legacy_escape"])
def test_preview_rejects_paths_outside_private_container(preview, monkeypatch, tmp_path, path_kind):
    root, args = preview
    config = daily.load_config()
    if path_kind == "absolute":
        config["paths"]["archive_dir"] = str(tmp_path / "outside")
    elif path_kind == "absolute_parent":
        config["paths"]["archive_dir"] = str(root.parent / ".." / "outside")
    elif path_kind == "legacy_escape":
        config["paths"]["legacy_history_dir"] = "../../outside"
    else:
        (root / "data").symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setattr(daily, "load_config", lambda: config)
    with pytest.raises(ValueError, match="deploy verification"):
        with daily._deploy_verification_guard(args):
            pytest.fail("unsafe path reached pipeline")


def test_real_shell_and_package_preview_commit_only_private_artifacts(tmp_path, isolated_data_dir):
    repo = Path(__file__).resolve().parents[3]
    home = tmp_path / "home"
    base = home / ".hermes/skills/investment/escape-top"
    package = base / "hermes_escape_top"

    def excluded(directory, _names):
        names = {"tests", "__pycache__"}
        if Path(directory) == repo / "src/hermes_escape_top":
            names.add("data")
        return names

    shutil.copytree(repo / "src/hermes_escape_top", package, ignore=excluded)
    shutil.copytree(isolated_data_dir / "data", package / "data")
    (base / "scripts").mkdir()
    shutil.copy2(repo / "ops/run_daily.py", base / "scripts/run_daily.py")
    (package / "RUNTIME_LOCK_SHA256").write_text("fixture-lock\n")
    runtime = base / "runtime/fixture-lock"
    runtime.mkdir(parents=True)
    (runtime / ".venv").symlink_to(Path(sys.prefix), target_is_directory=True)
    archive = package / "data/archive"
    archive.mkdir(exist_ok=True)
    (archive / "audit_log.jsonl").write_text('{"original":"scheduled audit sentinel"}\n')
    (archive / "run_receipt.json").write_text('{"status":"OK","original":true}\n')
    (package / "data/state.json").write_text('{"original":"state sentinel"}\n')
    before = {str(path.relative_to(package)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
              for path in package.rglob("*") if path.is_file()}
    observed = tmp_path / "observed"
    entry = home / ".hermes/bin/run_daily.sh"
    entry.parent.mkdir(parents=True)
    entry.write_text("#!/bin/bash\nset -e\n"
                     f"if ! bash {shlex.quote(str(repo / 'ops/run_daily.sh'))} \"$@\"; then cat \"$HERMES_RUN_LOG\" >&2; exit 1; fi\n"
                     f"cp -R \"$HERMES_DATA_DIR\" {shlex.quote(str(observed))}\n")
    entry.chmod(0o755)
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    result = subprocess.run(
        ["bash", str(repo / "ops/verify_live.sh")],
        env={**os.environ, "HOME": str(home), "TMPDIR": str(temporary),
             "HERMES_VERIFY_TEST_MODE": "0", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "verify_live PASS" in result.stdout
    captured = observed / "data/archive"
    row = json.loads((captured / "audit_log.jsonl").read_text().splitlines()[-1])["payload"]
    assert row["run_type"] == "manual_rerun"
    assert row["ibkr"]["source"] == "disabled"
    assert row["execution_sync"]["status"] == "SKIPPED"
    assert not (observed / "data/state.json").exists()
    assert json.loads((captured / "run_receipt.json").read_text()) == {"status": "OK", "original": True}
    runs = [json.loads(path.read_text()) for path in (captured / ".score_run_transactions/runs").glob("*/manifest.json")]
    assert any(run["status"] == "COMMITTED" and len(run["artifacts"]) == 7 for run in runs)
    assert not (captured / ".score_run_transactions/active.json").exists()
    assert (captured / "NEXT5_unlock_status.md").is_file()
    after = {str(path.relative_to(package)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
             for path in package.rglob("*") if path.is_file()}
    assert after == before
    assert not list(temporary.glob("hermes-deploy-verify.*"))
