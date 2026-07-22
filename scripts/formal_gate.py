#!/usr/bin/env python3
"""Run one pre-registered formal IS-selection/OOS-PBO experiment.

Usage:
    PYTHONPATH=src python3 scripts/formal_gate.py research/experiments/<id>.json

The manifest must already be committed and clean. Candidate names and gate
thresholds cannot be overridden on the command line, and a final result can be
written only once for each experiment id.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Mapping

import pandas as pd

from hermes_escape_top.core.backtest.formal_gate import (
    ExperimentManifest,
    FormalGateError,
    evaluate_formal_gate,
)
from hermes_escape_top.core.backtest.harness import cpcv_splits
from hermes_escape_top.core.backtest.validation import walk_forward_splits


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "building" / "reports" / "formal_gate"
GATE_CODE_PATHS = (
    ":(glob)src/hermes_escape_top/**/*.py",
    "src/hermes_escape_top/config/config.json",
    "src/pyproject.toml",
    "scripts/backtest_flag_sweep.py",
    "scripts/flag_gate.py",
    "scripts/formal_gate.py",
    "scripts/execution_timing_sensitivity.py",
    "scripts/build_current_baseline.py",
    "building/reports/current_baseline/CURRENT_BASELINE_CONFIG.json",
)
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from backtest_flag_sweep import assess_artifact_freshness, build_config  # noqa: E402


def require_preregistered_manifest(repo_root: Path, manifest_path: Path) -> str:
    repo = repo_root.resolve()
    path = manifest_path.resolve()
    try:
        relative = path.relative_to(repo)
    except ValueError as exc:
        raise FormalGateError("experiment manifest must live inside the repository") from exc

    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative.as_posix()],
        cwd=repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if tracked.returncode != 0:
        raise FormalGateError("experiment manifest must be tracked before the gate runs")
    clean = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", relative.as_posix()],
        cwd=repo,
        check=False,
    )
    if clean.returncode != 0:
        raise FormalGateError("experiment manifest must be committed and clean before the gate runs")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def require_gate_code_clean(repo_root: Path) -> str:
    repo = repo_root.resolve()
    dirty = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", *GATE_CODE_PATHS],
        cwd=repo,
        check=False,
    )
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "--", *GATE_CODE_PATHS],
        cwd=repo,
        text=True,
    ).strip()
    if dirty.returncode != 0 or untracked:
        raise FormalGateError("gate code and config must be committed before the gate runs")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def load_manifest(path: Path) -> ExperimentManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalGateError(f"cannot read experiment manifest: {path}") from exc
    return ExperimentManifest.from_dict(raw)


def _atomic_replace_text(path: Path, text: str) -> None:
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


def _atomic_replace_bytes(path: Path, payload: bytes) -> None:
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


def write_result_once(
    output_dir: Path,
    result: Mapping[str, Any],
    report: str,
    *,
    artifact_sources: Mapping[str, Path] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / ".formal_gate.lock").open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            result_path = output_dir / "result.json"
            if result_path.exists():
                raise FormalGateError(f"experiment already has a final result: {result_path}")
            for relative, source in sorted((artifact_sources or {}).items()):
                destination = (output_dir / relative).resolve()
                try:
                    destination.relative_to(output_dir.resolve())
                except ValueError as exc:
                    raise FormalGateError(f"artifact snapshot escapes output directory: {relative}") from exc
                try:
                    payload = source.read_bytes()
                except OSError as exc:
                    raise FormalGateError(f"cannot snapshot gate artifact: {source}") from exc
                destination.parent.mkdir(parents=True, exist_ok=True)
                _atomic_replace_bytes(destination, payload)
            _atomic_replace_text(output_dir / "REPORT.md", report)
            _atomic_replace_text(result_path, json.dumps(result, indent=2, sort_keys=True, default=str) + "\n")
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _load_equity(path: Path) -> pd.Series:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalGateError(f"cannot read equity artifact: {path}") from exc
    return pd.Series({pd.Timestamp(day): float(value) for day, value in raw.items()}).sort_index()


def load_artifacts(
    repo_root: Path,
    manifest: ExperimentManifest,
) -> tuple[dict[str, pd.Series], dict[str, dict[str, Any]], list[str]]:
    artifact_dir = (repo_root / manifest.artifacts_dir).resolve()
    try:
        artifact_dir.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise FormalGateError("artifacts_dir resolves outside the repository") from exc

    equities: dict[str, pd.Series] = {}
    statuses: dict[str, dict[str, Any]] = {}
    missing_equities: list[str] = []
    gate_start: str | None = None
    gate_end: str | None = None
    baseline_metrics = artifact_dir / f"{manifest.baseline}.json"
    try:
        baseline_cached = json.loads(baseline_metrics.read_text(encoding="utf-8"))
        if isinstance(baseline_cached.get("start"), str) and isinstance(
            baseline_cached.get("end"), str
        ):
            gate_start = baseline_cached["start"]
            gate_end = baseline_cached["end"]
    except (OSError, json.JSONDecodeError):
        pass
    for variant in manifest.variants:
        equity_path = artifact_dir / f"{variant}_equity.json"
        metrics_path = artifact_dir / f"{variant}.json"
        if not equity_path.exists():
            missing_equities.append(variant)
        else:
            equities[variant] = _load_equity(equity_path)
        if not metrics_path.exists():
            statuses[variant] = {"status": "STALE", "mismatches": ["metrics_artifact"]}
            continue
        try:
            cached = json.loads(metrics_path.read_text(encoding="utf-8"))
            cfg = build_config(variant)
            window = {"start": gate_start, "end": gate_end} if gate_start and gate_end else {}
            status = dict(assess_artifact_freshness(variant, cached, cfg, **window))
            if manifest.turnover_objective is not None:
                metric = str(manifest.turnover_objective["metric"])
                if metric == "route_set_turnover":
                    value = (cached.get("route_set_turnover") or {}).get("total")
                else:
                    value = cached.get("turnover")
                status["turnover_evidence"] = {metric: value}
            statuses[variant] = status
        except (OSError, json.JSONDecodeError, SystemExit) as exc:
            statuses[variant] = {
                "status": "STALE",
                "mismatches": ["metrics_artifact_unusable"],
                "error": str(exc),
            }
    return equities, statuses, missing_equities


def artifact_snapshot_sources(repo_root: Path, manifest: ExperimentManifest) -> dict[str, Path]:
    artifact_dir = (repo_root / manifest.artifacts_dir).resolve()
    sources: dict[str, Path] = {}
    for variant in manifest.variants:
        for suffix in (".json", "_equity.json", "_legacy_close_equity.json"):
            source = artifact_dir / f"{variant}{suffix}"
            if source.exists():
                sources[f"artifacts/{source.name}"] = source
    return sources


def render_report(manifest: ExperimentManifest, result: Mapping[str, Any]) -> str:
    lines = [
        f"# Formal Gate: {manifest.experiment_id}",
        "",
        f"- Hypothesis: {manifest.hypothesis}",
        f"- Governance lane: `{manifest.governance_lane}`",
        f"- Manifest SHA256: `{manifest.manifest_sha256}`",
        f"- Candidate universe: `{', '.join(manifest.variants)}`",
        f"- Declared trials: {manifest.declared_trial_count}",
        f"- Verdict: **{result['verdict']}**",
        f"- Authorization: **{result['authorization']}**",
        "",
    ]
    if result["verdict"] == "BLOCKED":
        lines.append(f"Blocked variants: `{', '.join(result.get('blocked_variants', []))}`")
        return "\n".join(lines) + "\n"

    closing = (
        "This records performance impact only. A data-correctness migration remains NO_FLIP "
        "until its correctness evidence and baseline restatement receive explicit human approval."
        if manifest.governance_lane == "data_correctness_migration"
        else "A passing result is still a candidate result. Production remains unchanged until a human flip."
    )
    lines += [
        "| Check | Result |",
        "|---|---|",
    ]
    for name, passed in result["checks"].items():
        lines.append(f"| {name} | {'PASS' if passed else 'FAIL'} |")
    lines += [
        "",
        "| Validation | PBO | Target OOS delta | Folds |",
        "|---|---:|---:|---:|",
        f"| Walk-forward | {result['walk_forward']['pbo']:.4f} | {result['walk_forward']['target_delta_vs_baseline']:+.6f} | {result['walk_forward']['n_folds']} |",
        f"| CPCV | {result['cpcv']['pbo']:.4f} | {result['cpcv']['target_delta_vs_baseline']:+.6f} | {result['cpcv']['n_folds']} |",
        "",
        f"Target DSR: `{result['target']['dsr']:.6f}` using n_trials={result['target']['dsr_inputs']['n_trials']}, "
        f"skew={result['target']['dsr_inputs']['skew']:.6f}, kurtosis={result['target']['dsr_inputs']['kurtosis']:.6f}.",
    ]
    turnover = result.get("turnover_objective")
    if isinstance(turnover, Mapping):
        lines += [
            "",
            (
                "Turnover objective: "
                f"`{turnover.get('metric')}` baseline `{float(turnover.get('baseline')):.6f}`, "
                f"target `{float(turnover.get('target')):.6f}`, "
                f"delta `{float(turnover.get('delta_vs_baseline')):+.6f}`, "
                f"required `<= {float(turnover.get('max_delta_vs_baseline')):+.6f}`."
            ),
        ]
    lines += ["", closing]
    return "\n".join(lines) + "\n"


def run(manifest_path: Path, *, repo_root: Path = REPO_ROOT, output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    manifest_commit = require_preregistered_manifest(repo_root, manifest_path)
    code_commit = require_gate_code_clean(repo_root)
    if code_commit != manifest_commit:
        raise FormalGateError("manifest and gate code must resolve to the same commit")
    manifest = load_manifest(manifest_path)
    output_dir = output_root / manifest.experiment_id
    if (output_dir / "result.json").exists():
        raise FormalGateError(f"experiment already has a final result: {output_dir / 'result.json'}")

    equities, statuses, missing_equities = load_artifacts(repo_root, manifest)
    if missing_equities:
        return {
            "schema": "hermes-formal-gate-result-v1",
            "experiment_id": manifest.experiment_id,
            "governance_lane": manifest.governance_lane,
            "manifest_sha256": manifest.manifest_sha256,
            "manifest_git_commit": manifest_commit,
            "verdict": "BLOCKED",
            "authorization": "NO_FLIP",
            "blocked_variants": missing_equities,
            "reason": "missing equity artifacts",
        }

    dates = list(equities[manifest.baseline].index)
    wf = walk_forward_splits([day.isoformat() for day in dates], **dict(manifest.walk_forward))
    cpcv = cpcv_splits(len(dates), **dict(manifest.cpcv))
    result = evaluate_formal_gate(
        manifest,
        equities,
        statuses,
        walk_forward_splits=wf,
        cpcv_splits=cpcv,
    )
    result["manifest_git_commit"] = manifest_commit
    if result["verdict"] != "BLOCKED":
        final_manifest_commit = require_preregistered_manifest(repo_root, manifest_path)
        final_code_commit = require_gate_code_clean(repo_root)
        final_manifest = load_manifest(manifest_path)
        if (
            final_manifest_commit != manifest_commit
            or final_code_commit != code_commit
            or final_manifest.manifest_sha256 != manifest.manifest_sha256
        ):
            raise FormalGateError("manifest or gate code changed while the formal gate was running")
        write_result_once(
            output_dir,
            result,
            render_report(manifest, result),
            artifact_sources=artifact_snapshot_sources(repo_root, manifest),
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run(args.manifest)
    except FormalGateError as exc:
        print(f"FORMAL_GATE_ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    if result["verdict"] == "BLOCKED":
        return 2
    if result["verdict"] == "REJECTED":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
