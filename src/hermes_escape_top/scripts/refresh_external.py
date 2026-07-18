from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from hermes_escape_top.config import load_config, resolve_path
from hermes_escape_top.core.safe_io import (
    PipelineBusy,
    pipeline_lock,
)
from hermes_escape_top.core.data.store import safe_symbol
from hermes_escape_top.core.data.external_sources import (
    AaiiSentimentAdapter,
    AaiiSentimentImportAdapter,
    BtcMicroAdapter,
    CBOE_INDEX_DEFINITIONS,
    CboePcrAdapter,
    CboeVolatilityIndexAdapter,
    CotNqAdapter,
    FredNetLiquidityAdapter,
    FredPercentileAdapter,
    FredVintageAdapter,
    FredVintageNetLiquidityAdapter,
    FredVintagePercentileAdapter,
    NaaimExposureAdapter,
    NaaimExposureImportAdapter,
    NaaimSubscriberAdapter,
    OccPcrAdapter,
    all_source_ids,
    aaii_sentiment_spec,
    btc_micro_spec,
    cboe_pcr_spec,
    cboe_index_spec,
    cot_nq_spec,
    effective_source_profile,
    fred_net_liquidity_spec,
    fred_percentile_spec,
    fred_vintage_net_liquidity_spec,
    fred_vintage_percentile_spec,
    fred_vintage_spec,
    enrich_source_status,
    import_files,
    import_origin,
    import_source_ids,
    finalize_import,
    latest_import_file,
    naaim_exposure_spec,
    occ_pcr_spec,
    profile_for,
    queue_import_candidates,
    queued_import_files,
    configured_refresh_source_ids,
    run_external_source_refresh,
    source_status,
    terminal_import_hashes,
    verified_import_content,
)
from hermes_escape_top.core.data.risk_signals import fred_api_key
from hermes_escape_top.core.data.external_sources.ledger import (
    canonical_evidence_issue,
    iter_source_runs,
)
from hermes_escape_top.core.data.external_sources.clock import (
    shanghai_today,
    timestamp_to_shanghai_date,
)

SOURCE_IDS = configured_refresh_source_ids({"features": {"use_fred_vintage_pit": False}})
FRED_DERIVED_SOURCE_IDS = tuple(
    source_id for source_id in all_source_ids()
    if (profile_for(source_id) and profile_for(source_id).depends_on == "fred_vintages")
)
FRED_VINTAGE_SOURCE_IDS = configured_refresh_source_ids(
    {"features": {"use_fred_vintage_pit": True}}
)
CBOE_INDEX_SOURCE_IDS = tuple(
    source_id for source_id in all_source_ids()
    if profile_for(source_id) and profile_for(source_id).refresh_group == "cboe_indices"
)
ALL_SOURCE_IDS = all_source_ids()
IMPORT_FILE_SOURCE_IDS = import_source_ids()
POLICY_WARN_ONLY_STALE_SOURCE_IDS = frozenset(
    source_id for source_id in all_source_ids()
    if profile_for(source_id) and profile_for(source_id).warn_only_stale_after_refresh
)
DAILY_RETRY_REUSE_SECONDS = 15 * 60
OFFICIAL_BROWSER_URLS = {
    "aaii_sentiment": "https://www.aaii.com/files/surveys/sentiment.xls",
    "naaim_exposure": "https://www.naaim.org/programs/naaim-exposure-index/",
}


def _fred_vintage_enabled(config: dict[str, Any]) -> bool:
    return bool((config.get("features") or {}).get("use_fred_vintage_pit", False))


def _fred_vintage_path(config: dict[str, Any]) -> Path:
    return resolve_path(config, "soft_history_dir") / "fred_vintages.csv"


def fred_vintages_source(config: dict[str, Any]):
    target = _fred_vintage_path(config)
    return (
        fred_vintage_spec(target_path=target),
        FredVintageAdapter(
            target_path=target,
            api_key=fred_api_key(config),
        ),
    )


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


def dollar_vintage_source(config: dict[str, Any]):
    target = resolve_path(config, "soft_history_dir") / "dollar_vintage.csv"
    return (
        fred_vintage_percentile_spec(
            source_id="dollar_vintage",
            target_path=target,
            field="dollar_broad",
        ),
        FredVintagePercentileAdapter(
            vintage_path=_fred_vintage_path(config),
            series_id="DTWEXBGS",
            field="dollar_broad",
        ),
    )


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


