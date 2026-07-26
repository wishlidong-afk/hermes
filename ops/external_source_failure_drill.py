#!/usr/bin/env python3
"""Offline AAII/NAAIM/CBOE failure drill using the production source runner."""
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
from hermes_escape_top.core.data.external_sources.cboe_indices import (  # noqa: E402
    CBOE_INDEX_DEFINITIONS,
    CboeVolatilityIndexAdapter,
    cboe_index_spec,
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
    for scenario in (
        "historical_ohlc_revision_new_tail",
        "historical_close_revision",
        "missing_existing_date",
        "tail_witness_mismatch",
        "unchanged_history",
    ):
        sequence += 1
        scenarios.append(_run_cboe_scenario(root, scenario, sequence=sequence))
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


def _expected_status(_source_id: str, scenario: str) -> str:
    if scenario == "manual_import_recovery":
        return "OK"
    return "PARSE_ERROR"


def _run_cboe_scenario(
    root: Path,
    scenario: str,
    *,
    sequence: int,
) -> dict[str, Any]:
    scenario_root = root / "cboe_vix3m" / scenario
    target = scenario_root / "history" / "_VIX3M.csv"
    archive = scenario_root / "archive"
    _write_cboe_seed(target)
    before = target.read_bytes()
    before_frame = pd.read_csv(target)
    before_latest = _latest_date(target)
    csv_text, witness_date, witness_close = _cboe_scenario_input(scenario)
    definition = CBOE_INDEX_DEFINITIONS["cboe_vix3m"]
    adapter = CboeVolatilityIndexAdapter(
        definition,
        fetch_text=lambda _url: csv_text,
        fetch_witness=lambda *_args: _cboe_witness(witness_date, witness_close),
        now=datetime(2026, 7, 25, 22, sequence, tzinfo=timezone.utc),
        seed_path=target,
    )

    run = run_external_source_refresh(
        cboe_index_spec(definition, target, min_rows=1),
        adapter,
        archive,
        now=datetime(2026, 7, 25, 23, sequence, tzinfo=timezone.utc),
    )
    after = target.read_bytes()
    after_frame = pd.read_csv(target)
    after_latest = _latest_date(target)
    ledger = latest_source_run(archive, definition.source_id) or {}
    validation = (
        json.loads(Path(run.validation_path).read_text(encoding="utf-8"))
        if run.validation_path
        else {}
    )
    revision = validation.get("history_revision") or {}
    certified_after = after_frame[
        after_frame["date"].astype(str).isin(before_frame["date"].astype(str))
    ].reset_index(drop=True)
    certified_rows_preserved = certified_after.to_dict(
        orient="records"
    ) == before_frame.reset_index(drop=True).to_dict(orient="records")
    canonical_unchanged = after == before
    canonical_advanced = bool(
        before_latest and after_latest and after_latest > before_latest
    )
    ledger_written = (
        ledger.get("run_id") == run.run_id
        and ledger.get("status") == run.status
    )

    if scenario == "historical_ohlc_revision_new_tail":
        passed = bool(
            run.status == "OK"
            and canonical_advanced
            and certified_rows_preserved
            and run.history_revision_status == "QUARANTINED"
            and run.history_revision_count == 3
        )
    elif scenario == "unchanged_history":
        passed = bool(
            run.status == "OK"
            and run.promotion_status == "UNCHANGED"
            and canonical_unchanged
            and run.history_revision_status == "NONE"
        )
    else:
        passed = run.status == "VALIDATION_ERROR" and canonical_unchanged
    passed = bool(passed and ledger_written)
    return {
        "source_id": definition.source_id,
        "scenario": scenario,
        "expected_status": (
            "OK"
            if scenario in {"historical_ohlc_revision_new_tail", "unchanged_history"}
            else "VALIDATION_ERROR"
        ),
        "actual_status": run.status,
        "promotion_status": run.promotion_status,
        "canonical_unchanged": canonical_unchanged,
        "canonical_advanced": canonical_advanced,
        "certified_rows_preserved": certified_rows_preserved,
        "before_latest_as_of": before_latest,
        "after_latest_as_of": after_latest,
        "ledger_written": ledger_written,
        "canonical_sha256": run.canonical_sha256,
        "official_file_sha256": run.official_file_sha256,
        "history_revision_status": run.history_revision_status,
        "history_revision_count": run.history_revision_count,
        "history_revision_fingerprint": run.history_revision_fingerprint,
        "revision_evidence": revision,
        "error_type": run.error_type,
        "error_message": run.error_message,
        "passed": passed,
    }


def _cboe_scenario_input(scenario: str) -> tuple[str, str, float]:
    seed_rows = (
        "10/30/2013,15.13,15.13,15.13,15.13\n"
        "07/22/2026,18,18,18,18\n"
    )
    cases = {
        "historical_ohlc_revision_new_tail": (
            "10/30/2013,14.68,15.45,14.68,15.13\n"
            "07/22/2026,18,18,18,18\n"
            "07/23/2026,19,19,19,19\n"
            "07/24/2026,20,20,20,20\n",
            "2026-07-24",
            20.0,
        ),
        "historical_close_revision": (
            "10/30/2013,15.14,15.14,15.14,15.14\n"
            "07/22/2026,18,18,18,18\n"
            "07/23/2026,19,19,19,19\n",
            "2026-07-23",
            19.0,
        ),
        "missing_existing_date": (
            "07/22/2026,18,18,18,18\n"
            "07/23/2026,19,19,19,19\n",
            "2026-07-23",
            19.0,
        ),
        "tail_witness_mismatch": (
            seed_rows + "07/23/2026,19,19,19,19\n",
            "2026-07-23",
            99.0,
        ),
        "unchanged_history": (seed_rows, "2026-07-22", 18.0),
    }
    body, witness_date, witness_close = cases[scenario]
    return "DATE,OPEN,HIGH,LOW,CLOSE\n" + body, witness_date, witness_close


def _cboe_witness(day: str, close: float) -> pd.DataFrame:
    return pd.DataFrame(
        {"Close": [close]},
        index=pd.DatetimeIndex([pd.Timestamp(day)], name="Date"),
    )


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
        build_import_adapter=lambda target, import_path: NaaimExposureImportAdapter(
            import_path=import_path,
            seed_path=target,
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


def _write_cboe_seed(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "date,open,high,low,close,adj_close,volume\n"
        "2013-10-30,15.13,15.13,15.13,15.13,15.13,0\n"
        "2026-07-22,18,18,18,18,18,0\n",
        encoding="utf-8",
    )


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
