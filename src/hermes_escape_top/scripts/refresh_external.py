from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from hermes_escape_top.config import load_config, resolve_path
from hermes_escape_top.core.data.external_sources import (
    AaiiSentimentAdapter,
    AaiiSentimentImportAdapter,
    BtcMicroAdapter,
    CboePcrAdapter,
    CotNqAdapter,
    FredNetLiquidityAdapter,
    FredPercentileAdapter,
    NaaimExposureAdapter,
    NaaimExposureImportAdapter,
    OccPcrAdapter,
    aaii_sentiment_spec,
    btc_micro_spec,
    cboe_pcr_spec,
    cot_nq_spec,
    effective_source_profile,
    fred_net_liquidity_spec,
    fred_percentile_spec,
    enrich_source_status,
    latest_import_file,
    naaim_exposure_spec,
    occ_pcr_spec,
    profile_for,
    run_external_source_refresh,
    source_status,
)
from hermes_escape_top.core.data.external_sources.ledger import iter_source_runs

SOURCE_IDS = (
    "dollar",
    "real_rate",
    "fred_net_liquidity",
    "cboe_equity_pcr",
    "cot_nq",
    "occ_equity_pcr",
    "btc_funding_basis",
    "naaim_exposure",
    "aaii_sentiment",
)
IMPORT_FILE_SOURCE_IDS = ("naaim_exposure", "aaii_sentiment")
POLICY_WARN_ONLY_STALE_SOURCE_IDS = frozenset({"dollar"})
OFFICIAL_BROWSER_URLS = {
    "aaii_sentiment": "https://www.aaii.com/files/surveys/sentiment.xls",
    "naaim_exposure": "https://www.naaim.org/programs/naaim-exposure-index/",
}


def dollar_source(config: dict[str, Any]):
    target = resolve_path(config, "soft_history_dir") / "dollar.csv"
    spec = fred_percentile_spec(
        source_id="dollar",
        target_path=target,
        field="dollar_broad",
    )
    adapter = FredPercentileAdapter(
        series_id="DTWEXBGS",
        field="dollar_broad",
    )
    return spec, adapter


def real_rate_source(config: dict[str, Any]):
    target = resolve_path(config, "soft_history_dir") / "real_rate.csv"
    spec = fred_percentile_spec(
        source_id="real_rate",
        target_path=target,
        field="real_rate_10y",
    )
    adapter = FredPercentileAdapter(
        series_id="DFII10",
        field="real_rate_10y",
    )
    return spec, adapter


def fred_net_liquidity_source(config: dict[str, Any]):
    target = resolve_path(config, "soft_history_dir") / "fred_net_liquidity.csv"
    return fred_net_liquidity_spec(target_path=target), FredNetLiquidityAdapter()


def naaim_exposure_source(config: dict[str, Any]):
    target = resolve_path(config, "soft_history_dir") / "naaim_exposure.csv"
    return naaim_exposure_spec(target_path=target), NaaimExposureAdapter()


def aaii_sentiment_source(config: dict[str, Any]):
    target = resolve_path(config, "soft_history_dir") / "aaii_sentiment.csv"
    return aaii_sentiment_spec(target_path=target), AaiiSentimentAdapter(seed_path=target)


def cboe_equity_pcr_source(config: dict[str, Any]):
    target = resolve_path(config, "soft_history_dir") / "cboe_equity_pcr.csv"
    return cboe_pcr_spec(target_path=target), CboePcrAdapter(seed_path=target)


def cot_nq_source(config: dict[str, Any]):
    target = resolve_path(config, "soft_history_dir") / "cot_nq.csv"
    return cot_nq_spec(target_path=target), CotNqAdapter()


def occ_equity_pcr_source(config: dict[str, Any]):
    target = resolve_path(config, "soft_history_dir") / "occ_equity_pcr.csv"
    return occ_pcr_spec(target_path=target), OccPcrAdapter(seed_path=target)


