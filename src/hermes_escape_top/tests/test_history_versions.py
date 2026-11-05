import json
from pathlib import Path

import pandas as pd
import pytest

from hermes_escape_top.scripts.backfill_history import backfill


def _frame(close=100.0):
    return pd.DataFrame(
        {"Open": [99.0], "High": [106.0], "Low": [98.0],
         "Close": [close], "Adj Close": [close], "Volume": [1000.0]},
        index=pd.to_datetime(["2026-09-21"]),
    )


def _run(history: Path, close=100.0):
    return backfill(
        ["SMH"], start="2026-09-21", end="2026-09-23",
        store_dir=history, repair_overlap_days=5,
        downloader=lambda *_: _frame(close),
    )


def _versions(history):
    return history.parent / ".history_versions" / history.name


def test_committed_backfill_preserves_complete_old_and_new_canonical(tmp_path):
    history = tmp_path / "history"
    _run(history)
    before = (history / "SMH.csv").read_bytes()
    _run(history, 105.0)
    after = (history / "SMH.csv").read_bytes()
    assert before != after
    indexes = list((_versions(history) / "batches").glob("*.json"))
    assert len(indexes) == 2, "committed versions must outlive transaction cleanup"

    from hermes_escape_top.core.reporting.history_versions import restore_history_version

    index = next(p for p in indexes if json.loads(p.read_text())["files"][0]["before_sha256"])
    restore_history_version(history, index.stem, "SMH", "before", tmp_path / "old.csv")
    restore_history_version(history, index.stem, "SMH", "after", tmp_path / "new.csv")
    assert (tmp_path / "old.csv").read_bytes() == before
    assert (tmp_path / "new.csv").read_bytes() == after
    assert (history / "SMH.csv").read_bytes() == after
    assert not list((history / ".history_transactions").iterdir())


def test_version_archive_deduplicates_unchanged_bytes(tmp_path):
    history = tmp_path / "history"
    _run(history)
    first_index = next((_versions(history) / "batches").glob("*.json"))
    original = first_index.read_bytes()
    _run(history)
    assert first_index.read_bytes() == original
    assert len(list((_versions(history) / "blobs").glob("*.csv"))) == 1
    indexes = [json.loads(p.read_text()) for p in (_versions(history) / "batches").glob("*.json")]
    unchanged = next(row["files"][0] for row in indexes if row["files"][0]["change"] == "UNCHANGED")
    assert unchanged["before_sha256"] == unchanged["after_sha256"]


def test_committed_blobs_are_read_only(tmp_path):
    import stat

    history = tmp_path / "history"
    _run(history)
    blob = next((_versions(history) / "blobs").glob("*.csv"))
    assert stat.S_IMODE(blob.stat().st_mode) == 0o444


def test_versions_do_not_enter_canonical_market_manifest(tmp_path):
    from hermes_escape_top.core.data.manifest import freeze_manifest

    history = tmp_path / "history"
    _run(history)
    assert set(freeze_manifest(history).entries) == {"SMH.csv"}


def test_archive_symlink_cannot_put_versions_back_inside_canonical_history(tmp_path):
    history = tmp_path / "history"
    history.mkdir()
    parent = tmp_path / ".history_versions"
    parent.mkdir()
    (parent / "history").symlink_to(history, target_is_directory=True)
    with pytest.raises(ValueError, match="canonical history"):
        _run(history)
    assert not list(history.iterdir())


def test_wrong_evidence_role_cannot_be_restored(tmp_path):
    from hermes_escape_top.core.reporting.history_versions import restore_history_version

    history = tmp_path / "history"
    _run(history)
    index = next((_versions(history) / "batches").glob("*.json"))
    payload = json.loads(index.read_text())
    payload["evidence_role"] = "UNRELATED_EVIDENCE"
    index.chmod(0o600)
    index.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="index"):
        restore_history_version(history, index.stem, "SMH", "after", tmp_path / "offline.csv")
    assert not (tmp_path / "offline.csv").exists()


@pytest.mark.parametrize("field", ["Open", "High", "Low", "Close", "Adj Close", "Volume"])
def test_each_canonical_field_revision_has_exact_before_and_after(tmp_path, field):
    from hermes_escape_top.core.reporting.history_versions import restore_history_version

    history = tmp_path / "history"
    _run(history)
    before = (history / "SMH.csv").read_bytes()
    revised = _frame()
    revised.loc[:, field] += 1.0
    backfill(["SMH"], start="2026-09-21", end="2026-09-23",
             store_dir=history, repair_overlap_days=5, downloader=lambda *_: revised.copy())
    index = next(p for p in (_versions(history) / "batches").glob("*.json")
                 if json.loads(p.read_text())["files"][0]["change"] == "CHANGED")
    restore_history_version(history, index.stem, "SMH", "before", tmp_path / "before.csv")
    restore_history_version(history, index.stem, "SMH", "after", tmp_path / "after.csv")
    assert (tmp_path / "before.csv").read_bytes() == before
    assert (tmp_path / "after.csv").read_bytes() == (history / "SMH.csv").read_bytes()
    assert (tmp_path / "after.csv").read_bytes() != before


