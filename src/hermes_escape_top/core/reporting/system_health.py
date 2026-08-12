from __future__ import annotations

from typing import Any, Dict

from ..data.external_sources.ledger import (
    CANONICAL_EVIDENCE_CRITICAL_STATUSES,
    canonical_evidence_issue,
)


def system_health_run_stem(
    as_of: str,
    receipt: Dict[str, Any],
    report: Dict[str, Any],
) -> str:
    raw_timestamp = str(
        receipt.get("finished_at")
        or receipt.get("run_at")
        or report.get("generated_at")
        or "unknown"
    )
    timestamp = "".join(char for char in raw_timestamp if char.isalnum()) or "unknown"
    raw_hash = str(report.get("input_hash") or "no-input-hash")
    input_hash = "".join(char for char in raw_hash if char.isalnum() or char in {"-", "_"})
    return f"system_health_{as_of}_{timestamp}_{input_hash or 'no-input-hash'}"


def factor_score_symbol_count(payload: Dict[str, Any]) -> int:
    top_level = payload.get("factor_scores")
    if isinstance(top_level, dict) and top_level:
        return len(top_level)
    scores = payload.get("scores")
    if not isinstance(scores, dict):
        return 0
    count = 0
    for row in scores.values():
        if not isinstance(row, dict):
            continue
        factors = row.get("factor_scores")
        if isinstance(factors, dict) and any(bool(values) for values in factors.values()):
            count += 1
    return count


def build_system_health_audit_dimensions(
    payload: Dict[str, Any],
    report: Dict[str, Any],
) -> list[Dict[str, str]]:
    health = report.get("health") or {}
    layers = health.get("layers") or {}
    manifest = report.get("manifest_status") or {}
    receipt = report.get("run_receipt") or {}
    external_sources = payload.get("external_source_status") or {}
    data_quality = payload.get("data_quality") or {}
    sip_status = payload.get("alpaca_daily_flow_status") or {}
    sip_flow = payload.get("alpaca_daily_flow") or {}
    ibkr = payload.get("ibkr") or {}

    def layer_status(name: str) -> str:
        return audit_status_from_level((layers.get(name) or {}).get("level"))

    external_rows = [
        row
        for row in external_sources.values()
        if isinstance(row, dict) and row.get("active") is not False
    ] if isinstance(external_sources, dict) else []
    external_bad = [
        (
            f"{row.get('source_id') or '?'}:"
            f"{row.get('latest_attempt_status') or row.get('status') or 'MISSING'}"
            + (
                f" {row.get('latest_attempt_error_message') or row.get('latest_attempt_error_type')}"
                if row.get("latest_attempt_error_message") or row.get("latest_attempt_error_type")
                else ""
            )
        )
        for row in external_rows
        if str(row.get("latest_attempt_status") or row.get("status") or "") != "OK"
        and not (
            str(row.get("lifecycle_status") or "") == "RETIRED_PAYWALL"
            and not canonical_evidence_issue(row)
        )
    ]
    external_evidence_bad = [
        f"{row.get('source_id') or '?'}:{canonical_evidence_issue(row)}"
        for row in external_rows
        if canonical_evidence_issue(row)
    ]
    external_evidence_critical = any(
        canonical_evidence_issue(row) in CANONICAL_EVIDENCE_CRITICAL_STATUSES
        for row in external_rows
    )
    file_evidence = external_file_evidence(external_sources)
    receipt_status = str(receipt.get("status") or "")
    dq_level = str(data_quality.get("level") or "")
    stale_days = health.get("stale_trading_days")
    manifest_status = str(manifest.get("status") or "")
    ibkr_source = str(ibkr.get("source") or "")
    sip_error = str(sip_status.get("status") or "")
    factor_symbols = factor_score_symbol_count(payload)
    coverage_score = (report.get("decision_input_coverage") or {}).get("coverage_score")
    witness_status = (report.get("market_witness_status") or {}).get("status")

    return [
        audit_row(
            "scored_payload_cache",
            "评分 payload 缓存",
            "PASS" if (payload.get("cache_status") or {}).get("hit") else "FAIL",
            f"cache_status.hit=true source={(payload.get('cache_status') or {}).get('source', 'web_cache')}"
            if (payload.get("cache_status") or {}).get("hit")
            else "NO_CACHE",
        ),
        audit_row(
            "input_hash",
            "输入哈希",
            "PASS" if payload.get("input_hash") else "WARN",
            str(payload.get("input_hash") or "missing")[:16],
        ),
        audit_row(
            "market_as_of",
            "行情 as_of",
            "FAIL" if isinstance(stale_days, int) and stale_days >= 3 else "WARN" if isinstance(stale_days, int) and stale_days >= 1 else "PASS",
            f"as_of={report.get('as_of')} stale_trading_days={stale_days}",
        ),
        audit_row(
            "manifest_integrity",
            "数据清单",
            "PASS" if manifest_status == "OK" else "FAIL" if manifest_status == "DRIFT" else "WARN",
            manifest_status or "missing",
        ),
        audit_row(
            "data_quality",
            "数据质量",
            "PASS" if dq_level == "HIGH" else "WARN" if dq_level == "MEDIUM" else "FAIL" if dq_level in {"LOW", "BLOCKED", "NO_CACHE"} else "INFO",
            f"{dq_level or 'NA'} overall={data_quality.get('overall_score')} "
            f"decision_coverage={coverage_score} market_witness={witness_status or 'NA'}",
        ),
        audit_row("strategy_data_layer", "策略数据层", layer_status("strategy_data"), layer_detail(layers, "strategy_data")),
        audit_row(
            "position_reconciliation_layer",
            "持仓对账层",
            layer_status("position_reconciliation"),
            layer_detail(layers, "position_reconciliation"),
        ),
        audit_row("auxiliary_flows_layer", "辅助资金流层", layer_status("auxiliary_flows"), layer_detail(layers, "auxiliary_flows")),
        audit_row(
            "scheduled_receipt",
            "官方 run 回执",
            "PASS" if receipt_status == "OK" and receipt.get("ok") else "WARN" if receipt_status == "RUNNING" else "FAIL",
            f"status={receipt_status or 'MISSING'} run_type={receipt.get('run_type')}",
        ),
        audit_row(
            "external_source_runs",
            "外部源 runner",
            "FAIL" if external_evidence_critical else "PASS" if external_rows and not external_bad and not external_evidence_bad else "WARN" if external_rows else "INFO",
            "all OK"
            if external_rows and not external_bad and not external_evidence_bad
            else ", ".join((external_evidence_bad + external_bad)[:6]) or "no external_source_status",
        ),
        audit_row(
            "external_file_evidence",
            "官方文件证据",
            "PASS" if file_evidence else "INFO" if not external_rows else "WARN",
            "; ".join(file_evidence) if file_evidence else "no AAII/NAAIM issue+sha evidence",
        ),
        audit_row(
            "external_precheck_readiness",
            "外部源预检",
            "FAIL" if external_evidence_critical else "PASS" if external_rows and not external_bad and not external_evidence_bad else "WARN" if external_rows else "INFO",
            "latest ledger ready"
            if external_rows and not external_bad and not external_evidence_bad
            else "check latest external precheck log",
        ),
        audit_row(
            "ibkr_reconciliation",
            "IBKR 对账",
            layer_status("position_reconciliation"),
            f"source={ibkr_source or 'missing'} age_seconds={health.get('ibkr_age_seconds')}",
        ),
        audit_row(
            "sip_flow",
            "SIP 资金流",
            "WARN" if sip_error in {"ERROR", "MISSING"} else "PASS" if sip_flow.get("as_of") else "INFO",
            f"status={sip_error or 'OK'} as_of={sip_flow.get('as_of')}",
        ),
        audit_row("scores_present", "标的评分", "PASS" if payload.get("scores") else "FAIL", f"count={len(payload.get('scores') or {})}"),
        audit_row(
            "factor_scores_present",
            "因子贡献",
            "PASS" if factor_symbols else "WARN",
            f"symbols={factor_symbols}",
        ),
        audit_row("sizing_present", "系统目标仓位", "PASS" if payload.get("sizing") else "WARN", f"symbols={len(payload.get('sizing') or {})}"),
        audit_row(
            "hard_valve_evidence",
            "硬阀门证据",
            "PASS" if payload.get("decision_layers") else "WARN",
            f"symbols={len(payload.get('decision_layers') or {})}",
        ),
        audit_row(
            "risk_contributions",
            "风险贡献",
            "PASS" if payload.get("risk_contributions") else "INFO",
            f"rows={len(payload.get('risk_contributions') or [])}",
        ),
        audit_row(
            "stress_scenarios",
            "压力情景",
            "PASS" if payload.get("stress_scenarios") else "INFO",
            f"rows={len(payload.get('stress_scenarios') or [])}",
        ),
    ]


