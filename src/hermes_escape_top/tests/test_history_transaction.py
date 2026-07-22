from __future__ import annotations

import json
import os

import pytest

from hermes_escape_top.core.data.history_transaction import (
    HistoryPromotionTransaction,
    recover_history_transactions,
)


@pytest.mark.parametrize("operation_id", ["", ".", "..", "../escape", "nested/run"])
def test_operation_id_cannot_escape_transaction_journal(tmp_path, operation_id):
    history = tmp_path / "history"
    history.mkdir()

    with pytest.raises(ValueError, match="operation_id"):
        HistoryPromotionTransaction(
            history,
            allowed_roots=(history,),
            operation_id=operation_id,
        )


def test_startup_recovery_restores_every_target_after_partial_promotion(tmp_path):
    history = tmp_path / "history"
    history.mkdir()
    qqq = history / "QQQ.csv"
    spy = history / "SPY.csv"
    qqq.write_bytes(b"old-qqq\n")
    spy.write_bytes(b"old-spy\n")

    transaction = HistoryPromotionTransaction(
        history,
        allowed_roots=(history,),
        operation_id="crash-case",
    )
    transaction.stage_bytes(qqq, b"new-qqq\n")
    transaction.stage_bytes(spy, b"new-spy\n")
    transaction.prepare()

    manifest = json.loads(transaction.manifest_path.read_text(encoding="utf-8"))
    manifest["state"] = "PROMOTING"
    transaction.write_manifest(manifest)
    first = manifest["entries"][0]
    os.replace(first["staged_path"], first["target_path"])

    assert qqq.read_bytes() == b"new-qqq\n"
    assert spy.read_bytes() == b"old-spy\n"

    recovered = recover_history_transactions(history, allowed_roots=(history,))

    assert recovered == ["crash-case"]
    assert qqq.read_bytes() == b"old-qqq\n"
    assert spy.read_bytes() == b"old-spy\n"
    assert not transaction.transaction_dir.exists()


def test_committed_transaction_is_kept_during_startup_cleanup(tmp_path):
    history = tmp_path / "history"
    history.mkdir()
    qqq = history / "QQQ.csv"
    qqq.write_bytes(b"old\n")
    transaction = HistoryPromotionTransaction(
        history,
        allowed_roots=(history,),
        operation_id="committed-case",
    )
    transaction.stage_bytes(qqq, b"new\n")
    transaction.prepare()
    transaction.promote()
    transaction.mark_committed(cleanup=False)

    recovered = recover_history_transactions(history, allowed_roots=(history,))

    assert recovered == []
    assert qqq.read_bytes() == b"new\n"
    assert not transaction.transaction_dir.exists()


def test_startup_recovery_restores_tracked_evidence_with_history(tmp_path):
    history = tmp_path / "history"
    archive = tmp_path / "archive"
    history.mkdir()
    archive.mkdir()
    qqq = history / "QQQ.csv"
    evidence = archive / "market_admission_latest.json"
    qqq.write_bytes(b"old-history\n")
    evidence.write_bytes(b"old-evidence\n")
    transaction = HistoryPromotionTransaction(
        history,
        allowed_roots=(history, archive),
        operation_id="evidence-crash",
    )
    transaction.stage_bytes(qqq, b"new-history\n")
    transaction.track_path(evidence)
    transaction.prepare()

    manifest = json.loads(transaction.manifest_path.read_text(encoding="utf-8"))
    manifest["state"] = "PROMOTING"
    transaction.write_manifest(manifest)
    history_entry = next(entry for entry in manifest["entries"] if entry["promote"])
    os.replace(history_entry["staged_path"], history_entry["target_path"])
    evidence.write_bytes(b"new-evidence\n")

    recover_history_transactions(
        history,
        allowed_roots=(history, archive),
    )

    assert qqq.read_bytes() == b"old-history\n"
    assert evidence.read_bytes() == b"old-evidence\n"
