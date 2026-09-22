"""Diagnostic comparisons, separate from admission and decision identity."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

import pandas as pd

from ..data.market_admission import MarketAdmissionSession
from ..data.market_witness import (
    ALPACA_WITNESS_SOURCE,
    YAHOO_CANDIDATE_SOURCE,
    normalize_alpaca_witness_bar,
    normalize_yahoo_candidate_bar,
)
from ..safe_io import atomic_write_json


def _hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(value), sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


class MarketComparisonRecorder:
    """Capture an adjacent-run comparison without influencing admission."""

    def __init__(self, archive: Path, session: MarketAdmissionSession):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", session.operation_id):
            raise ValueError("invalid market comparison operation id")
        self.path = archive / "market_comparisons" / session.operation_id / f"{uuid4().hex}.json"
        self.session = session
        prior = archive / "market_admission_latest.json"
        raw = prior.read_bytes() if prior.exists() else None
        self.previous = json.loads(raw) if raw is not None else None
        self.previous_sha = hashlib.sha256(raw).hexdigest() if raw is not None else None
        self.previous_is_earlier = False
        if self.previous:
            try:
                before = datetime.fromisoformat(self.previous["generated_at"])
                now = datetime.fromisoformat(session.generated_at)
                self.previous_is_earlier = (
                    before.utcoffset() is not None and now.utcoffset() is not None
                    and before <= now and not self.previous.get("run_error")
                )
            except (KeyError, TypeError, ValueError):
                pass
        self.rows: list[dict[str, Any]] = []

    def capture(self, symbol: str, candidate: pd.DataFrame, rows: list[dict[str, Any]]) -> None:
        captured_at = datetime.now(timezone.utc).isoformat()
        witnesses = {
            str(bar.get("t") or "")[:10]: bar
            for bar in self.session.witness_bars.get(symbol.upper(), [])
            if isinstance(bar, Mapping)
        }
        previous = {
            (row.get("symbol"), row.get("date")): row
            for row in (self.previous or {}).get("rows", [])
            if self.previous_is_earlier
            and row.get("admitted") is False and row.get("blocking") is not False
        }
        for (_, values), row in zip(candidate.iterrows(), rows, strict=True):
            if "candidate_sha256" not in row or symbol.upper() == "BTC-USD":
                continue
            local = {"date": row["date"], **{
                name.lower(): values.get(name)
                for name in ("Open", "High", "Low", "Close", "Volume")
            }}
            candidate_bar = normalize_yahoo_candidate_bar(local)
            witness_bar = normalize_alpaca_witness_bar(witnesses.get(row["date"]))
            prior = previous.get((row["symbol"], row["date"]))
            self.rows.append({
                **row,
                "captured_at": captured_at,
                "outcome": (
                    "MATCH_AFTER_REJECTION"
                    if prior is not None and row["status"] == "MATCH"
                    else row["status"]
                ),
                "previous_rejection": prior,
                "raw_comparison": {
                    "candidate": {"source": YAHOO_CANDIDATE_SOURCE, "auto_adjust": False,
                                  "bar": candidate_bar,
                                  "sha256": _hash(candidate_bar) if candidate_bar else None},
                    "witness": {"source": ALPACA_WITNESS_SOURCE, "feed": "sip",
                                "adjustment": "raw", "timeframe": "1Day",
                                "bar": witness_bar,
                                "sha256": _hash(witness_bar) if witness_bar else None},
                },
            })

    def write(self, admission: Mapping[str, Any]) -> None:
        report = {
            "schema_version": "hermes-market-comparisons-v1",
            "evidence_role": "DIAGNOSTIC_ONLY_NOT_ADMISSION",
            "selection_policy": "PREVIOUS_ADMISSION_SNAPSHOT_SAME_SYMBOL_DATE",
            "comparison_id": self.path.stem,
            "operation_id": self.session.operation_id,
            "generated_at": self.session.generated_at,
            "requested_start": self.session.requested_start,
            "requested_end": self.session.requested_end,
            "completed_through": self.session.completed_through,
            "equity_witness": admission.get("equity_witness"),
            "admission_payload_sha256": _hash(admission),
            "previous_admission_sha256": self.previous_sha,
            "previous_admission_payload_sha256": _hash(self.previous) if self.previous else None,
            "previous_admission": self.previous,
            "rows": self.rows,
        }
        atomic_write_json(self.path, report)