def btc_funding_basis_source(config: dict[str, Any]):
    target = resolve_path(config, "soft_history_dir") / "btc_funding_basis.csv"
    return btc_micro_spec(target_path=target), BtcMicroAdapter(seed_path=target)


def source_factories():
    return {
        "dollar": dollar_source,
        "real_rate": real_rate_source,
        "fred_net_liquidity": fred_net_liquidity_source,
        "cboe_equity_pcr": cboe_equity_pcr_source,
        "cot_nq": cot_nq_source,
        "occ_equity_pcr": occ_equity_pcr_source,
        "btc_funding_basis": btc_funding_basis_source,
        "naaim_exposure": naaim_exposure_source,
        "aaii_sentiment": aaii_sentiment_source,
    }


def source_specs(config: dict[str, Any]):
    specs = []
    for source_id in SOURCE_IDS:
        spec, _ = source_factories()[source_id](config)
        specs.append(spec)
    return specs


def refresh_source(
    source_id: str,
    config: dict[str, Any] | None = None,
    *,
    import_file: str | None = None,
    auto_import: bool = False,
) -> dict[str, Any]:
    cfg = config or load_config()
    factories = source_factories()
    if source_id not in factories:
        raise ValueError(f"unsupported external source: {source_id}")
    spec, adapter = factories[source_id](cfg)
    archive_dir = resolve_path(cfg, "archive_dir")
    if import_file:
        adapter = _import_adapter(source_id, spec, Path(import_file).expanduser())
    run = run_external_source_refresh(spec, adapter, archive_dir)
    result = run.to_dict()
    if auto_import and not import_file and str(result.get("status")) != "OK":
        latest_file = _latest_import_for(source_id)
        fallback = pending_import_file(source_id, archive_dir)
        if latest_file is not None and fallback is None:
            skip_reason = (
                _previous_import_failure_reason(source_id, latest_file, archive_dir)
                or "official file hash already processed"
            )
            result["fallback_import_skipped"] = str(latest_file)
            result["fallback_import_skip_reason"] = skip_reason
            return result
        if fallback is not None:
            skip_reason = _previous_import_failure_reason(source_id, fallback, archive_dir)
            if skip_reason:
                result["fallback_import_skipped"] = str(fallback)
                result["fallback_import_skip_reason"] = skip_reason
                return result
            fallback_run = run_external_source_refresh(
                spec,
                _import_adapter(source_id, spec, fallback),
                archive_dir,
            ).to_dict()
            fallback_run["fallback_from_status"] = result.get("status")
            fallback_run["fallback_import_file"] = str(fallback)
            return fallback_run
    return result


def refresh_all_sources(config: dict[str, Any] | None = None, *, auto_import: bool = True) -> dict[str, Any]:
    cfg = config or load_config()
    runs: list[dict[str, Any]] = []
    for source_id in SOURCE_IDS:
        try:
            run = refresh_source(source_id, cfg, auto_import=auto_import)
            runs.append(run)
        except Exception as exc:
            runs.append(
                {
                    "source_id": source_id,
                    "status": "ERROR",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                }
            )
    ok_count = sum(1 for run in runs if str(run.get("status")) == "OK")
    error_count = len(runs) - ok_count
    return {
        "ok": error_count == 0,
        "ok_count": ok_count,
        "error_count": error_count,
        "runs": runs,
        "mode": "all",
    }