def audit_row(row_id: str, label: str, status: str, detail: str) -> Dict[str, str]:
    return {"id": row_id, "label": label, "status": status, "detail": str(detail or "")}


def audit_status_from_level(level: Any) -> str:
    text = str(level or "OK")
    if text == "CRITICAL":
        return "FAIL"
    if text == "DEGRADED":
        return "WARN"
    if text == "INFO":
        return "INFO"
    return "PASS"


def layer_detail(layers: Dict[str, Any], key: str) -> str:
    layer = layers.get(key) or {}
    checks = layer.get("checks") or []
    return "; ".join(str(check.get("label") or "") for check in checks) or str(layer.get("level") or "OK")


def external_file_evidence(external_sources: Any) -> list[str]:
    if not isinstance(external_sources, dict):
        return []
    evidence: list[str] = []
    for source_id, row in sorted(external_sources.items()):
        if not isinstance(row, dict):
            continue
        issue = row.get("official_issue_as_of")
        sha = row.get("official_file_sha256")
        if issue and sha:
            evidence.append(f"{source_id}:{str(issue)[:10]}:{str(sha)[:8]}")
    return evidence


def render_system_health_markdown(report: Dict[str, Any]) -> str:
    health = report.get("health") or {}
    layers = health.get("layers") or {}
    dimensions = report.get("audit_dimensions") or []
    lines = [
        f"# Hermes System Health — {report.get('as_of')}",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- overall_strategy_level: `{health.get('level')}`",
        f"- input_hash: `{str(report.get('input_hash') or 'NA')[:16]}`",
        f"- manifest: `{(report.get('manifest_status') or {}).get('status', 'NA')}`",
        f"- receipt: `{(report.get('run_receipt') or {}).get('status', 'NA')}`",
        "",
        "| Layer | Level | Checks |",
        "|---|---|---|",
    ]
    for key in ("strategy_data", "position_reconciliation", "auxiliary_flows"):
        row = layers.get(key) or {}
        checks = row.get("checks") or []
        check_text = "; ".join(
            f"{item.get('level')} {item.get('label')} {item.get('detail') or ''}".strip()
            for item in checks
        ) or "OK"
        lines.append(f"| {row.get('label', key)} | {row.get('level', 'OK')} | {check_text} |")
    lines.extend(
        [
            "",
            "## 20 维自检",
            "",
            "| ID | Status | Detail |",
            "|---|---|---|",
        ]
    )
    for row in dimensions:
        detail = str(row.get("detail") or "").replace("|", "\\|")
        lines.append(f"| {row.get('id')} | {row.get('status')} | {detail} |")
    lines.append("")
    return "\n".join(lines)
