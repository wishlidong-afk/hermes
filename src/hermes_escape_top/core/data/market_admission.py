from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from uuid import uuid4

import pandas as pd

from .alpaca_flow import DATA_URL, load_alpaca_credentials
from .coinbase_witness import (
    COINBASE_CANDLES_URL,
    COINBASE_SOURCE,
    compare_btc_spot_close,
    fetch_coinbase_daily_bar_range,
    latest_completed_utc_day,
)
from .external_sources.clock import timestamp_to_shanghai_date
from .market_witness import (
    ALPACA_WITNESS_SOURCE,
    compare_market_bar,
    fetch_alpaca_daily_bar_range,
    is_alpaca_supported_symbol,
    normalize_alpaca_witness_bar,
)
from .market_clock import latest_completed_us_market_session
from .store import safe_symbol


_ALPACA_PROVENANCE_FIELDS = (
    "schema_version",
    "source",
    "source_url",
    "timeframe",
    "feed",
    "adjustment",
    "fetched_at",
    "requested_start",
    "requested_end",
    "completed_through",
    "symbols",
    "symbol_count",
    "bar_count",
    "normalized_bars_sha256",
)


@dataclass
class MarketAdmissionSession:
    enabled: bool
    witness_bars: Mapping[str, Iterable[Mapping[str, Any]]]
    field_inventory: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    btc_spot_witness_enabled: bool = False
    btc_completed_through: str | None = None
    witness_provenance: dict[str, Any] = field(default_factory=dict)
    witness_errors: dict[str, str] = field(default_factory=dict)
    fetch_error: str | None = None
    run_error: str | None = None
    requested_start: str | None = None
    requested_end: str | None = None
    completed_through: str | None = None
    operation_id: str = field(default_factory=lambda: uuid4().hex)
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    canonical_files: dict[str, dict[str, Any]] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def admit(
        self,
        symbol: str,
        candidate: pd.DataFrame,
    ) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
        if candidate.empty:
            return candidate.copy(), []

        symbol = str(symbol).upper()
        if not self.enabled:
            bypass_rows = [
                self._bypass_row(symbol, index, "DISABLED") for index in candidate.index
            ]
            self.evidence.extend(bypass_rows)
            return candidate.copy(), bypass_rows
        if self.btc_spot_witness_enabled and symbol == "BTC-USD":
            return self._admit_btc(candidate)
        if not is_alpaca_supported_symbol(symbol):
            bypass_rows = [
                self._bypass_row(symbol, index, "NOT_APPLICABLE")
                for index in candidate.index
            ]
            self.evidence.extend(bypass_rows)
            return candidate.copy(), bypass_rows

        witness_by_date = {
            str(row.get("t") or "")[:10]: row
            for row in self.witness_bars.get(symbol, [])
            if isinstance(row, Mapping)
        }
        admitted_positions: list[int] = []
        rows: list[dict[str, Any]] = []
        for position, (index, candidate_row) in enumerate(candidate.iterrows()):
            day = pd.Timestamp(index).date().isoformat()
            if (
                (self.requested_start and day < self.requested_start)
                or (self.requested_end and day >= self.requested_end)
            ):
                evidence = self._rejection_row(
                    symbol,
                    day,
                    "OUTSIDE_WITNESS_WINDOW",
                    "candidate date is outside the fetched witness window",
                )
                rows.append(evidence)
                continue
            if self.completed_through and day > self.completed_through:
                evidence = self._rejection_row(
                    symbol,
                    day,
                    "UNFINALIZED_SESSION",
                    f"candidate session is later than completed_through={self.completed_through}",
                )
                rows.append(evidence)
                continue
            local = {
                "date": day,
                "open": candidate_row.get("Open"),
                "high": candidate_row.get("High"),
                "low": candidate_row.get("Low"),
                "close": candidate_row.get("Close"),
                "volume": candidate_row.get("Volume"),
            }
            comparison = compare_market_bar(
                local,
                witness_by_date.get(day),
                require_complete=True,
            )
            admitted = comparison.get("status") == "MATCH"
            if admitted:
                admitted_positions.append(position)
            evidence = {
                "symbol": symbol,
                "date": day,
                "status": comparison.get("status"),
                "admitted": admitted,
                "reason": comparison.get("reason"),
                "warning_band": bool(comparison.get("warning_band", False)),
                "close_diff_pct": comparison.get("close_diff_pct"),
                "max_ohlc_diff_pct": comparison.get("max_ohlc_diff_pct"),
                "volume_diff_pct": comparison.get("volume_diff_pct"),
                "price_evidence_status": comparison.get("price_evidence_status"),
                "volume_evidence_status": comparison.get("volume_evidence_status"),
                "candidate_sha256": comparison.get("local_sha256"),
                "witness_sha256": comparison.get("witness_sha256"),
                **self._decision_metadata(symbol),
            }
            if comparison.get("raw_comparison"):
                evidence["raw_comparison"] = comparison["raw_comparison"]
            source_fetch_error = (
                self.witness_errors.get("alpaca")
                if self.btc_spot_witness_enabled
                else self.fetch_error
            )
            if source_fetch_error and comparison.get("status") == "NO_WITNESS":
                evidence["fetch_error"] = source_fetch_error
            rows.append(evidence)
        self.evidence.extend(rows)
        return candidate.iloc[admitted_positions].copy(), rows

    def _admit_btc(
        self,
        candidate: pd.DataFrame,
    ) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
        witness_by_date = {
            str(row.get("t") or "")[:10]: row
            for row in self.witness_bars.get("BTC-USD", [])
            if isinstance(row, Mapping)
        }
        admitted_positions: list[int] = []
        rows: list[dict[str, Any]] = []
        for position, (index, candidate_row) in enumerate(candidate.iterrows()):
            day = pd.Timestamp(index).date().isoformat()
            if (
                (self.requested_start and day < self.requested_start)
                or (self.requested_end and day >= self.requested_end)
            ):
                rows.append(
                    self._rejection_row(
                        "BTC-USD",
                        day,
                        "OUTSIDE_WITNESS_WINDOW",
                        "candidate date is outside the fetched Coinbase witness window",
                    )
                )
                continue
            if self.btc_completed_through and day > self.btc_completed_through:
                rows.append(
                    self._rejection_row(
                        "BTC-USD",
                        day,
                        "DEFERRED_UNFINALIZED",
                        (
                            "BTC UTC day is still open; "
                            f"completed_through={self.btc_completed_through}"
                        ),
                        blocking=False,
                    )
                )
                continue
            local = {
                "date": day,
                "open": candidate_row.get("Open"),
                "high": candidate_row.get("High"),
                "low": candidate_row.get("Low"),
                "close": candidate_row.get("Close"),
                "volume": candidate_row.get("Volume"),
            }
            comparison = compare_btc_spot_close(local, witness_by_date.get(day))
            admitted = comparison.get("status") == "MATCH"
            if admitted:
                admitted_positions.append(position)
            evidence = {
                "symbol": "BTC-USD",
                "date": day,
                "status": comparison.get("status"),
                "admitted": admitted,
                "reason": comparison.get("reason"),
                "warning_band": bool(comparison.get("warning_band", False)),
                "close_diff_pct": comparison.get("close_diff_pct"),
                "candidate_sha256": comparison.get("local_sha256"),
                "witness_sha256": comparison.get("witness_sha256"),
                "witness_source": COINBASE_SOURCE,
                **self._decision_metadata("BTC-USD"),
            }
            witness_error = self.witness_errors.get("coinbase")
            if witness_error and comparison.get("status") == "NO_WITNESS":
                evidence["fetch_error"] = witness_error
            rows.append(evidence)
        self.evidence.extend(rows)
        return candidate.iloc[admitted_positions].copy(), rows

    def uses_calendar_days(self, symbol: str) -> bool:
        return self.enabled and self.btc_spot_witness_enabled and str(symbol).upper() == "BTC-USD"

    def payload(self, *, generated_at: str | None = None) -> dict[str, Any]:
        summary: dict[str, int] = {}
        price_evidence_summary: dict[str, int] = {}
        volume_evidence_summary: dict[str, int] = {}
        admitted_rows = 0
        for row in self.evidence:
            status = str(row.get("status") or "UNKNOWN")
            summary[status] = summary.get(status, 0) + 1
            price_status = row.get("price_evidence_status")
            if price_status:
                key = str(price_status)
                price_evidence_summary[key] = price_evidence_summary.get(key, 0) + 1
            volume_status = row.get("volume_evidence_status")
            if volume_status:
                key = str(volume_status)
                volume_evidence_summary[key] = volume_evidence_summary.get(key, 0) + 1
            admitted_rows += int(bool(row.get("admitted")))
        deferred_rows = sum(
            1
            for row in self.evidence
            if not row.get("admitted") and row.get("blocking") is False
        )
        rejected_rows = len(self.evidence) - admitted_rows - deferred_rows
        if not self.enabled:
            status = "DISABLED"
        elif self.run_error:
            status = "ERROR"
        elif self.fetch_error:
            status = "FETCH_ERROR"
        elif rejected_rows:
            status = "BLOCKED"
        else:
            status = "OK"
        payload = {
            "schema_version": (
                "hermes-market-admission-v2"
                if self.btc_spot_witness_enabled
                else "hermes-market-admission-v1"
            ),
            "mode": "enforce_consensus" if self.enabled else "off",
            "source": (
                "YAHOO_PLUS_ALPACA_SIP_PLUS_COINBASE_EXCHANGE"
                if self.btc_spot_witness_enabled
                else "YAHOO_PLUS_ALPACA_SIP"
            ),
            "status": status,
            "generated_at": generated_at or self.generated_at,
            "operation_id": self.operation_id,
            "requested_start": self.requested_start,
            "requested_end": self.requested_end,
            "completed_through": self.completed_through,
            "fetch_error": self.fetch_error,
            "run_error": self.run_error,
            "canonical_files": dict(self.canonical_files),
            "summary": summary,
            "price_evidence_summary": price_evidence_summary,
            "volume_evidence_summary": volume_evidence_summary,
            "admitted_rows": admitted_rows,
            "rejected_rows": rejected_rows,
            "rows": list(self.evidence),
        }
        if self.field_inventory:
            strategy_rejected, component_rejected = _rejection_impact_counts(
                self.evidence
            )
            payload["strategy_blocking_rejected_rows"] = strategy_rejected
            payload["component_flow_rejected_rows"] = component_rejected
        if self.btc_spot_witness_enabled:
            payload["deferred_rows"] = deferred_rows
            payload["btc_spot_witness"] = {
                "enabled": True,
                "source": COINBASE_SOURCE,
                "completed_through": self.btc_completed_through,
                "provenance": dict(self.witness_provenance.get("coinbase") or {}),
                "error": self.witness_errors.get("coinbase"),
            }
        if self.witness_provenance.get("alpaca"):
            payload["equity_witness"] = _safe_alpaca_witness_provenance(
                self.witness_provenance["alpaca"]
            )
        return payload

    def bind_canonical_files(
        self,
        history_dir: Path,
        symbols: Iterable[str],
    ) -> None:
        root = Path(history_dir)
        for symbol in symbols:
            name = f"{safe_symbol(symbol)}.csv"
            path = root / name
            if not path.exists():
                self.canonical_files.pop(name, None)
                continue
            latest_as_of = None
            try:
                dates = pd.read_csv(path, usecols=["date"])["date"].dropna()
                if not dates.empty:
                    latest_as_of = str(dates.iloc[-1])[:10]
            except Exception:
                latest_as_of = None
            self.canonical_files[name] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "latest_as_of": latest_as_of,
            }

    def _bypass_row(self, symbol: str, index: Any, status: str) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "date": pd.Timestamp(index).date().isoformat(),
            "status": status,
            "admitted": True,
            "reason": "Alpaca SIP admission does not apply",
            **self._decision_metadata(symbol),
        }

    def _rejection_row(
        self,
        symbol: str,
        day: str,
        status: str,
        reason: str,
        *,
        blocking: bool = True,
    ) -> dict[str, Any]:
        row = {
            "symbol": symbol,
            "date": day,
            "status": status,
            "admitted": False,
            "reason": reason,
            **self._decision_metadata(symbol),
        }
        if not blocking:
            row["blocking"] = False
        return row

    def _decision_metadata(self, symbol: str) -> dict[str, Any]:
        if not self.field_inventory:
            return {}
        inventory = self.field_inventory.get(str(symbol).upper())
        roles = (
            [str(role) for role in inventory.get("roles") or []]
            if isinstance(inventory, Mapping)
            else []
        )
        impact = (
            "COMPONENT_FLOW_ONLY"
            if roles and set(roles) <= {"component_flow"}
            else "STRATEGY_BLOCKING"
        )
        return {"decision_roles": roles, "decision_impact": impact}