def real_rate_vintage_source(config: dict[str, Any]):
    target = resolve_path(config, "soft_history_dir") / "real_rate_vintage.csv"
    return (
        fred_vintage_percentile_spec(
            source_id="real_rate_vintage",
            target_path=target,
            field="real_rate_10y",
        ),
        FredVintagePercentileAdapter(
            vintage_path=_fred_vintage_path(config),
            series_id="DFII10",
            field="real_rate_10y",
        ),
    )


def fred_net_liquidity_source(config: dict[str, Any]):
    target = resolve_path(config, "soft_history_dir") / "fred_net_liquidity.csv"
    return fred_net_liquidity_spec(target_path=target), FredNetLiquidityAdapter()


def fred_net_liquidity_vintage_source(config: dict[str, Any]):
    target = resolve_path(config, "soft_history_dir") / "fred_net_liquidity_vintage.csv"
    return (
        fred_vintage_net_liquidity_spec(target_path=target),
        FredVintageNetLiquidityAdapter(vintage_path=_fred_vintage_path(config)),
    )


def naaim_exposure_source(config: dict[str, Any]):
    target = resolve_path(config, "soft_history_dir") / "naaim_exposure.csv"
    subscriber_url = str(os.environ.get("NAAIM_SUBSCRIBER_URL") or "").strip()
    if subscriber_url:
        bearer = str(os.environ.get("NAAIM_SUBSCRIBER_BEARER_TOKEN") or "").strip()
        cookie = ""
        cookie_path = str(os.environ.get("NAAIM_SUBSCRIBER_COOKIE_FILE") or "").strip()
        if cookie_path:
            cookie = Path(cookie_path).expanduser().read_text(encoding="utf-8").strip()
        return naaim_exposure_spec(target_path=target), NaaimSubscriberAdapter(
            download_url=subscriber_url,
            bearer_token=bearer,
            session_cookie=cookie,
            seed_path=target,
        )
    return naaim_exposure_spec(target_path=target), NaaimExposureAdapter(seed_path=target)


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


def cboe_index_source(source_id: str, config: dict[str, Any]):
    definition = CBOE_INDEX_DEFINITIONS[source_id]
    target = resolve_path(config, "history_dir") / f"{safe_symbol(definition.symbol)}.csv"
    return (
        cboe_index_spec(definition, target),
        CboeVolatilityIndexAdapter(definition),
    )


def source_factories():
    factories = {
        "fred_vintages": fred_vintages_source,
        "dollar": dollar_source,
        "dollar_vintage": dollar_vintage_source,
        "real_rate": real_rate_source,
        "real_rate_vintage": real_rate_vintage_source,
        "fred_net_liquidity": fred_net_liquidity_source,
        "fred_net_liquidity_vintage": fred_net_liquidity_vintage_source,
        "cboe_equity_pcr": cboe_equity_pcr_source,
        "cot_nq": cot_nq_source,
        "occ_equity_pcr": occ_equity_pcr_source,
        "btc_funding_basis": btc_funding_basis_source,
        "naaim_exposure": naaim_exposure_source,
        "aaii_sentiment": aaii_sentiment_source,
    }
    factories.update(
        {
            source_id: (
                lambda config, source_id=source_id: cboe_index_source(source_id, config)
            )
            for source_id in CBOE_INDEX_SOURCE_IDS
        }
    )
    return factories


def configured_source_ids(config: dict[str, Any]) -> tuple[str, ...]:
    return configured_refresh_source_ids(config)


def source_specs(config: dict[str, Any]):
    specs = []
    for source_id in configured_source_ids(config):
        spec, _ = source_factories()[source_id](config)
        specs.append(spec)
    return specs


