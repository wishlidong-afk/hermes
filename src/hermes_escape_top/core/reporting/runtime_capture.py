"""Explicit in-run inputs, owned by the existing v2 score transaction."""
from __future__ import annotations

import hashlib
import csv
import io
import json
import os
import sys
from importlib.metadata import distributions
from pathlib import Path
from datetime import datetime
from typing import Any
from collections.abc import Iterable, Mapping

import pandas as pd

from ..data.decision_identity import scoring_logic_hash, stable_hash
from ..data.base import SymbolSnapshot
from ..data.market import MarketData
from ..data.decision_revision import _release_hash
from ..data.run_transaction import ScoreRunTransaction, bind_score_run_inputs
from ..data.store import LocalStore, safe_symbol
from ..safe_io import assert_pipeline_lease
from ...config import resolve_path, validate_config
from .broker_capture import BrokerCapture


class RuntimeCapture:
    def __init__(
        self, *, store: LocalStore, config: dict[str, Any], config_path: Path, package_root: Path,
        as_of: str, capture_id: str, parameters: dict[str, Any], symbols: Iterable[str], artifacts: Iterable[Path],
        configuration: tuple[bytes, Path],
    ) -> None:
        if store.archive_dir.parent.resolve().is_relative_to(Path(package_root).resolve()):
            raise ValueError("capture data root must be outside source package")
        self.store = store
        self.config = json.loads(_json_bytes(config))
        self.as_of = str(as_of)[:10]
        self.capture_id = capture_id
        self.root = store.archive_dir / "decision_inputs" / capture_id
        self.parameters = json.loads(_json_bytes(parameters))
        self.broker = BrokerCapture(bool(parameters["include_ibkr"]))
        self.inputs: dict[str, Any] = {}
        self.certification_reads: list[dict[str, Any]] = []
        self.absent_sources: list[Path] = []
        self.before_paths = [self.root / "pre_state" / path.relative_to(store.archive_dir.parent)
                             for path in artifacts if path.exists()]
        self.sources: dict[str, tuple[Path, bytes]] = {}
        self.histories: dict[str, Any] = {}
        for symbol in symbols:
            row: dict[str, Any] = {}
            for role, legacy in (("primary", False), ("legacy", True)):
                path = store.history_path(symbol, legacy=legacy)
                entry: dict[str, Any] = {"source": str(path), "availability": "ABSENT", "path": None, "sha256": None}
                if path.is_symlink():
                    raise ValueError(f"capture history symlink: {path}")
                if path.exists():
                    name = f"market/{role}/{safe_symbol(symbol)}.csv"
                    content = path.read_bytes()
                    _validate_history(content, path)
                    self.sources[name] = (path, content)
                    entry.update(availability="PRESENT", path=(self.root / name).relative_to(store.archive_dir.parent).as_posix(),
                                 sha256=hashlib.sha256(content).hexdigest())
                else:
                    self.absent_sources.append(path)
                row[role] = entry
            row["selected"] = ("primary" if row["primary"]["availability"] == "PRESENT"
                               else "legacy" if row["legacy"]["availability"] == "PRESENT" else "missing")
            if row["selected"] == "missing":
                raise ValueError(f"capture required history missing: {symbol}")
            self.histories[symbol] = row
        self.config_path = Path(config_path).absolute()
        config_content, self.resolved_config_path = configuration
        if (self.config_path.resolve(strict=True) != self.resolved_config_path
                or self.config_path.read_bytes() != config_content):
            raise ValueError("capture configuration bytes changed after loading")
        if json.loads(config_content) != config:
            raise ValueError("capture loaded config does not match its source")
        self.sources["configuration.raw.json"] = (self.resolved_config_path, config_content)
        self.parameters["config_source"] = {"requested_path": str(self.config_path),
                                             "resolved_path": str(self.resolved_config_path)}
        soft_root = resolve_path(config, "soft_history_dir")
        for path in sorted(soft_root.glob("*.csv")):
            self._plan_source(f"soft_sources/{path.name}", path)
        package_root = Path(package_root).absolute()
        for path in sorted(package_root.rglob("*.py")):
            relative = path.relative_to(package_root)
            if "tests" not in relative.parts:
                self._plan_source(f"source/package/{relative.as_posix()}", path)
        self._plan_source("certification/market_manifest.json", store.archive_dir / "data_manifest_latest.json")
        self._plan_source("certification/approved_live_config.json", package_root / "governance/approved_live_config.json")
        self._plan_source("certification/VERSION", package_root / "VERSION")
        self.expected_certification_reads = {
            str(store.archive_dir / "data_manifest_latest.json"),
            str(package_root / "governance/approved_live_config.json"), str(package_root / "VERSION"),
        }
        if "certification/VERSION" not in self.sources:
            self.expected_certification_reads.update(str(path) for name, (path, _content) in self.sources.items()
                                                      if name.startswith("source/package/") and name.endswith(".py"))
        lock_path = next((root / "requirements.lock" for root in (package_root, *package_root.parents)
                          if (root / "requirements.lock").is_file()), package_root / "requirements.lock")
        self._plan_source("source/requirements.lock", lock_path)
        self.source_inventory = {
            str(path): {"source": str(path), "availability": "PRESENT",
                        "path": (self.root / name).relative_to(store.archive_dir.parent).as_posix(),
                        "sha256": hashlib.sha256(content).hexdigest()}
            for name, (path, content) in self.sources.items()
        }
        self.source_inventory.update({str(path): {"source": str(path), "availability": "ABSENT",
                                                  "path": None, "sha256": None} for path in self.absent_sources})

    def _plan_source(self, name: str, path: Path) -> None:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(f"capture invalid source: {path}")
        if path.exists():
            self.sources[name] = (path, path.read_bytes())
        else:
            self.absent_sources.append(path)

    def evidence_paths(self) -> list[Path]:
        return [self.root / name for name in (
            "manifest.json", "pre_state.json", "config.json", "parameters.json",
            "snapshots.json", "histories.json", "soft.json", "payload.json",
            "certification.json", "environment.json",
            "broker.json",
        )] + self.before_paths + [self.root / name for name in self.sources]

    def start(self, *, _lease: Any) -> None:
        assert_pipeline_lease(_lease, path=self.store.archive_dir / ".pipeline.lock")
        for name, (_path, content) in self.sources.items():
            self._write(name, content)

    def certification_read(self, path: Path, content: bytes | None) -> None:
        entry = self.source_inventory.get(str(path.absolute()))
        if entry is None or entry["sha256"] != (hashlib.sha256(content).hexdigest() if content is not None else None):
            raise ValueError(f"capture certification read mismatch: {path}")
        self.certification_reads.append(dict(entry))

    def record_inputs(
        self, *, snapshots: Mapping[str, SymbolSnapshot], histories: Mapping[str, pd.DataFrame], soft_data: dict[str, Any],
    ) -> None:
        frozen = LocalStore({**self.config, "paths": {**self.config["paths"],
                            "history_dir": str(self.root / "market/primary"),
                            "legacy_history_dir": str(self.root / "market/legacy")}})
        uncached = {**self.config, "features": {**self.config.get("features", {}), "use_indicator_cache": False}}
        market = MarketData(uncached, frozen)
        self._verify_soft_caches(frozen)
        if set(histories) != set(self.histories) or set(snapshots) != set(self.histories) | {"SOFT"}:
            raise ValueError("capture history universe mismatch")
        for symbol, actual in histories.items():
            frame = frozen.load_history(symbol)
            visible = frame.loc[frame.index <= pd.Timestamp(self.as_of)] if not frame.empty else frame
            expected = stable_hash(visible.reindex(sorted(visible.columns), axis=1).to_dict(orient="split"))
            if actual is None or expected != stable_hash(actual.reindex(sorted(actual.columns), axis=1).to_dict(orient="split")):
                raise ValueError(f"capture history consumption mismatch: {symbol}")
            if market.snapshot(symbol, self.as_of).to_dict() != snapshots[symbol].to_dict():
                raise ValueError(f"capture snapshot/cache mismatch: {symbol}")
            self.histories[symbol]["visible_hash"] = expected
        self.inputs = json.loads(_json_bytes({
            "snapshots.json": {symbol: snapshot.to_dict() for symbol, snapshot in snapshots.items()},
            "histories.json": {symbol: frame.to_dict(orient="split") if frame is not None else None
                               for symbol, frame in histories.items()},
            "soft.json": {"value": soft_data, "record_order": list(soft_data["records"]),
                          "record_field_order": {key: list(row.get("fields", {}))
                                                 for key, row in soft_data["records"].items()}},
        }))

    def _verify_soft_caches(self, frozen: LocalStore) -> None:
        from ..data import risk_signals
        contents = {str(path): content for path, content in self.sources.values()}
        try:
            for (source, mtime, dates), cached in list(risk_signals._CSV_CACHE.items()):
                if source in contents and Path(source).stat().st_mtime == mtime:
                    expected = pd.read_csv(io.BytesIO(contents[source]), parse_dates=list(dates) or None)
                    pd.testing.assert_frame_equal(cached, expected)
            for (symbol, source, mtime), cached in list(risk_signals._CLOSE_CACHE.items()):
                if source not in self.source_inventory:
                    continue
                current_mtime = Path(source).stat().st_mtime if Path(source).exists() else 0.0
                if current_mtime != mtime:
                    continue
                frame = frozen.load_history(symbol)
                expected = frame["Close"].dropna() if not frame.empty and "Close" in frame else None
                if expected is None or cached is None:
                    if expected is not cached:
                        raise ValueError("capture soft cache mismatch")
                else:
                    pd.testing.assert_series_equal(cached, expected)
        except AssertionError as exc:
            raise ValueError("capture soft cache mismatch") from exc

    def finish(self, transaction: ScoreRunTransaction, payload: dict[str, Any], *, _lease: Any) -> None:
        assert_pipeline_lease(_lease, path=self.store.archive_dir / ".pipeline.lock")
        if self.config_path.resolve(strict=True) != self.resolved_config_path:
            raise ValueError("capture config source link changed during scoring")
        if stable_hash(payload.get("market_admission_status")) != stable_hash(self.parameters.get("market_admission_status")):
            raise ValueError("capture admission argument changed")
        if (stable_hash(self.inputs.get("snapshots.json")) != stable_hash(payload["snapshots"])
                or stable_hash((self.inputs.get("soft.json") or {}).get("value")) != stable_hash(payload["soft_data"])):
            raise ValueError("capture consumed inputs changed after freezing")
        records = payload["soft_data"]["records"]
        soft = self.inputs["soft.json"]
        if (soft["record_order"] != list(records)
                or soft["record_field_order"] != {key: list(row.get("fields", {})) for key, row in records.items()}):
            raise ValueError("capture soft order changed after freezing")
        identity = payload["decision_evidence"]["semantic_identity"]
        if identity["history_hashes"] != {symbol: row["visible_hash"] for symbol, row in self.histories.items()}:
            raise ValueError("capture certified history projection mismatch")
        reads = [row["source"] for row in self.certification_reads]
        if set(reads) != self.expected_certification_reads or len(reads) != len(set(reads)):
            raise ValueError("capture certification reads incomplete")
        certificate = payload["decision_evidence"]
        manifest_content = self.sources["certification/market_manifest.json"][1]
        policy_content = self.sources["certification/approved_live_config.json"][1]
        version_content = self.sources.get("certification/VERSION")
        release = (version_content[1].decode().splitlines()[0].split()[0] if version_content
                   else _release_hash(self.root / "source/package"))
        if (certificate["canonical_market_evidence_hash"] != json.loads(manifest_content)["manifest_id"]
                or certificate["policy_hash"] != hashlib.sha256(policy_content).hexdigest()
                or certificate["scorer_release_hash"] != release
                or certificate["config_hash"] != stable_hash(self.config)
                or certificate["soft_input_evidence_hash"] != stable_hash(payload["soft_data"]["records"])
                or datetime.fromisoformat(certificate["certified_at"]) != datetime.fromisoformat(payload["run_ts"])):
            raise ValueError("capture certification material binding mismatch")
        binding = {"run_id": transaction.run_id, "capture_id": transaction.capture_id,
                   "as_of": self.as_of, "decision_id": payload["decision_evidence"]["decision_id"],
                   "input_hash": payload["input_hash"]}
        for name, value in {**self.inputs, "config.json": self.config,
                            "broker.json": self.broker.tape(payload),
                            "parameters.json": self.parameters, "payload.json": payload,
                            "certification.json": {"certified_at": payload["decision_evidence"]["certified_at"],
                                                   "reads": self.certification_reads},
                            "environment.json": {
                                "archive_scope": "PROJECT_SOURCE_AND_ENVIRONMENT_VERSIONS_NOT_INTERPRETER_OR_WHEELS",
                                "interpreter": {"executable": sys.executable, "version": sys.version},
                                "packages": sorted({(dist.metadata["Name"], dist.version) for dist in distributions()}),
                            }}.items():
            self._write(name, _json_bytes(value))
        for name, (path, content) in self.sources.items():
            if (self.root / name).read_bytes() != content:
                raise ValueError(f"capture archived source bytes mismatch: {name}")
            if path.is_symlink() or path.read_bytes() != content:
                raise ValueError(f"capture source changed during scoring: {path}")
        if any(path.exists() or path.is_symlink() for path in self.absent_sources):
            raise ValueError("capture absent source appeared during scoring")
        fingerprint = scoring_logic_hash(self.root / "source/package")
        if fingerprint != payload["decision_evidence"]["semantic_identity"]["scoring_logic_hash"]:
            raise ValueError("capture scoring source fingerprint mismatch")
        evidence = self.evidence_paths()
        files = [{"path": path.relative_to(self.store.archive_dir.parent).as_posix(),
                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                 for path in sorted(evidence) if path.is_file() and path.name != "manifest.json"]
        self._write("manifest.json", _json_bytes({
            "schema_version": "hermes-in-run-input-binding-v1", "capture_mode": "IN_RUN_CAPTURE",
            "binding": binding, "files": files, "histories": self.histories,
            "source_inventory": self.source_inventory, "scoring_logic_hash": fingerprint,
        }))
        manifest = self.root / "manifest.json"
        bind_score_run_inputs(
            transaction, manifest_path=manifest,
            expected_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
            decision_id=binding["decision_id"], input_hash=binding["input_hash"], _lease=_lease,
        )

    def _write(self, name: str, content: bytes) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open("xb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        path.chmod(0o400)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, default=str) + "\n").encode()


def read_capture_config(path: Path) -> tuple[dict[str, Any], bytes, Path]:
    """Parse and retain the same UTF-8 bytes; OFF still uses load_config."""
    path = Path(path).absolute()
    resolved = path.resolve(strict=True)
    content = path.read_bytes()
    config = json.loads(content.decode("utf-8"))
    validate_config(config)
    if path.resolve(strict=True) != resolved:
        raise ValueError("capture config source link changed while loading")
    return config, content, resolved


def _validate_history(content: bytes, path: Path) -> None:
    rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig")), strict=True))
    rows = [row for row in rows if row]
    if len(rows) < 2 or len(set(rows[0])) != len(rows[0]) or any(len(row) != len(rows[0]) for row in rows[1:]):
        raise ValueError(f"capture malformed history: {path}")
    columns = [column.lower() for column in rows[0]]
    if len(set(columns)) != len(columns) or "date" not in columns or "close" not in columns:
        raise ValueError(f"capture history columns missing: {path}")
    dates = pd.to_datetime([row[columns.index("date")] for row in rows[1:]], errors="coerce")
    if dates.isna().any() or dates.has_duplicates or not dates.is_monotonic_increasing:
        raise ValueError(f"capture malformed history dates: {path}")
    raw = pd.read_csv(io.BytesIO(content))
    for column in raw.columns:
        if column.lower() in {"open", "high", "low", "close", "volume"}:
            numeric = pd.to_numeric(raw[column], errors="coerce")
            if (raw[column].notna() & (numeric.isna() | numeric.isin([float("inf"), -float("inf")]))).any():
                raise ValueError(f"capture malformed history numeric field: {path}")