def prepare_market_admission_session(
    symbols: Iterable[str],
    start: str,
    end: str,
    *,
    credentials: Mapping[str, str] | None = None,
    request_json: Callable[[str, Mapping[str, str]], dict[str, Any]] | None = None,
    now: datetime | None = None,
    btc_spot_witness_enabled: bool = False,
    coinbase_request_json: Callable[[str, Mapping[str, str]], Any] | None = None,
    field_inventory: Mapping[str, Mapping[str, Any]] | None = None,
) -> MarketAdmissionSession:
    completed_through = latest_completed_us_market_session(now).isoformat()
    if not btc_spot_witness_enabled:
        try:
            auth = dict(credentials or load_alpaca_credentials())
            alpaca_witness_bars = fetch_alpaca_daily_bar_range(
                symbols,
                start,
                end,
                auth,
                request_json=request_json,
                now=now,
            )
            alpaca_provenance = {
                "alpaca": _alpaca_witness_provenance(
                    alpaca_witness_bars,
                    start=start,
                    end=end,
                    completed_through=completed_through,
                    now=now,
                )
            }
            return MarketAdmissionSession(
                enabled=True,
                witness_bars=alpaca_witness_bars,
                field_inventory=field_inventory or {},
                witness_provenance=alpaca_provenance,
                requested_start=str(start)[:10],
                requested_end=str(end)[:10],
                completed_through=completed_through,
            )
        except Exception as exc:
            return MarketAdmissionSession(
                enabled=True,
                witness_bars={},
                field_inventory=field_inventory or {},
                fetch_error=f"{exc.__class__.__name__}: {exc}",
                requested_start=str(start)[:10],
                requested_end=str(end)[:10],
                completed_through=completed_through,
            )

    selected = sorted({str(symbol).upper() for symbol in symbols})
    witness_bars: dict[str, Iterable[Mapping[str, Any]]] = {}
    witness_errors: dict[str, str] = {}
    witness_provenance: dict[str, Any] = {}
    alpaca_symbols = [symbol for symbol in selected if is_alpaca_supported_symbol(symbol)]
    if alpaca_symbols:
        try:
            auth = dict(credentials or load_alpaca_credentials())
            alpaca_witness_bars = fetch_alpaca_daily_bar_range(
                alpaca_symbols,
                start,
                end,
                auth,
                request_json=request_json,
                now=now,
            )
            witness_bars.update(alpaca_witness_bars)
            witness_provenance["alpaca"] = _alpaca_witness_provenance(
                alpaca_witness_bars,
                start=start,
                end=end,
                completed_through=completed_through,
                now=now,
            )
        except Exception as exc:
            witness_errors["alpaca"] = f"{exc.__class__.__name__}: {exc}"
    if "BTC-USD" in selected:
        try:
            coinbase = fetch_coinbase_daily_bar_range(
                start,
                end,
                request_json=coinbase_request_json,
            )
            witness_bars["BTC-USD"] = list(coinbase.get("bars") or [])
            witness_provenance["coinbase"] = {
                key: value for key, value in coinbase.items() if key != "bars"
            }
        except Exception as exc:
            witness_bars["BTC-USD"] = []
            witness_errors["coinbase"] = f"{exc.__class__.__name__}: {exc}"
            partial_provenance = getattr(exc, "provenance", None)
            if isinstance(partial_provenance, Mapping):
                witness_provenance["coinbase"] = dict(partial_provenance)
    fetch_error = "; ".join(
        f"{source.upper()}: {message}"
        for source, message in sorted(witness_errors.items())
    ) or None
    return MarketAdmissionSession(
        enabled=True,
        witness_bars=witness_bars,
        field_inventory=field_inventory or {},
        btc_spot_witness_enabled=True,
        btc_completed_through=latest_completed_utc_day(now).isoformat(),
        witness_provenance=witness_provenance,
        witness_errors=witness_errors,
        fetch_error=fetch_error,
        requested_start=str(start)[:10],
        requested_end=str(end)[:10],
        completed_through=completed_through,
    )


