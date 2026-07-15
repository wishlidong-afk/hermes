#!/usr/bin/env python3
"""Offline AAII/NAAIM failure drill using the production source runner."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from hermes_escape_top.core.data.external_sources.aaii import (  # noqa: E402
    AaiiSentimentImportAdapter,
    aaii_sentiment_spec,
)
from hermes_escape_top.core.data.external_sources.ledger import (  # noqa: E402
    latest_source_run,
)
from hermes_escape_top.core.data.external_sources.naaim import (  # noqa: E402
    NaaimExposureImportAdapter,
    naaim_exposure_spec,
)
from hermes_escape_top.core.data.external_sources.runner import (  # noqa: E402
    run_external_source_refresh,
)


@dataclass(frozen=True)
class _SourceFixture:
    source_id: str
    write_seed: Callable[[Path], None]
    build_spec: Callable[[Path], Any]
    build_import_adapter: Callable[[Path, Path], Any]
    old_file: str
    wrong_file: str
    recovery_file: str


class _FetchFailureAdapter:
    def fetch_raw(self) -> dict[str, Any]:
        raise RuntimeError("simulated primary endpoint failure")


def run_drill(work_dir: Path) -> dict[str, Any]:
    root = Path(work_dir)
    root.mkdir(parents=True, exist_ok=True)
    scenarios: list[dict[str, Any]] = []
    sequence = 0
    for fixture in (_aaii_fixture(), _naaim_fixture()):
        for scenario in (
            "primary_fetch_failure",
            "older_official_file",
            "wrong_issue_file",
            "manual_import_recovery",
        ):
            sequence += 1
            scenarios.append(
                _run_scenario(
                    root,
                    fixture,
                    scenario,
                    now=datetime(2026, 7, 15, 1, sequence, tzinfo=timezone.utc),
                )
            )
    return {
        "schema": "hermes-external-source-failure-drill-v1",
        "status": "PASS" if all(row["passed"] for row in scenarios) else "FAIL",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "network_used": False,
        "live_data_touched": False,
        "scenarios": scenarios,
    }


def _run_scenario(
    root: Path,
    fixture: _SourceFixture,
    scenario: str,
    *,
    now: datetime,
) -> dict[str, Any]:
    scenario_root = root / fixture.source_id / scenario
    target = scenario_root / "soft_history" / f"{fixture.source_id}.csv"
    archive = scenario_root / "archive"
    fixture.write_seed(target)
    before = target.read_bytes()
    before_latest = _latest_date(target)
    import_path = scenario_root / f"{scenario}.csv"

    expected_status: str
    if scenario == "primary_fetch_failure":
        adapter: Any = _FetchFailureAdapter()
        expected_status = "FETCH_ERROR"
    else:
        content = {
            "older_official_file": fixture.old_file,
            "wrong_issue_file": fixture.wrong_file,
            "manual_import_recovery": fixture.recovery_file,
        }[scenario]
        import_path.parent.mkdir(parents=True, exist_ok=True)
        import_path.write_text(content, encoding="utf-8")
        adapter = fixture.build_import_adapter(target, import_path)
        expected_status = _expected_status(fixture.source_id, scenario)

    run = run_external_source_refresh(
        fixture.build_spec(target),
        adapter,
        archive,
        now=now,
    )
    after = target.read_bytes()
    after_latest = _latest_date(target)
    ledger = latest_source_run(archive, fixture.source_id) or {}
    failure_scenario = scenario != "manual_import_recovery"
    canonical_unchanged = after == before
    canonical_advanced = bool(
        before_latest and after_latest and after_latest > before_latest
    )
    ledger_written = (
        ledger.get("run_id") == run.run_id
        and ledger.get("status") == run.status
    )
    passed = (
        run.status == expected_status
        and ledger_written
        and (canonical_unchanged if failure_scenario else canonical_advanced)
        and (failure_scenario or bool(run.canonical_sha256 and run.official_file_sha256))
    )
    return {
        "source_id": fixture.source_id,
        "scenario": scenario,
        "expected_status": expected_status,
        "actual_status": run.status,
        "canonical_unchanged": canonical_unchanged,
        "canonical_advanced": canonical_advanced,
        "before_latest_as_of": before_latest,
        "after_latest_as_of": after_latest,
        "ledger_written": ledger_written,
        "canonical_sha256": run.canonical_sha256,
        "official_file_sha256": run.official_file_sha256,
        "error_type": run.error_type,
        "error_message": run.error_message,
        "passed": passed,
    }


def _expected_status(source_id: str, scenario: str) -> str:
    if scenario == "manual_import_recovery":
        return "OK"
    if scenario == "older_official_file" and source_id == "naaim_exposure":
        return "VALIDATION_ERROR"
    return "PARSE_ERROR"


def _aaii_fixture() -> _SourceFixture:
    return _SourceFixture(
        source_id="aaii_sentiment",
        write_seed=_write_aaii_seed,
        build_spec=lambda target: aaii_sentiment_spec(target_path=target, min_rows=2),
        build_import_adapter=lambda target, import_path: AaiiSentimentImportAdapter(
            seed_path=target,
            import_path=import_path,
            percentile_window=4,
            min_periods=1,
        ),
        old_file=(
            "Reported,Bullish,Neutral,Bearish,Bull-Bear\n"
            "2026-06-25,44.9,25.0,30.1,14.8\n"
        ),
        wrong_file=(
            "Reported,Bullish,Neutral,Bearish,Bull-Bear\n"
            "2026-07-09,120.0,0.0,-20.0,140.0\n"
        ),
        recovery_file=(
            "Reported,Bullish,Neutral,Bearish,Bull-Bear\n"
            "2026-07-09,38.2,28.0,33.8,4.4\n"
        ),
    )


def _naaim_fixture() -> _SourceFixture:
    return _SourceFixture(
        source_id="naaim_exposure",
        write_seed=_write_naaim_seed,
        build_spec=lambda target: naaim_exposure_spec(target_path=target, min_rows=1),
        build_import_adapter=lambda _target, import_path: NaaimExposureImportAdapter(
            import_path=import_path,
            percentile_window=4,
            min_periods=1,
        ),
        old_file="Date,NAAIM Number\n2026-06-24,85.0\n",
        wrong_file="Date,NAAIM Number\n2026-07-08,999.0\n",
        recovery_file=(
            "Date,NAAIM Number\n"
            "2026-06-24,85.0\n"
            "2026-07-01,90.0\n"
            "2026-07-08,95.0\n"
        ),
    )


def _write_aaii_seed(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            _aaii_row("2026-06-25", 0.40, 0.35),
            _aaii_row("2026-07-02", 0.38, 0.34),
        ]
    ).to_csv(path, index=False)


def _aaii_row(day: str, bull: float, bear: float) -> dict[str, Any]:
    return {
        "date": day,
        "publish_date": day,
        "aaii_bull": bull,
        "aaii_bear": bear,
        "aaii_bull_bear_spread": round(bull - bear, 3),
        "aaii_bull_pctl": 50.0,
        "aaii_spread_pctl": 50.0,
    }


def _write_naaim_seed(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "date": "2026-06-24",
                "publish_date": "2026-06-25",
                "naaim_exposure": 85.0,
                "naaim_pctl": 50.0,
                "is_proxy": False,
            },
            {
                "date": "2026-07-01",
                "publish_date": "2026-07-02",
                "naaim_exposure": 90.0,
                "naaim_pctl": 100.0,
                "is_proxy": False,
            },
        ]
    ).to_csv(path, index=False)


def _latest_date(path: Path) -> str | None:
    frame = pd.read_csv(path)
    values = pd.to_datetime(frame["date"], errors="coerce").dropna()
    return None if values.empty else values.max().date().isoformat()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="optional JSON evidence path")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="hermes-external-drill-") as temp_dir:
        report = run_drill(Path(temp_dir))
    if args.output:
        _atomic_write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
