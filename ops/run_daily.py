#!/usr/bin/env python3
"""run_daily.py — M4 live: runs the package engine as a module (single source of truth).

There is no loose run_daily_package.py copy any more. _discover_runtime_paths in
the package walks UP to locate hermes_escape_top, so `python -m` resolves the
engine — and every subprocess's PYTHONPATH — from escape-top/ no matter how deep
the file sits. Before 2026-06-17 this ran a shallower loose copy that silently
drifted from the package (the B incident: daily ran 4-day-stale orchestration).
Rollback: scripts/run_daily.py.bak_prepkg_<stamp> (+ restore the loose copy).

`--deploy-verify` traverses the same package entry as a manual preview without
committing state or stamping the scheduled-run receipt.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ESCAPE_TOP = Path(__file__).resolve().parent.parent  # .../escape-top, holds hermes_escape_top/
PYTHON = sys.executable


def build_command(args):
    deploy_verify = "--deploy-verify" in args
    forwarded = [arg for arg in args if arg != "--deploy-verify"]
    cmd = [PYTHON, "-m", "hermes_escape_top.scripts.run_daily_package", "--live"]
    if deploy_verify:
        if forwarded:
            raise SystemExit("--deploy-verify does not accept additional arguments")
        cmd.extend(["--run-type", "manual_rerun"])
    else:
        cmd.append("--commit-state")
        cmd.extend(forwarded)
    return cmd


def build_alpaca_flow_command():
    return [
        PYTHON,
        "-m",
        "hermes_escape_top.core.data.alpaca_flow",
        "--as-of",
        "latest",
    ]


def _alpaca_status_path(env):
    if env.get("HERMES_DATA_DIR"):
        return Path(env["HERMES_DATA_DIR"]) / "data" / "archive" / "alpaca_daily_flow_status.json"
    return ESCAPE_TOP / "hermes_escape_top" / "data" / "archive" / "alpaca_daily_flow_status.json"


def write_alpaca_flow_status(payload, *, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "status": str(payload.get("status") or "ERROR"),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "as_of": payload.get("as_of"),
        "source": payload.get("source"),
        "error": payload.get("error"),
    }
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return record


if __name__ == "__main__":
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ESCAPE_TOP) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    cmd = build_command(sys.argv[1:])
    r = subprocess.run(cmd, cwd=str(ESCAPE_TOP), env=env)
    if r.returncode == 0 and "--deploy-verify" not in sys.argv[1:]:
        flow = subprocess.run(
            build_alpaca_flow_command(),
            cwd=str(ESCAPE_TOP),
            env=env,
            capture_output=True,
            text=True,
        )
        if flow.returncode == 0:
            print(f"[alpaca-flow] {flow.stdout.strip()}")
            try:
                summary = json.loads((flow.stdout or "").strip().splitlines()[-1])
            except Exception:
                summary = {}
            try:
                write_alpaca_flow_status(
                    {"status": "OK", **summary},
                    path=_alpaca_status_path(env),
                )
            except Exception as exc:
                print(f"[alpaca-flow] WARNING: could not persist auxiliary status: {exc!r}")
        else:
            detail = (flow.stderr or flow.stdout or "unknown error").strip()
            print(f"[alpaca-flow] WARNING: refresh failed; keeping prior cache: {detail[-500:]}")
            try:
                write_alpaca_flow_status(
                    {"status": "ERROR", "error": detail[-500:]},
                    path=_alpaca_status_path(env),
                )
            except Exception as exc:
                print(f"[alpaca-flow] WARNING: could not persist auxiliary status: {exc!r}")
    sys.exit(r.returncode)