def _rejection_impact_counts(rows: Iterable[Mapping[str, Any]]) -> tuple[int, int]:
    strategy_rejected = 0
    component_rejected = 0
    for row in rows:
        if row.get("admitted") or row.get("blocking") is False:
            continue
        if str(row.get("decision_impact") or "") == "COMPONENT_FLOW_ONLY":
            component_rejected += 1
        else:
            strategy_rejected += 1
    return strategy_rejected, component_rejected


def _alpaca_witness_provenance(
    witness_bars: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    start: str,
    end: str,
    completed_through: str,
    now: datetime | None,
) -> dict[str, Any]:
    normalized = {
        str(symbol): [
            bar
            for row in rows
            if isinstance(row, Mapping)
            for bar in [normalize_alpaca_witness_bar(row)]
            if bar is not None
        ]
        for symbol, rows in sorted(witness_bars.items())
    }
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    fetched_at = now or datetime.now(timezone.utc)
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    fetched_at = fetched_at.astimezone(timezone.utc).replace(microsecond=0)
    return {
        "schema_version": "hermes-alpaca-witness-provenance-v1",
        "source": ALPACA_WITNESS_SOURCE,
        "source_url": DATA_URL,
        "timeframe": "1Day",
        "feed": "sip",
        "adjustment": "raw",
        "fetched_at": fetched_at.isoformat(),
        "requested_start": str(start)[:10],
        "requested_end": str(end)[:10],
        "completed_through": completed_through,
        "symbols": sorted(normalized),
        "symbol_count": len(normalized),
        "bar_count": sum(len(rows) for rows in normalized.values()),
        "normalized_bars_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _safe_alpaca_witness_provenance(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in _ALPACA_PROVENANCE_FIELDS if key in value}


def write_market_admission_evidence(
    archive_dir: Path,
    payload: Mapping[str, Any],
) -> Path:
    dated, latest = market_admission_evidence_paths(archive_dir, payload)
    dated.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    for path in (dated, latest):
        _atomic_write_text(path, encoded)
    return latest


def market_admission_evidence_paths(
    archive_dir: Path,
    payload: Mapping[str, Any],
) -> tuple[Path, Path]:
    archive = Path(archive_dir)
    generated_date = timestamp_to_shanghai_date(payload.get("generated_at"))
    if generated_date is None:
        raise ValueError("market admission payload missing generated_at")
    generated_day = generated_date.isoformat()
    dated = archive / f"market_admission_{generated_day}.json"
    latest = archive / "market_admission_latest.json"
    return dated, latest


def read_market_admission_evidence(archive_dir: Path) -> dict[str, Any] | None:
    path = Path(archive_dir) / "market_admission_latest.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def validate_market_admission_evidence(
    payload: Mapping[str, Any],
    history_dir: Path,
    *,
    as_of: str | None = None,
    run_started_at: str | None = None,
) -> dict[str, Any]:
    out = dict(payload)
    if str(out.get("mode") or "") != "enforce_consensus":
        return out
    generated = _parse_timestamp(out.get("generated_at"))
    started = _parse_timestamp(run_started_at)
    completed = str(out.get("completed_through") or "")[:10]
    current_as_of = str(as_of or "")[:10]
    missing = [
        key
        for key in ("operation_id", "generated_at", "completed_through", "canonical_files")
        if not out.get(key)
    ]
    if missing or generated is None:
        out["status"] = "STALE"
        out["evidence_detail"] = f"evidence provenance missing: {', '.join(missing) or 'invalid generated_at'}"
        return out
    if current_as_of and completed < current_as_of:
        out["status"] = "STALE"
        out["evidence_detail"] = f"completed_through={completed} before score as_of={current_as_of}"
        return out
    if started is not None and generated < started:
        out["status"] = "STALE"
        out["evidence_detail"] = "evidence predates the current run receipt"
        return out
    canonical_files = out.get("canonical_files") or {}
    root = Path(history_dir)
    superseded_files: list[str] = []
    for name, expected in sorted(canonical_files.items()):
        if Path(name).name != name or not isinstance(expected, Mapping):
            out["status"] = "EVIDENCE_DRIFT"
            out["evidence_detail"] = f"invalid canonical evidence entry: {name}"
            return out
        path = root / name
        expected_sha = expected.get("sha256")
        if (
            not path.is_file()
            or not isinstance(expected_sha, str)
            or len(expected_sha) != 64
            or any(char not in "0123456789abcdef" for char in expected_sha.lower())
        ):
            out["status"] = "EVIDENCE_DRIFT"
            out["evidence_detail"] = f"{name} canonical evidence is incomplete"
            return out
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected_sha:
            if _is_strict_append_only_extension(
                path,
                expected_sha=expected_sha,
                expected_latest_as_of=str(expected.get("latest_as_of") or "")[:10],
            ):
                superseded_files.append(name)
                continue
            out["status"] = "EVIDENCE_DRIFT"
            out["evidence_detail"] = f"{name} sha256 mismatch"
            return out
    impact_detail = _validate_rejection_impact_contract(out)
    if impact_detail:
        out["status"] = "EVIDENCE_DRIFT"
        out["evidence_detail"] = impact_detail
        return out
    if str(out.get("schema_version") or "") == "hermes-market-admission-v2":
        detail = _validate_market_admission_v2(out)
        if detail:
            out["status"] = "EVIDENCE_DRIFT"
            out["evidence_detail"] = detail
            return out
    if superseded_files and str(out.get("status") or "") in {"OK", "BLOCKED"}:
        out["status"] = "SUPERSEDED_BY_NEWER_DATA"
        out["superseded_files"] = superseded_files
        out["evidence_detail"] = (
            "new certified rows appended after this run: "
            + ", ".join(superseded_files)
        )
    return out


