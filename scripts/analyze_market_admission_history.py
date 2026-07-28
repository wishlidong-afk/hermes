#!/usr/bin/env python3
"""Build a read-only reliability study from market-admission artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "hermes-market-admission-history-study-v1"
DEFAULT_PRICE_MATCH_PCT = 0.5
DEFERRED_STATUSES = {"DEFERRED_UNFINALIZED", "UNFINALIZED_SESSION"}


def load_artifacts(archive_dir: Path) -> list[dict[str, Any]]:
    archive = Path(archive_dir)
    artifacts: list[dict[str, Any]] = []
    for path in sorted(archive.glob("market_admission_*.json")):
        if path.name == "market_admission_latest.json":
            continue
        suffix = path.stem.removeprefix("market_admission_")
        try:
            datetime.strptime(suffix, "%Y-%m-%d")
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid market-admission artifact {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"market-admission artifact is not an object: {path}")
        row = dict(payload)
        row["artifact_date"] = suffix
        row["artifact_path"] = str(path)
        row["artifact_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        artifacts.append(row)
    return sorted(
        artifacts,
        key=lambda row: (
            str(row.get("artifact_date") or ""),
            str(row.get("generated_at") or ""),
        ),
    )


def analyze_artifacts(
    artifacts: Iterable[Mapping[str, Any]],
    *,
    target_sessions: int = 30,
) -> dict[str, Any]:
    if target_sessions <= 0:
        raise ValueError("target_sessions must be positive")
    ordered = sorted(
        (dict(row) for row in artifacts),
        key=lambda row: (
            str(row.get("artifact_date") or ""),
            str(row.get("generated_at") or ""),
        ),
    )
    first_by_session: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, artifact in enumerate(ordered):
        completed = str(artifact.get("completed_through") or "")[:10]
        if completed:
            first_by_session.setdefault(completed, (index, artifact))
    selected_sessions = sorted(first_by_session)[-target_sessions:]
    selected_set = set(selected_sessions)
    first_index = min(
        (first_by_session[day][0] for day in selected_sessions),
        default=0,
    )

    session_rows = [
        {
            "completed_through": day,
            "artifact_date": str(artifact.get("artifact_date") or ""),
            "status": str(artifact.get("status") or "UNKNOWN"),
            "admitted_rows": _integer(artifact.get("admitted_rows")),
            "rejected_rows": _integer(artifact.get("rejected_rows")),
            "deferred_rows": _integer(artifact.get("deferred_rows")),
        }
        for day, artifact in (
            (day, first_by_session[day][1]) for day in selected_sessions
        )
    ]
    blocked_sessions = sum(row["status"] == "BLOCKED" for row in session_rows)

    histories: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    deferred_keys: set[tuple[str, str, str]] = set()
    for artifact_index, artifact in enumerate(ordered[first_index:], start=first_index):
        artifact_date = str(artifact.get("artifact_date") or "")
        for raw in _artifact_rows(artifact):
            symbol = str(raw.get("symbol") or "")
            day = str(raw.get("date") or "")[:10]
            if not symbol or not day:
                continue
            event = dict(raw)
            event["artifact_index"] = artifact_index
            event["artifact_date"] = artifact_date
            histories[(symbol, day)].append(event)
            if str(event.get("status") or "") in DEFERRED_STATUSES or event.get("blocking") is False:
                deferred_keys.add((symbol, day, str(event.get("status") or "")))

    events: list[dict[str, Any]] = []
    for (symbol, day), history in sorted(histories.items()):
        if day not in selected_set:
            continue
        first_failure_index = next(
            (index for index, row in enumerate(history) if _is_blocking(row)),
            None,
        )
        if first_failure_index is None:
            continue
        failure = history[first_failure_index]
        later = history[first_failure_index + 1 :]
        recovery_row = next(
            (row for row in later if _is_admitted(row)),
            None,
        )
        recovered = recovery_row is not None
        runs_to_recovery = (
            int(recovery_row["artifact_index"]) - int(failure["artifact_index"])
            if recovery_row is not None
            else None
        )
        resolution = (
            "RECOVERED"
            if recovered
            else "UNRESOLVED_WITH_LATER_EVIDENCE"
            if later
            else "PENDING_NO_LATER_EVIDENCE"
        )
        event = {
            "symbol": symbol,
            "date": day,
            "first_artifact_date": failure.get("artifact_date"),
            "status": str(failure.get("status") or "UNKNOWN"),
            "close_diff_pct": _number(failure.get("close_diff_pct")),
            "max_ohlc_diff_pct": _number(failure.get("max_ohlc_diff_pct")),
            "volume_diff_pct": _number(failure.get("volume_diff_pct")),
            "price_evidence_status": failure.get("price_evidence_status"),
            "volume_evidence_status": failure.get("volume_evidence_status"),
            "resolution_status": resolution,
            "later_observations": len(later),
            "runs_to_recovery": runs_to_recovery,
            "recovered_artifact_date": (
                recovery_row.get("artifact_date")
                if recovery_row is not None
                else None
            ),
        }
        events.append(event)

    status_counts = Counter(event["status"] for event in events)
    symbol_rows: dict[str, dict[str, Any]] = {}
    for symbol in sorted({event["symbol"] for event in events}):
        rows = [event for event in events if event["symbol"] == symbol]
        symbol_rows[symbol] = {
            "events": len(rows),
            "volume_mismatches": sum(row["status"] == "VOLUME_MISMATCH" for row in rows),
            "price_mismatches": sum(row["status"] == "PRICE_MISMATCH" for row in rows),
            "recovered": sum(row["resolution_status"] == "RECOVERED" for row in rows),
            "pending": sum(
                row["resolution_status"] == "PENDING_NO_LATER_EVIDENCE"
                for row in rows
            ),
        }

    matured = [event for event in events if event["later_observations"] > 0]
    recovered = [event for event in matured if event["resolution_status"] == "RECOVERED"]
    pending = [
        event
        for event in events
        if event["resolution_status"] == "PENDING_NO_LATER_EVIDENCE"
    ]
    close_matched = sum(
        event["close_diff_pct"] is not None
        and event["close_diff_pct"] <= DEFAULT_PRICE_MATCH_PCT
        for event in events
    )
    available = len(selected_sessions)
    evidence_status = "SUFFICIENT" if available >= target_sessions else "INSUFFICIENT_EVIDENCE"
    policy_decision = (
        "REVIEW_ELIGIBLE"
        if evidence_status == "SUFFICIENT"
        else "HOLD_FAIL_CLOSED_POLICY"
    )
    source_artifacts = [
        {
            "artifact_date": row.get("artifact_date"),
            "path": (
                Path(str(row.get("artifact_path"))).name
                if row.get("artifact_path")
                else None
            ),
            "sha256": row.get("artifact_sha256"),
        }
        for row in ordered
    ]
    source_manifest_sha256 = hashlib.sha256(
        json.dumps(
            source_artifacts,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_status": evidence_status,
        "policy_decision": policy_decision,
        "source_evidence": {
            "artifact_manifest_sha256": source_manifest_sha256,
            "artifacts": source_artifacts,
        },
        "sample": {
            "target_sessions": target_sessions,
            "available_sessions": available,
            "artifact_count": len(ordered),
            "session_selection_policy": "FIRST_ARTIFACT_PER_COMPLETED_THROUGH",
            "start_completed_through": selected_sessions[0] if selected_sessions else None,
            "end_completed_through": selected_sessions[-1] if selected_sessions else None,
        },
        "session_summary": {
            "blocked_sessions": blocked_sessions,
            "ok_sessions": sum(row["status"] == "OK" for row in session_rows),
            "blocked_session_rate_pct": _percentage(blocked_sessions, available),
        },
        "blocking_summary": {
            "unique_events": len(events),
            "status_counts": dict(sorted(status_counts.items())),
            "matured_events": len(matured),
            "recovered_events": len(recovered),
            "matured_recovery_rate_pct": _percentage(len(recovered), len(matured)),
            "next_run_recoveries": sum(event["runs_to_recovery"] == 1 for event in recovered),
            "pending_events": len(pending),
            "close_within_match_band": close_matched,
            "deferred_rows_excluded": len(deferred_keys),
        },
        "sessions": session_rows,
        "symbols": symbol_rows,
        "events": events,
    }


def render_markdown(report: Mapping[str, Any], *, archive_dir: Path) -> str:
    sample = report.get("sample") or {}
    sessions = report.get("session_summary") or {}
    blocking = report.get("blocking_summary") or {}
    lines = [
        "# Market Admission Reliability Study",
        "",
        f"Generated: `{report.get('generated_at')}`",
        f"Evidence source: `{Path(archive_dir)}`",
        "",
        "> Read-only study. It does not fetch data, promote canonical rows, change thresholds, or alter live state.",
        "",
        "## Decision",
        "",
        f"- Evidence: **{report.get('evidence_status')}** "
        f"(`{sample.get('available_sessions')}/{sample.get('target_sessions')}` completed sessions).",
        f"- Policy: **{report.get('policy_decision')}**.",
        "- A threshold or source-role change is not authorized by this report.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Completed-session window | {sample.get('start_completed_through')}..{sample.get('end_completed_through')} |",
        f"| Admission artifacts | {sample.get('artifact_count')} |",
        f"| Session selection | {sample.get('session_selection_policy')} |",
        f"| Artifact manifest SHA-256 | `{(report.get('source_evidence') or {}).get('artifact_manifest_sha256')}` |",
        f"| Independent completed sessions | {sample.get('available_sessions')} |",
        f"| Blocked sessions | {sessions.get('blocked_sessions')} ({sessions.get('blocked_session_rate_pct')}%) |",
        f"| Unique blocking symbol/dates | {blocking.get('unique_events')} |",
        f"| Matured events with later evidence | {blocking.get('matured_events')} |",
        f"| Matured events recovered | {blocking.get('recovered_events')} ({blocking.get('matured_recovery_rate_pct')}%) |",
        f"| Recovered on next observed run | {blocking.get('next_run_recoveries')} |",
        f"| Pending with no later evidence | {blocking.get('pending_events')} |",
        f"| Blocking events with close inside 0.5% band | {blocking.get('close_within_match_band')} |",
        "",
        "## Blocking Events",
        "",
        "| Symbol | Session | First seen | Status | Close diff | Max OHLC diff | Volume diff | Resolution | Recovery run |",
        "|---|---|---|---|---:|---:|---:|---|---:|",
    ]
    for event in report.get("events") or []:
        lines.append(
            "| {symbol} | {date} | {first} | {status} | {close} | {ohlc} | {volume} | {resolution} | {runs} |".format(
                symbol=event.get("symbol"),
                date=event.get("date"),
                first=event.get("first_artifact_date"),
                status=event.get("status"),
                close=_format_pct(event.get("close_diff_pct")),
                ohlc=_format_pct(event.get("max_ohlc_diff_pct")),
                volume=_format_pct(event.get("volume_diff_pct")),
                resolution=event.get("resolution_status"),
                runs=event.get("runs_to_recovery") or "-",
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            _interpretation(report),
            "",
            "The next review gate remains 30 independent completed sessions. Before that gate, keep the existing fail-closed admission policy and collect third-source evidence only in shadow mode.",
            "",
        ]
    )
    return "\n".join(lines)


def _interpretation(report: Mapping[str, Any]) -> str:
    blocking = report.get("blocking_summary") or {}
    events = int(blocking.get("unique_events") or 0)
    matured = int(blocking.get("matured_events") or 0)
    recovered = int(blocking.get("recovered_events") or 0)
    close_matched = int(blocking.get("close_within_match_band") or 0)
    statements = []
    if matured and recovered == matured:
        statements.append(
            f"All {matured} blocking events with later evidence recovered; this is consistent with transient vendor finalization, but the sample is not yet sufficient for a policy change."
        )
    if events and close_matched == events:
        statements.append(
            f"All {events} blocking events retained a close inside the current 0.5% match band; the observed blocks came from volume or another OHLC field."
        )
    if not statements:
        statements.append("The available evidence does not yet establish a stable mismatch pattern.")
    return " ".join(statements)


def _artifact_rows(artifact: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = artifact.get("rows") or artifact.get("evidence") or []
    if not isinstance(rows, list):
        raise ValueError(
            f"market-admission rows are not a list: {artifact.get('artifact_path') or artifact.get('artifact_date')}"
        )
    return [row for row in rows if isinstance(row, Mapping)]


def _is_blocking(row: Mapping[str, Any]) -> bool:
    status = str(row.get("status") or "")
    return (
        row.get("admitted") is False
        and row.get("blocking") is not False
        and status not in DEFERRED_STATUSES
    )


def _is_admitted(row: Mapping[str, Any]) -> bool:
    return row.get("admitted") is True or str(row.get("status") or "") == "MATCH"


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _percentage(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100.0, 2)


def _format_pct(value: Any) -> str:
    number = _number(value)
    return "-" if number is None else f"{number:.4f}%"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--target-sessions", type=int, default=30)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    args = parser.parse_args()

    report = analyze_artifacts(
        load_artifacts(args.archive),
        target_sessions=args.target_sessions,
    )
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if args.output_json:
        _write(args.output_json, encoded)
    if args.output_md:
        _write(args.output_md, render_markdown(report, archive_dir=args.archive))
    if not args.output_json and not args.output_md:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