def refresh_retry_sources(
    config: dict[str, Any] | None = None,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    day = today or date.today()
    current = status(cfg, today=day)
    selected = [
        source_id
        for source_id in SOURCE_IDS
        if _source_needs_retry(current.get(source_id) or {}, day)
    ]
    runs: list[dict[str, Any]] = []
    for source_id in selected:
        try:
            runs.append(refresh_source(source_id, cfg, auto_import=True))
        except Exception as exc:
            runs.append(
                {
                    "source_id": source_id,
                    "status": "ERROR",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                }
            )
    ok_count = sum(1 for run in runs if str(run.get("status") or "") == "OK")
    return {
        "ok": ok_count == len(runs),
        "ok_count": ok_count,
        "error_count": len(runs) - ok_count,
        "runs": runs,
        "mode": "retry_needed",
        "selected_sources": selected,
    }


def pre_daily_check(
    config: dict[str, Any] | None = None,
    *,
    today: date | None = None,
    retry_only: bool = False,
) -> dict[str, Any]:
    cfg = config or load_config()
    refresh_result = (
        refresh_retry_sources(cfg, today=today)
        if retry_only
        else refresh_all_sources(cfg, auto_import=True)
    )
    sources = status(cfg, today=today)
    return _evaluate_readiness(cfg, refresh_result, sources)


def daily_source_check(
    config: dict[str, Any] | None = None,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Reuse a complete same-day precheck; otherwise perform a full refresh."""
    cfg = config or load_config()
    day = today or date.today()
    sources = status(cfg, today=day)
    if sources and all(_source_checked_on(row) == day for row in sources.values()):
        refresh_result = {
            "ok": True,
            "ok_count": sum(1 for row in sources.values() if _attempt_status(row) == "OK"),
            "error_count": sum(1 for row in sources.values() if _attempt_status(row) != "OK"),
            "runs": [_status_as_refresh_run(source_id, row) for source_id, row in sources.items()],
            "mode": "reuse_same_day",
            "selected_sources": [],
        }
        refresh_result["ok"] = refresh_result["error_count"] == 0
        return _evaluate_readiness(cfg, refresh_result, sources)
    return pre_daily_check(cfg, today=day)


def _evaluate_readiness(
    cfg: dict[str, Any],
    refresh_result: dict[str, Any],
    sources: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    refresh_runs = {
        str(run.get("source_id")): run
        for run in refresh_result.get("runs") or []
        if isinstance(run, dict) and run.get("source_id")
    }
    blocking = []
    warnings = []
    policy_warnings = []
    nonblocking_refresh_errors = []
    blocking_refresh_errors = []
    for source_id, row in sources.items():
        if row.get("active") is False:
            continue
        run_status = str(row.get("status") or "")
        freshness = str(row.get("freshness_status") or "")
        evidence = str(row.get("evidence_status") or "")
        if evidence in {"EVIDENCE_DRIFT", "MISSING_CANONICAL", "NO_LEDGER"}:
            blocking.append(source_id)
        elif run_status != "OK" or freshness == "UNKNOWN":
            blocking.append(source_id)
        elif freshness == "STALE":
            if _is_policy_warn_only_stale(
                cfg, source_id, row, refresh_runs.get(source_id) or {}
            ):
                row["publisher_status"] = "UNCHANGED_AFTER_REFRESH"
                row["publisher_note"] = (
                    "official source checked today; publisher has not posted a newer observation"
                )
                row["next_action"] = (
                    f"official source checked today; wait for publisher update for {source_id}"
                )
                row["readiness_severity"] = "WARN"
                warnings.append(source_id)
                policy_warnings.append(source_id)
            else:
                blocking.append(source_id)
        elif freshness == "DUE_SOON":
            warnings.append(source_id)
    for run in refresh_result.get("runs") or []:
        if not isinstance(run, dict):
            continue
        source_id = str(run.get("source_id") or "")
        if not source_id or str(run.get("status") or "") == "OK":
            continue
        row = sources.get(source_id) or {}
        if row.get("active") is False:
            continue
        source_ok = str(row.get("status") or "") == "OK"
        freshness = str(row.get("freshness_status") or "")
        if source_ok and freshness not in {"STALE", "UNKNOWN"}:
            nonblocking_refresh_errors.append(source_id)
            continue
        blocking_refresh_errors.append(source_id)
        if source_id not in blocking:
            blocking.append(source_id)
    return {
        "ready": not blocking,
        "blocking_sources": blocking,
        "warning_sources": warnings,
        "policy_warning_sources": policy_warnings,
        "nonblocking_refresh_error_sources": nonblocking_refresh_errors,
        "blocking_refresh_error_sources": blocking_refresh_errors,
        "refresh": refresh_result,
        "sources": sources,
    }


def _source_needs_retry(row: dict[str, Any], today: date) -> bool:
    if not row:
        return True
    if row.get("active") is False:
        return False
    if str(row.get("evidence_status") or "") not in {"", "MATCH"}:
        return True
    if _source_checked_on(row) != today:
        return True
    return _attempt_status(row) != "OK"


def _source_checked_on(row: dict[str, Any]) -> date | None:
    value = row.get("latest_attempt_finished_at") or row.get("finished_at")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(ZoneInfo("Asia/Shanghai")).date()


def _attempt_status(row: dict[str, Any]) -> str:
    return str(row.get("latest_attempt_status") or row.get("status") or "")


def _status_as_refresh_run(source_id: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "status": _attempt_status(row),
        "error_type": row.get("latest_attempt_error_type") or row.get("error_type"),
        "error_message": row.get("latest_attempt_error_message") or row.get("error_message"),
        "latest_promoted_as_of": row.get("latest_promoted_as_of"),
    }


def _is_policy_warn_only_stale(
    config: dict[str, Any],
    source_id: str,
    row: dict[str, Any],
    refresh_run: dict[str, Any],
) -> bool:
    if source_id not in POLICY_WARN_ONLY_STALE_SOURCE_IDS:
        return False
    features = config.get("features") or {}
    if not features.get("use_soft_data_max_age", False):
        return False
    if not features.get(f"data_{source_id}", False):
        return False
    if str(row.get("status") or "") != "OK":
        return False
    if str(row.get("freshness_status") or "") != "STALE":
        return False
    if str(refresh_run.get("status") or "") != "OK":
        return False
    configured = (
        ((config.get("soft_data_slo") or {}).get("max_age_days") or {}).get(source_id)
    )
    try:
        age_days = int(row.get("age_days"))
        max_age_days = int(configured)
    except (TypeError, ValueError):
        return False
    return age_days > max_age_days


def open_official_download_and_import(
    source_id: str,
    config: dict[str, Any] | None = None,
    *,
    downloads_dir: Path | str | None = None,
    opener: Callable[[str], None] | None = None,
    timeout_seconds: float = 90.0,
    poll_seconds: float = 1.0,
) -> dict[str, Any]:
    if source_id not in IMPORT_FILE_SOURCE_IDS:
        raise ValueError(f"official browser download is not supported for source: {source_id}")
    profile = profile_for(source_id)
    if profile is None:
        raise ValueError(f"unsupported external source: {source_id}")
    directory = Path(downloads_dir or "~/Downloads").expanduser()
    before = {path.resolve() for path in _matching_import_files(profile, directory)}
    url = OFFICIAL_BROWSER_URLS[source_id]
    (opener or _open_url)(url)
    deadline = time.time() + timeout_seconds
    selected: Path | None = None
    while time.time() <= deadline:
        candidates = [
            path for path in _matching_import_files(profile, directory)
            if path.resolve() not in before and not path.name.endswith(".crdownload")
        ]
        if candidates:
            selected = max(candidates, key=lambda path: path.stat().st_mtime)
            break
        time.sleep(poll_seconds)
    if selected is None:
        raise TimeoutError(f"no new official {source_id} import file appeared in {directory}")
    result = refresh_source(source_id, config, import_file=str(selected))
    result["downloaded_file"] = str(selected)
    result["official_url"] = url
    return result


def _import_adapter(source_id: str, spec: Any, path: Path):
    if source_id == "aaii_sentiment":
        return AaiiSentimentImportAdapter(seed_path=spec.target_path, import_path=path)
    if source_id == "naaim_exposure":
        return NaaimExposureImportAdapter(import_path=path)
    raise ValueError(f"--import-file is not supported for source: {source_id}")


def _latest_import_for(source_id: str) -> Path | None:
    profile = profile_for(source_id)
    if profile is None:
        return None
    return latest_import_file(profile)


def pending_import_file(source_id: str, archive_dir: Path) -> Path | None:
    """Return an official file only when its content hash is new to the ledger."""
    path = _latest_import_for(source_id)
    if path is None:
        return None
    file_hash = _file_sha256(path)
    if not file_hash:
        return None
    for row in iter_source_runs(archive_dir):
        if row.get("source_id") == source_id and _run_content_sha256(row) == file_hash:
            return None
    return path


def _previous_import_failure_reason(source_id: str, path: Path, archive_dir: Path) -> str | None:
    file_hash = _file_sha256(path)
    if not file_hash:
        return None
    for row in iter_source_runs(archive_dir):
        if row.get("source_id") != source_id or str(row.get("status") or "") == "OK":
            continue
        if _run_content_sha256(row) == file_hash:
            return "previous failure for same official file hash"
    return None


def _file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _run_content_sha256(row: dict[str, Any]) -> str | None:
    raw_path = row.get("raw_path")
    if not raw_path:
        return None
    try:
        raw = json.loads(Path(str(raw_path)).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = raw.get("content_sha256") or raw.get("xlsx_sha256")
    return str(value) if value else None


def _matching_import_files(profile: Any, directory: Path) -> list[Path]:
    out: list[Path] = []
    for pattern in getattr(profile, "import_globs", ()):
        name = Path(str(pattern)).name
        out.extend(directory.glob(name))
    return [path for path in out if path.is_file()]


def _open_url(url: str) -> None:
    subprocess.run(["open", url], check=True)


def status(config: dict[str, Any] | None = None, *, today: date | None = None) -> dict[str, dict[str, Any]]:
    cfg = config or load_config()
    archive_dir = resolve_path(cfg, "archive_dir")
    rows = source_status(
        archive_dir,
        source_specs(cfg),
        today=today,
    )
    return {
        source_id: enrich_source_status(
            row,
            today=today,
            profile=effective_source_profile(cfg, source_id),
            official_artifact_ready=(
                source_id in IMPORT_FILE_SOURCE_IDS
                and pending_import_file(source_id, archive_dir) is not None
            ),
        )
        for source_id, row in rows.items()
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh Hermes external data sources independently.")
    parser.add_argument("--source", choices=list(SOURCE_IDS), help="Refresh one source.")
    parser.add_argument("--import-file", help="Import an official downloaded source file for supported sources.")
    parser.add_argument("--auto-import", action="store_true", help="After a supported source fetch fails, try the newest official file in the configured import locations.")
    parser.add_argument("--open-official-download", action="store_true", help="Open the official browser download/page for a supported source, wait for a new file, then import it.")
    parser.add_argument("--downloads-dir", default="~/Downloads", help="Directory to watch with --open-official-download.")
    parser.add_argument("--all", action="store_true", help="Refresh all registered sources.")
    parser.add_argument("--pre-daily-check", action="store_true", help="Refresh all sources, auto-import official files when available, and print readiness.")
    parser.add_argument("--retry-needed", action="store_true", help="Retry only sources whose same-day check failed or whose canonical evidence is not ready.")
    parser.add_argument("--status", action="store_true", help="Print latest source-run status.")
    args = parser.parse_args(argv)

    if args.import_file and not args.source:
        parser.error("--import-file requires --source")
    if args.import_file and args.source not in IMPORT_FILE_SOURCE_IDS:
        parser.error("--import-file is supported only for: " + ", ".join(IMPORT_FILE_SOURCE_IDS))
    if args.status:
        print(json.dumps(status(), ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 0
    if args.pre_daily_check:
        print(json.dumps(pre_daily_check(), ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 0
    if args.retry_needed:
        print(json.dumps(pre_daily_check(retry_only=True), ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 0
    if args.source:
        if args.open_official_download:
            print(json.dumps(open_official_download_and_import(args.source, downloads_dir=Path(args.downloads_dir).expanduser()), ensure_ascii=False, indent=2, sort_keys=True, default=str))
            return 0
        print(json.dumps(refresh_source(args.source, import_file=args.import_file, auto_import=args.auto_import), ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 0
    if args.all:
        print(json.dumps(refresh_all_sources(auto_import=True), ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
