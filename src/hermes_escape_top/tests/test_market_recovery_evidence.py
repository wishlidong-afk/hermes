import hashlib
import json

import pandas as pd
import pytest

from hermes_escape_top.core.data.market_admission import MarketAdmissionSession
from hermes_escape_top.scripts.backfill_history import backfill


def _run(tmp_path, *, witness_volume=1000, operation="a" * 32, day="2026-09-18",
         enabled=True, missing_witness=False, malformed_witness=False):
    frame = pd.DataFrame(
        {"Open": [99.0], "High": [101.0], "Low": [98.0],
         "Close": [100.0], "Volume": [1000.0]},
        index=pd.to_datetime([day]),
    )
    session = MarketAdmissionSession(
        enabled=enabled,
        witness_bars={} if missing_witness else {"SMH": [{"t": day + "T04:00:00Z", "o": 99.0,
                               "h": 101.0, "l": 98.0, "c": 100.0,
                               "v": witness_volume}]},
        operation_id=operation,
        generated_at="2026-09-21T00:00:00+00:00",
        requested_start="2026-09-17", requested_end="2026-09-22",
        completed_through="2026-09-21",
    )
    if malformed_witness:
        session.witness_bars["SMH"].append(None)
    backfill(["SMH"], start=day, end="2026-09-22",
             store_dir=tmp_path / "history", downloader=lambda *_: frame.copy(),
             repair_overlap_days=5, admission_session=session,
             admission_archive=tmp_path / "archive")
    return session


def test_diagnostics_ignore_non_mapping_witness_entries_like_admission(tmp_path):
    session = _run(tmp_path, malformed_witness=True)
    assert session.payload()["status"] == "OK"
    report = json.loads(next((tmp_path / "archive/market_comparisons" / ("a" * 32)).glob("*.json")).read_text())
    assert report["rows"][0]["raw_comparison"]["witness"]["bar"]["close"] == 100.0


def test_recovered_comparison_is_saved_without_changing_admission_payload(tmp_path):
    _run(tmp_path, witness_volume=2000)
    previous = (tmp_path / "archive/market_admission_latest.json").read_bytes()
    session = _run(tmp_path, operation="b" * 32)
    artifact = next((tmp_path / "archive/market_comparisons" / ("b" * 32)).glob("*.json"))
    report = json.loads(artifact.read_text())
    assert report["previous_admission_sha256"] == hashlib.sha256(previous).hexdigest()
    assert report["previous_admission"]["operation_id"] == "a" * 32
    row = report["rows"][0]
    assert row["outcome"] == "MATCH_AFTER_REJECTION"
    assert row["previous_rejection"]["raw_comparison"]["witness"]["bar"]["volume"] == 2000
    assert row["raw_comparison"]["witness"]["bar"]["volume"] == 1000
    assert row["raw_comparison"]["candidate"]["bar"]["volume"] == 1000
    payload = session.payload()
    assert "raw_comparison" not in payload["rows"][0]
    assert json.loads((tmp_path / "archive/market_admission_latest.json").read_text()) == payload
    assert pd.read_csv(tmp_path / "history/SMH.csv")["close"].tolist() == [100.0]


def test_repeated_operation_preserves_each_batch_comparison_evidence(tmp_path):
    _run(tmp_path)
    directory = tmp_path / "archive/market_comparisons" / ("a" * 32)
    path = next(directory.glob("*.json"))
    original = path.read_bytes()
    _run(tmp_path, witness_volume=2000)
    assert len(list(directory.glob("*.json"))) == 2
    assert path.read_bytes() == original


def test_future_previous_snapshot_cannot_claim_recovery(tmp_path):
    _run(tmp_path, witness_volume=2000)
    path = tmp_path / "archive/market_admission_latest.json"
    previous = json.loads(path.read_text())
    previous["generated_at"] = "2026-09-22T00:00:00+00:00"
    path.write_text(json.dumps(previous))
    _run(tmp_path, operation="b" * 32)
    report = json.loads(next((tmp_path / "archive/market_comparisons" / ("b" * 32)).glob("*.json")).read_text())
    assert report["rows"][0]["outcome"] == "MATCH"
    assert report["rows"][0]["previous_rejection"] is None


@pytest.mark.parametrize("mode", ["still_rejected", "different_date", "missing_witness"])
def test_no_false_recovery_for_rejected_missing_or_other_date(tmp_path, mode):
    _run(tmp_path, witness_volume=2000)
    _run(tmp_path, operation="b" * 32,
         witness_volume=2000 if mode == "still_rejected" else 1000,
         day="2026-09-21" if mode == "different_date" else "2026-09-18",
         missing_witness=mode == "missing_witness")
    report = json.loads(next((tmp_path / "archive/market_comparisons" / ("b" * 32)).glob("*.json")).read_text())
    row = report["rows"][0]
    assert row["outcome"] != "MATCH_AFTER_REJECTION"
    if mode == "different_date":
        assert row["previous_rejection"] is None
    elif mode == "missing_witness":
        assert row["raw_comparison"]["witness"]["bar"] is None
        assert row["admitted"] is False
    else:
        assert row["admitted"] is False


def test_stale_third_source_does_not_affect_capture_or_admission(tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "market_admission_third_source_latest.json").write_text(
        json.dumps({"status": "OK", "operation_id": "stale", "rows": [
            {"symbol": "SMH", "date": "2026-09-18", "third_source_support": "YAHOO_CANDIDATE"}
        ]})
    )
    session = _run(tmp_path, witness_volume=2000)
    assert session.payload()["status"] == "BLOCKED"
    report = json.loads(next((archive / "market_comparisons" / ("a" * 32)).glob("*.json")).read_text())
    assert report["rows"][0]["outcome"] == "VOLUME_MISMATCH"
    assert "third_source" not in json.dumps(report)


def test_disabled_admission_does_not_create_diagnostics(tmp_path):
    _run(tmp_path, enabled=False)
    assert not (tmp_path / "archive/market_comparisons").exists()


def test_commit_failure_rolls_back_comparison_artifact_and_history(tmp_path, monkeypatch):
    from hermes_escape_top.core.data.history_transaction import HistoryPromotionTransaction

    _run(tmp_path)
    history = tmp_path / "history/SMH.csv"
    original = history.read_bytes()
    old_reports = {p: p.read_bytes() for p in (tmp_path / "archive/market_comparisons").rglob("*.json")}

    def fail_commit(_self):
        assert list((tmp_path / "archive/market_comparisons" / ("b" * 32)).glob("*.json"))
        raise RuntimeError("injected commit failure")

    monkeypatch.setattr(HistoryPromotionTransaction, "mark_committed", fail_commit)
    with pytest.raises(RuntimeError, match="injected commit failure"):
        _run(tmp_path, operation="b" * 32)
    assert history.read_bytes() == original
    assert {p: p.read_bytes() for p in (tmp_path / "archive/market_comparisons").rglob("*.json")} == old_reports
    assert json.loads((tmp_path / "archive/market_admission_latest.json").read_text())["status"] == "ERROR"


def test_raw_hashes_and_admission_binding_are_independently_recomputable(tmp_path):
    session = _run(tmp_path)
    report = json.loads(next((tmp_path / "archive/market_comparisons" / ("a" * 32)).glob("*.json")).read_text())

    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()

    assert digest(session.payload()) == report["admission_payload_sha256"]
    for source in ("candidate", "witness"):
        evidence = report["rows"][0]["raw_comparison"][source]
        assert digest(evidence["bar"]) == evidence["sha256"]