def _is_strict_append_only_extension(
    path: Path,
    *,
    expected_sha: str,
    expected_latest_as_of: str,
) -> bool:
    """Return true only when the old canonical bytes are an exact CSV prefix."""
    if not expected_latest_as_of:
        return False
    data = path.read_bytes()
    digest = hashlib.sha256()
    prefix_end = 0
    matched = False
    for line in data.splitlines(keepends=True):
        digest.update(line)
        prefix_end += len(line)
        if digest.hexdigest() == expected_sha:
            matched = True
            break
    if not matched or prefix_end >= len(data):
        return False

    prefix_dates = _csv_first_column_dates(data[:prefix_end], allow_header=True)
    appended_dates = _csv_first_column_dates(data[prefix_end:], allow_header=False)
    ordered_dates = [expected_latest_as_of, *appended_dates]
    return bool(
        prefix_dates
        and appended_dates
        and prefix_dates[-1] == expected_latest_as_of
        and all(left < right for left, right in zip(ordered_dates, ordered_dates[1:]))
    )


def _csv_first_column_dates(data: bytes, *, allow_header: bool) -> list[str]:
    dates: list[str] = []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return dates
    nonempty_rows = 0
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        value = raw_line.split(",", 1)[0].strip().strip('"')
        try:
            date.fromisoformat(value)
        except ValueError:
            if allow_header and nonempty_rows == 0:
                nonempty_rows += 1
                continue
            return []
        dates.append(value)
        nonempty_rows += 1
    return dates


