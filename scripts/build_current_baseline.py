#!/usr/bin/env python3
"""Build one provenance-bound current-deployment full-backtest source."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Mapping

import pandas as pd

from hermes_escape_top.config import CONFIG_PATH, load_config
from hermes_escape_top.core.backtest.run_full import FullBacktestReport, run_full_backtest
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.governance.live_config_policy import (
    file_sha256,
    load_policy,
    semantic_sha256,
    validate_configs,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "building" / "reports" / "current_baseline"
DEFAULT_START = "2018-01-01"
ENABLE = ["costs"]
APPROVED_LIVE_POLICY_PATH = (
    REPO_ROOT / "src" / "hermes_escape_top" / "governance" / "approved_live_config.json"
)
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from backtest_flag_sweep import cache_evidence, normalize_gate_config  # noqa: E402


def research_worktree_clean(repo_root: Path = REPO_ROOT) -> bool:
    paths = [
        ":(glob)src/hermes_escape_top/**/*.py",
        "src/hermes_escape_top/config/config.json",
        "src/pyproject.toml",
        "scripts/backtest_flag_sweep.py",
        "scripts/formal_gate.py",
        "scripts/execution_timing_sensitivity.py",
        "scripts/build_current_baseline.py",
        "src/hermes_escape_top/governance/approved_live_config.json",
    ]
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", *paths],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0 and not result.stdout.strip()


def build_baseline_config(config_path: Path) -> dict[str, Any]:
    repo_config = load_config(CONFIG_PATH)
    live_config = load_config(config_path)
    validate_configs(repo_config, live_config, load_policy(APPROVED_LIVE_POLICY_PATH))
    return normalize_gate_config(live_config)


def build_baseline_config_authorization(
    config_path: Path,
    normalized_config: Mapping[str, Any],
) -> dict[str, Any]:
    repo_config = json.loads(Path(CONFIG_PATH).read_text(encoding="utf-8"))
    live_config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    policy = load_policy(APPROVED_LIVE_POLICY_PATH)
    validate_configs(repo_config, live_config, policy)
    raw_features = live_config.get("features") or {}
    normalized_features = normalized_config.get("features") or {}
    normalization: dict[str, dict[str, Any]] = {}
    for key in sorted(set(raw_features) | set(normalized_features)):
        raw_value = raw_features.get(key, "<missing>")
        normalized_value = normalized_features.get(key, "<missing>")
        if raw_value == normalized_value:
            continue
        reason = (
            "byte-identical replay acceleration only"
            if key == "use_indicator_cache"
            else "explicit default for gate replay schema"
        )
        normalization[str(key)] = {
            "raw": raw_value,
            "normalized": normalized_value,
            "reason": reason,
        }
    return {
        "schema_version": "current-baseline-config-authorization-v1",
        "config_source": str(Path(config_path).resolve()),
        "raw_live_config_sha256": file_sha256(Path(config_path)),
        "raw_live_config_semantic_sha256": semantic_sha256(live_config),
        "repo_config_semantic_sha256": semantic_sha256(repo_config),
        "policy_sha256": file_sha256(APPROVED_LIVE_POLICY_PATH),
        "policy_schema_version": str(policy.get("schema_version") or ""),
        "policy_approved_live_semantic_sha256": str(
            policy.get("live_config_semantic_sha256") or ""
        ),
        "policy_approved_repo_semantic_sha256": str(
            policy.get("repo_config_semantic_sha256") or ""
        ),
        "normalized_config_semantic_sha256": semantic_sha256(normalized_config),
        "approved_feature_diff": policy.get("approved_feature_diff") or {},
        "normalization": normalization,
    }


def latest_history_date(frame: pd.DataFrame) -> str:
    if frame is None or frame.empty or "Close" not in frame:
        raise ValueError("QQQ history has no usable close rows")
    close = pd.to_numeric(frame["Close"], errors="coerce").dropna()
    if close.empty:
        raise ValueError("QQQ history has no usable close rows")
    return pd.Timestamp(close.index[-1]).date().isoformat()


def build_source_payload(
    report: FullBacktestReport,
    evidence: Mapping[str, Any],
    *,
    config_source: str,
    config_authorization: Mapping[str, Any],
) -> dict[str, Any]:
    payload = report.to_dict()
    if payload.get("data_manifest_id") != evidence.get("manifest_id"):
        raise ValueError("backtest report manifest does not match frozen provenance manifest")
    if payload.get("requested_start") != evidence.get("start") or payload.get("requested_end") != evidence.get("end"):
        raise ValueError("backtest report window does not match frozen provenance window")
    if config_authorization.get("schema_version") != "current-baseline-config-authorization-v1":
        raise ValueError("baseline config authorization is missing or invalid")
    payload.update(
        {
            "evidence_schema": "current-baseline-source-v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "config_source": str(config_source),
            "config_snapshot": "CURRENT_BASELINE_CONFIG.json",
            "config_authorization": dict(config_authorization),
            "provenance": {**dict(evidence), "worktree_clean": True},
            "authorization": "NO_CONFIG_FLIP",
        }
    )
    return payload


def render_summary(payload: Mapping[str, Any]) -> str:
    simulation = payload.get("simulation", {})
    metrics = simulation.get("metrics", {})
    provenance = payload.get("provenance", {})
    config_authorization = payload.get("config_authorization", {})
    return "\n".join(
        [
            "# Current Baseline Full Source",
            "",
            f"Evidence schema: `{payload.get('evidence_schema')}`",
            f"Commit: `{provenance.get('git_commit')}`",
            f"Window: `{payload.get('effective_start')}` to `{payload.get('effective_end')}`",
            f"Requested window: `{payload.get('requested_start')}` to `{payload.get('requested_end')}`",
            f"Manifest: `{payload.get('data_manifest_id')}`",
            f"Config source: `{payload.get('config_source')}`",
            f"Config snapshot: `{payload.get('config_snapshot')}`",
            f"Approved live semantic SHA256: `{config_authorization.get('raw_live_config_semantic_sha256')}`",
            f"Policy SHA256: `{config_authorization.get('policy_sha256')}`",
            f"Normalized replay config SHA256: `{config_authorization.get('normalized_config_semantic_sha256')}`",
            "Authorization: `NO_CONFIG_FLIP`",
            "",
            "| Metric | Legacy close source |",
            "|---|---:|",
            f"| Final value | {_money(metrics.get('final_value'))} |",
            f"| CAGR | {_pct(metrics.get('cagr'))} |",
            f"| MaxDD | {_pct(metrics.get('max_drawdown'))} |",
            f"| Sharpe | {_num(metrics.get('sharpe'))} |",
            f"| Sortino | {_num(metrics.get('sortino'))} |",
            f"| Turnover | {_num(simulation.get('turnover'))} |",
            "",
            "> This file is the provenance-bound source for execution-timing repricing. Legacy close is not the headline baseline.",
            "",
        ]
    )


def run(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    config_path: Path = CONFIG_PATH,
    start: str = DEFAULT_START,
    end: str | None = None,
) -> dict[str, Any]:
    if not research_worktree_clean():
        raise RuntimeError("research code and config must be committed and clean before baseline generation")
    cfg = build_baseline_config(config_path)
    config_authorization = build_baseline_config_authorization(config_path, cfg)
    store = LocalStore(cfg)
    resolved_end = str(end or latest_history_date(store.load_history("QQQ")))
    evidence = cache_evidence("baseline", cfg, start=str(start), end=resolved_end, enable=ENABLE)
    report = run_full_backtest(start=str(start), end=resolved_end, cfg=cfg, enable=set(ENABLE))
    payload = build_source_payload(
        report,
        evidence,
        config_source=str(config_path.resolve()),
        config_authorization=config_authorization,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    source_path = output_dir / "CURRENT_BASELINE_FULL.json"
    source_archive_path = output_dir / "CURRENT_BASELINE_FULL.json.gz"
    summary_path = output_dir / "CURRENT_BASELINE_FULL.md"
    equity_path = output_dir / "CURRENT_BASELINE_EQUITY.json"
    config_snapshot_path = output_dir / "CURRENT_BASELINE_CONFIG.json"
    _atomic_write_json(config_snapshot_path, cfg)
    _atomic_write_json(source_path, payload)
    _atomic_write_bytes(source_archive_path, deterministic_gzip(source_path.read_bytes()))
    _atomic_write_json(equity_path, payload.get("simulation", {}).get("equity_curve", {}))
    _atomic_write_text(summary_path, render_summary(payload))
    print(f"Current baseline source: {source_path}")
    print(f"Current baseline source archive: {source_archive_path}")
    print(f"Current baseline summary: {summary_path}")
    print(f"Current baseline config: {config_snapshot_path}")
    print(f"Commit: {payload['provenance']['git_commit']}")
    print(f"Window: {payload['requested_start']} to {payload['requested_end']}")
    return payload


def _atomic_write_json(path: Path, payload: Any) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _atomic_write_text(path: Path, text: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def deterministic_gzip(payload: bytes) -> bytes:
    return gzip.compress(payload, compresslevel=9, mtime=0)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _num(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "n/a"


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "n/a"


def _money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a clean, provenance-bound current baseline source")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=None)
    args = parser.parse_args()
    run(output_dir=args.output_dir, config_path=args.config, start=args.start, end=args.end)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