def refresh_source(
    source_id: str,
    config: dict[str, Any] | None = None,
    *,
    import_file: str | None = None,
    auto_import: bool = False,
    _lease: Any = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    archive_dir = resolve_path(cfg, "archive_dir")
    if source_id not in configured_source_ids(cfg):
        raise ValueError(f"external source disabled by config: {source_id}")
    factories = source_factories()
    if source_id not in factories:
        raise ValueError(f"unsupported external source: {source_id}")
    spec, adapter = factories[source_id](cfg)
    queued_import: Path | None = None
    queued_content: bytes | None = None
    if import_file:
        staged = queue_import_candidates(
            source_id,
            archive_dir,
            [Path(import_file).expanduser()],
            processed_hashes=_processed_import_hashes(source_id, archive_dir),
        )
        if not staged:
            raise ValueError(f"official import file hash already processed: {import_file}")
        queued_import = staged[0]
        queued_content = verified_import_content(queued_import)
        adapter = _import_adapter(
            source_id,
            spec,
            queued_import,
            content_bytes=queued_content,
        )
    runner_kwargs = {"_lease": _lease} if _lease is not None else {}
    run = run_external_source_refresh(spec, adapter, archive_dir, **runner_kwargs)
    result = run.to_dict()
    if queued_import is not None:
        terminal = finalize_import(
            queued_import,
            status=str(result.get("status") or "ERROR"),
            expected_content=queued_content,
        )
        result["import_queue_path"] = str(terminal)
        result["import_source_file"] = str(Path(import_file).expanduser())
    if auto_import and not import_file and str(result.get("status")) != "OK":
        latest_file = _latest_import_for(source_id)
        discovered = pending_import_files(source_id, archive_dir)
        if latest_file is not None and not discovered:
            skip_reason = (
                _previous_import_failure_reason(source_id, latest_file, archive_dir)
                or "official file hash already processed"
            )
            result["fallback_import_skipped"] = str(latest_file)
            result["fallback_import_skip_reason"] = skip_reason
            return result
        fallbacks = queue_import_candidates(
            source_id,
            archive_dir,
            discovered,
            processed_hashes=_processed_import_hashes(source_id, archive_dir),
        )
        attempted: list[str] = []
        fallback_from_status = result.get("status")
        for fallback in fallbacks:
            original = import_origin(fallback) or fallback
            attempted.append(str(original))
            fallback_content = verified_import_content(fallback)
            fallback_run = run_external_source_refresh(
                spec,
                _import_adapter(
                    source_id,
                    spec,
                    fallback,
                    content_bytes=fallback_content,
                ),
                archive_dir,
                **runner_kwargs,
            ).to_dict()
            fallback_run["fallback_from_status"] = fallback_from_status
            fallback_run["fallback_import_file"] = str(original)
            fallback_run["fallback_attempted_files"] = list(attempted)
            terminal = finalize_import(
                fallback,
                status=str(fallback_run.get("status") or "ERROR"),
                expected_content=fallback_content,
            )
            fallback_run["fallback_queue_path"] = str(terminal)
            result = fallback_run
            if str(fallback_run.get("status")) == "OK":
                return fallback_run
    return result


def _refresh_sources_with_dependencies(
    source_ids: tuple[str, ...] | list[str],
    cfg: dict[str, Any],
    *,
    auto_import: bool,
    _lease: Any = None,
) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    fred_vintage_ready = True
    for source_id in source_ids:
        if (
            _fred_vintage_enabled(cfg)
            and source_id in FRED_DERIVED_SOURCE_IDS
            and not fred_vintage_ready
        ):
            runs.append(
                {
                    "source_id": source_id,
                    "status": "SKIPPED_DEPENDENCY",
                    "dependency": "fred_vintages",
                    "error": "exact FRED vintage refresh failed; certified canonical retained",
                }
            )
            continue
        try:
            refresh_kwargs = {"_lease": _lease} if _lease is not None else {}
            run = refresh_source(
                source_id,
                cfg,
                auto_import=auto_import,
                **refresh_kwargs,
            )
            runs.append(run)
            if source_id == "fred_vintages":
                fred_vintage_ready = str(run.get("status") or "") == "OK"
        except Exception as exc:
            runs.append(
                {
                    "source_id": source_id,
                    "status": "ERROR",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                }
            )
            if source_id == "fred_vintages":
                fred_vintage_ready = False
    return runs


def refresh_all_sources(
    config: dict[str, Any] | None = None,
    *,
    auto_import: bool = True,
    _lease: Any = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    runs = _refresh_sources_with_dependencies(
        configured_source_ids(cfg),
        cfg,
        auto_import=auto_import,
        _lease=_lease,
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
    _lease: Any = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    day = today or shanghai_today()
    current = status(cfg, today=day)
    selected = [
        source_id
        for source_id in configured_source_ids(cfg)
        if _source_needs_retry(current.get(source_id) or {}, day)
    ]
    runs = _refresh_sources_with_dependencies(
        selected,
        cfg,
        auto_import=True,
        _lease=_lease,
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
    _lease: Any = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    day = today or shanghai_today()
    refresh_kwargs = {"_lease": _lease} if _lease is not None else {}
    refresh_result = (
        refresh_retry_sources(cfg, today=day, **refresh_kwargs)
        if retry_only
        else refresh_all_sources(cfg, auto_import=True, **refresh_kwargs)
    )
    sources = status(cfg, today=day)
    return _evaluate_readiness(cfg, refresh_result, sources)


def daily_source_check(
    config: dict[str, Any] | None = None,
    *,
    today: date | None = None,
    now: datetime | None = None,
    _lease: Any = None,
) -> dict[str, Any]:
    """Reuse a complete same-day precheck; otherwise perform a full refresh."""
    cfg = config or load_config()
    day = today or shanghai_today()
    sources = status(cfg, today=day)
    active_rows = [
        row for row in sources.values()
        if row.get("active") is not False
    ]
    if sources and all(_source_checked_on(row) == day for row in active_rows):
        checked_at = now or datetime.now(timezone.utc)
        retry_rows = [
            row
            for row in active_rows
            if _source_needs_retry(row, day)
        ]
        if any(_daily_retry_is_due(row, checked_at) for row in retry_rows):
            precheck_kwargs = {"_lease": _lease} if _lease is not None else {}
            return pre_daily_check(
                cfg,
                today=day,
                retry_only=True,
                **precheck_kwargs,
            )
        refresh_result = {
            "ok": True,
            "ok_count": sum(1 for row in active_rows if _attempt_status(row) == "OK"),
            "error_count": sum(1 for row in active_rows if _attempt_status(row) != "OK"),
            "runs": [_status_as_refresh_run(source_id, row) for source_id, row in sources.items()],
            "mode": "reuse_same_day",
            "selected_sources": [],
        }
        refresh_result["ok"] = refresh_result["error_count"] == 0
        return _evaluate_readiness(cfg, refresh_result, sources)
    precheck_kwargs = {"_lease": _lease} if _lease is not None else {}
    return pre_daily_check(cfg, today=day, **precheck_kwargs)


def _daily_retry_is_due(row: dict[str, Any], now: datetime) -> bool:
    if str(row.get("evidence_status") or "") not in {"", "MATCH"}:
        return True
    value = row.get("latest_attempt_finished_at") or row.get("finished_at")
    if not value:
        return True
    try:
        finished_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return True
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age_seconds = (now.astimezone(timezone.utc) - finished_at.astimezone(timezone.utc)).total_seconds()
    return age_seconds > DAILY_RETRY_REUSE_SECONDS


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
        evidence = canonical_evidence_issue(row)
        if evidence:
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
    return timestamp_to_shanghai_date(value)


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
    _lease: Any = None,
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
    result = refresh_source(
        source_id,
        config,
        import_file=str(selected),
        _lease=_lease,
    )
    result["downloaded_file"] = str(selected)
    result["official_url"] = url
    return result


def _import_adapter(
    source_id: str,
    spec: Any,
    path: Path,
    *,
    content_bytes: bytes | None = None,
):
    if source_id == "aaii_sentiment":
        return AaiiSentimentImportAdapter(
            seed_path=spec.target_path,
            import_path=path,
            content_bytes=content_bytes,
        )
    if source_id == "naaim_exposure":
        return NaaimExposureImportAdapter(
            import_path=path,
            seed_path=spec.target_path,
            content_bytes=content_bytes,
        )
    raise ValueError(f"--import-file is not supported for source: {source_id}")


def _latest_import_for(source_id: str) -> Path | None:
    profile = profile_for(source_id)
    if profile is None:
        return None
    return latest_import_file(profile)


def pending_import_file(source_id: str, archive_dir: Path) -> Path | None:
    """Return an official file only when its content hash is new to the ledger."""
    candidates = pending_import_files(source_id, archive_dir)
    return candidates[0] if candidates else None


def pending_import_files(source_id: str, archive_dir: Path) -> list[Path]:
    """Discover unprocessed official files without mutating queue state."""
    processed_hashes = _processed_import_hashes(source_id, archive_dir)
    processed_hashes.update(terminal_import_hashes(source_id, archive_dir))
    queued = queued_import_files(source_id, archive_dir)
    seen = set(processed_hashes)
    for path in queued:
        if file_hash := _file_sha256(path):
            seen.add(file_hash)
    pending = list(queued)
    for path in _import_candidates_for(source_id):
        file_hash = _file_sha256(path)
        if file_hash and file_hash not in seen:
            pending.append(path)
            seen.add(file_hash)
    return pending


def _processed_import_hashes(source_id: str, archive_dir: Path) -> set[str]:
    """Treat every terminal legacy ledger outcome as already processed."""
    latest_by_hash: dict[str, dict[str, Any]] = {}
    for row in iter_source_runs(archive_dir):
        if row.get("source_id") != source_id:
            continue
        content_hash = _run_content_sha256(row)
        if content_hash:
            latest_by_hash[content_hash] = row
    return set(latest_by_hash)


def _import_candidates_for(source_id: str) -> list[Path]:
    profile = profile_for(source_id)
    if profile is None:
        return []
    candidates = import_files(profile)
    latest = latest_import_file(profile)
    if latest is not None:
        candidates.insert(0, latest)
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


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
    recorded = row.get("official_file_sha256")
    if recorded:
        return str(recorded)
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
    day = today or shanghai_today()
    archive_dir = resolve_path(cfg, "archive_dir")
    rows = source_status(
        archive_dir,
        source_specs(cfg),
        today=day,
    )
    return {
        source_id: enrich_source_status(
            row,
            today=day,
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
    parser.add_argument("--source", choices=list(ALL_SOURCE_IDS), help="Refresh one source.")
    parser.add_argument("--import-file", help="Import an official downloaded source file for supported sources.")
    parser.add_argument("--auto-import", action="store_true", help="After a supported source fetch fails, try the newest official file in the configured import locations.")
    parser.add_argument("--open-official-download", action="store_true", help="Open the official browser download/page for a supported source, wait for a new file, then import it.")
    parser.add_argument("--downloads-dir", default="~/Downloads", help="Directory to watch with --open-official-download.")
    parser.add_argument("--all", action="store_true", help="Refresh all registered sources.")
    parser.add_argument("--pre-daily-check", action="store_true", help="Refresh all sources, auto-import official files when available, and print readiness.")
    parser.add_argument("--retry-needed", action="store_true", help="Retry only sources whose same-day check failed or whose canonical evidence is not ready.")
    parser.add_argument("--status", action="store_true", help="Print latest source-run status.")
    parser.add_argument("--lock-timeout", type=float, default=600.0, help="Seconds to wait for the shared pipeline write lock.")
    args = parser.parse_args(argv)

    if args.import_file and not args.source:
        parser.error("--import-file requires --source")
    if args.import_file and args.source not in IMPORT_FILE_SOURCE_IDS:
        parser.error("--import-file is supported only for: " + ", ".join(IMPORT_FILE_SOURCE_IDS))
    if args.status:
        print(json.dumps(status(), ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 0
    if not (args.pre_daily_check or args.retry_needed or args.source or args.all):
        parser.print_help()
        return 2
    try:
        cfg = load_config()
        lock_path = resolve_path(cfg, "archive_dir") / ".pipeline.lock"
        with pipeline_lock(
            blocking=True,
            timeout=max(float(args.lock_timeout), 0.0),
            path=lock_path,
        ) as lease:
            with redirect_stdout(sys.stderr):
                if args.pre_daily_check:
                    result = pre_daily_check(cfg, _lease=lease)
                elif args.retry_needed:
                    result = pre_daily_check(cfg, retry_only=True, _lease=lease)
                elif args.source and args.open_official_download:
                    result = open_official_download_and_import(
                        args.source,
                        cfg,
                        downloads_dir=Path(args.downloads_dir).expanduser(),
                        _lease=lease,
                    )
                elif args.source:
                    result = refresh_source(
                        args.source,
                        cfg,
                        import_file=args.import_file,
                        auto_import=args.auto_import,
                        _lease=lease,
                    )
                else:
                    result = refresh_all_sources(cfg, auto_import=True, _lease=lease)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 0
    except PipelineBusy as exc:
        print(json.dumps({"ok": False, "busy": True, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 75


if __name__ == "__main__":
    raise SystemExit(main())