def _validate_market_admission_v2(payload: Mapping[str, Any]) -> str | None:
    btc = payload.get("btc_spot_witness")
    if not isinstance(btc, Mapping) or btc.get("enabled") is not True:
        return "BTC witness contract is missing or disabled"
    if btc.get("source") != COINBASE_SOURCE:
        return "BTC witness source is invalid"
    try:
        date.fromisoformat(str(btc.get("completed_through") or ""))
    except ValueError:
        return "BTC witness completed_through is invalid"

    provenance = btc.get("provenance")
    if not isinstance(provenance, Mapping):
        return "BTC witness provenance is missing"
    if provenance.get("source") != COINBASE_SOURCE:
        return "BTC witness provenance source is invalid"
    if provenance.get("source_url") != COINBASE_CANDLES_URL:
        return "BTC witness provenance URL is invalid"
    if _parse_timestamp(provenance.get("fetched_at")) is None:
        return "BTC witness fetched_at is invalid"
    for key in ("requested_start", "requested_end"):
        if str(provenance.get(key) or "")[:10] != str(payload.get(key) or "")[:10]:
            return f"BTC witness {key} does not match the admission window"
    requests = provenance.get("requests")
    if not isinstance(requests, list) or not requests:
        return "BTC witness request provenance is missing"
    for request in requests:
        if not isinstance(request, Mapping) or not str(request.get("url") or "").startswith(
            COINBASE_CANDLES_URL
        ):
            return "BTC witness request URL is invalid"
        status = request.get("status")
        if status == "OK":
            sha = request.get("content_sha256")
            if (
                not isinstance(sha, str)
                or len(sha) != 64
                or any(char not in "0123456789abcdef" for char in sha.lower())
            ):
                return "BTC witness response SHA256 is invalid"
            if not isinstance(request.get("row_count"), int) or request["row_count"] < 0:
                return "BTC witness row_count is invalid"
        elif status == "ERROR":
            if not request.get("error"):
                return "BTC witness failed request is missing its error"
        else:
            return "BTC witness request status is invalid"

    rows = payload.get("rows")
    summary = payload.get("summary")
    if not isinstance(rows, list) or not isinstance(summary, Mapping):
        return "market admission rows or summary are missing"
    computed_summary: dict[str, int] = {}
    admitted_rows = 0
    deferred_rows = 0
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("admitted"), bool):
            return "market admission row contract is invalid"
        status = str(row.get("status") or "UNKNOWN")
        admitted = row["admitted"]
        computed_summary[status] = computed_summary.get(status, 0) + 1
        admitted_rows += int(admitted)
        if row.get("blocking") is False:
            if admitted or status != "DEFERRED_UNFINALIZED":
                return "nonblocking market admission row is inconsistent"
            deferred_rows += 1
        if admitted != (status in {"MATCH", "NOT_APPLICABLE"}):
            return f"market admission row status/admitted mismatch for {status}"
    rejected_rows = len(rows) - admitted_rows - deferred_rows
    if dict(summary) != computed_summary:
        return "market admission summary does not match rows"
    if payload.get("admitted_rows") != admitted_rows:
        return "market admission admitted_rows does not match rows"
    if payload.get("deferred_rows") != deferred_rows:
        return "market admission deferred_rows does not match rows"
    if payload.get("rejected_rows") != rejected_rows:
        return "market admission rejected_rows does not match rows"
    if payload.get("run_error"):
        expected_status = "ERROR"
    elif payload.get("fetch_error"):
        expected_status = "FETCH_ERROR"
    elif rejected_rows:
        expected_status = "BLOCKED"
    else:
        expected_status = "OK"
    if payload.get("status") != expected_status:
        return f"market admission status does not match evidence ({expected_status})"
    return None