def test_versions_include_history_outside_the_download_window_and_btc(tmp_path):
    from hermes_escape_top.core.reporting.history_versions import restore_history_version

    history = tmp_path / "history"
    older = _frame()
    older.index = pd.to_datetime(["2026-09-18"])
    backfill(["BTC-USD"], start="2026-09-18", end="2026-09-23", store_dir=history,
             downloader=lambda *_: pd.concat([older, _frame()]))
    canonical = next(history.glob("*.csv"))
    before = canonical.read_bytes()
    backfill(["BTC-USD"], start="2026-09-21", end="2026-09-23", store_dir=history,
             repair_overlap_days=1, downloader=lambda *_: _frame(105.0))
    index = next(p for p in (_versions(history) / "batches").glob("*.json")
                 if json.loads(p.read_text())["files"][0]["change"] == "CHANGED")
    restore_history_version(history, index.stem, "BTC-USD", "before", tmp_path / "before.csv")
    restore_history_version(history, index.stem, "BTC-USD", "after", tmp_path / "after.csv")
    assert (tmp_path / "before.csv").read_bytes() == before
    assert (tmp_path / "after.csv").read_bytes() == canonical.read_bytes()
    assert pd.read_csv(tmp_path / "after.csv")["date"].tolist() == ["2026-09-18", "2026-09-21"]


def test_missing_witness_creates_no_claim_of_a_promoted_version(tmp_path):
    from hermes_escape_top.core.data.market_admission import MarketAdmissionSession

    history = tmp_path / "history"
    session = MarketAdmissionSession(enabled=True, witness_bars={})
    result = backfill(["SMH"], start="2026-09-21", end="2026-09-23", store_dir=history,
                      downloader=lambda *_: _frame(), admission_session=session,
                      admission_archive=tmp_path / "archive")
    assert not result["SMH"].updated
    assert not (history / "SMH.csv").exists()
    assert not list((_versions(history) / "batches").glob("*.json"))
    assert session.payload()["status"] == "BLOCKED"


@pytest.mark.parametrize("step", ["prepare", "promote", "seal", "mark_committed"])
def test_transaction_failure_restores_canonical_and_all_version_artifacts(tmp_path, monkeypatch, step):
    from hermes_escape_top.core.data.history_transaction import HistoryPromotionTransaction
    from hermes_escape_top.core.reporting.history_versions import HistoryVersionRecorder

    history = tmp_path / "history"
    _run(history)
    original = (history / "SMH.csv").read_bytes()
    versions = _versions(history)
    artifacts = {p: p.read_bytes() for p in versions.rglob("*") if p.is_file()}
    owner = HistoryVersionRecorder if step == "seal" else HistoryPromotionTransaction
    method = getattr(owner, step)

    def fail(transaction):
        if step != "mark_committed":
            method(transaction)
        raise OSError("injected version transaction failure")

    monkeypatch.setattr(owner, step, fail)
    with pytest.raises(OSError, match="injected version transaction failure"):
        _run(history, 105.0)
    assert (history / "SMH.csv").read_bytes() == original
    assert {p: p.read_bytes() for p in versions.rglob("*") if p.is_file()} == artifacts


def test_incomplete_promotion_cannot_be_restored_and_startup_removes_its_index(tmp_path):
    from hermes_escape_top.core.data.history_transaction import (
        HistoryPromotionTransaction, recover_history_transactions,
    )
    from hermes_escape_top.core.reporting.history_versions import (
        HistoryVersionRecorder, restore_history_version,
    )

    history = tmp_path / "history"
    _run(history)
    target = history / "SMH.csv"
    before = target.read_bytes()
    transaction = HistoryPromotionTransaction(history, allowed_roots=(history, _versions(history)))
    recorder = HistoryVersionRecorder(transaction)
    transaction.stage_bytes(target, before + b"2026-09-22,1,1,1,1,1,1\n")
    recorder.capture("SMH", target, before + b"2026-09-22,1,1,1,1,1,1\n", source_symbol="SMH")
    recorder.stage_index()
    transaction.prepare()
    transaction.promote()
    with pytest.raises(RuntimeError, match="not committed"):
        restore_history_version(history, recorder.batch_id, "SMH", "after", tmp_path / "offline.csv")
    assert not (tmp_path / "offline.csv").exists()
    assert recover_history_transactions(history, allowed_roots=(history, _versions(history))) == [transaction.operation_id]
    assert target.read_bytes() == before
    assert not recorder.path.exists()


@pytest.mark.parametrize("failure", ["missing_blob", "corrupt_blob", "missing_before", "canonical", "existing"])
def test_restore_fails_closed_without_writing_on_invalid_request(tmp_path, failure):
    from hermes_escape_top.core.reporting.history_versions import restore_history_version

    history = tmp_path / "history"
    _run(history)
    index = next((_versions(history) / "batches").glob("*.json"))
    payload = json.loads(index.read_text())
    blob = _versions(history) / "blobs" / f"{payload['files'][0]['after_sha256']}.csv"
    output = tmp_path / "offline.csv"
    version = "after"
    if failure == "missing_blob":
        blob.unlink()
    elif failure == "corrupt_blob":
        blob.chmod(0o600)
        blob.write_bytes(b"corrupt")
    elif failure == "missing_before":
        version = "before"
    elif failure == "canonical":
        output = history / "other.csv"
    else:
        output.write_bytes(b"already exists")
    with pytest.raises((ValueError, RuntimeError, FileNotFoundError)):
        restore_history_version(history, index.stem, "SMH", version, output)
    if failure == "existing":
        assert output.read_bytes() == b"already exists"
    else:
        assert not output.exists()