def _validate_rejection_impact_contract(payload: Mapping[str, Any]) -> str | None:
    rows = payload.get("rows")
    row_items = rows if isinstance(rows, list) else []
    impact_contract = any(
        key in payload
        for key in (
            "strategy_blocking_rejected_rows",
            "component_flow_rejected_rows",
        )
    ) or any(
        isinstance(row, Mapping)
        and ("decision_impact" in row or "decision_roles" in row)
        for row in row_items
    )
    if not impact_contract:
        return None
    if not isinstance(rows, list):
        return "market admission impact rows are missing"
    for row in rows:
        if not isinstance(row, Mapping):
            return "market admission impact row contract is invalid"
        roles = row.get("decision_roles")
        if not isinstance(roles, list) or not all(
            isinstance(role, str) for role in roles
        ):
            return "market admission decision roles are invalid"
        expected_impact = (
            "COMPONENT_FLOW_ONLY"
            if roles and set(roles) <= {"component_flow"}
            else "STRATEGY_BLOCKING"
        )
        if row.get("decision_impact") != expected_impact:
            return "market admission decision impact does not match roles"
    strategy_rejected, component_rejected = _rejection_impact_counts(rows)
    if payload.get("strategy_blocking_rejected_rows") != strategy_rejected:
        return "market admission strategy rejection count does not match rows"
    if payload.get("component_flow_rejected_rows") != component_rejected:
        return "market admission component rejection count does not match rows"
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _atomic_write_text(path: Path, content: str) -> None:
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, temp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temp.chmod(mode)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
