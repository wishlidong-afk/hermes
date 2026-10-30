"""Daily run-health gate.

Turns the scattered freshness/quality/IBKR/manifest signals into ONE loud
verdict so a degraded run (stale data, dead source, IBKR down, manifest drift,
no cache) is impossible to miss — instead of silently shipping a "looks fine"
daily report. Read-only; consumed by the WebUI banner and /api/health_status.

Levels: OK (green) · DEGRADED (amber) · CRITICAL (red).
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from ..core.data.external_sources.ledger import (
    CANONICAL_EVIDENCE_CRITICAL_STATUSES,
    canonical_evidence_issue,
    certified_canonical_is_current,
)
from ..core.data.external_sources.profiles import profile_for
from ..core.data.external_sources.clock import timestamp_to_shanghai_date
from .refresh import _completed_trading_days_after

# Sources that are off/unwired BY DESIGN — their absence is the steady-state
# baseline, not a degradation, so excluding them keeps "no alarm" meaningful.
_EXPECTED_OFF_SOURCES = {"gex", "valuation"}
_LOCAL_TZ = ZoneInfo("Asia/Shanghai")

# Soft sources backed by live market data (ETF price ratios / index levels).
# These update on every trading day; staleness is immediately actionable.
_ONLINE_SOFT_SOURCES = {
    "credit_etf", "concentration", "defensive_rotation",
    "financial_stress", "ndx_concentration", "move",
}

_LAYER_LABELS = {
    "strategy_data": "策略数据",
    "position_reconciliation": "持仓对账",
    "auxiliary_flows": "辅助资金流",
    "operations": "运行维护",
}


def runtime_release_identity(package_root: Optional[Path] = None) -> Dict[str, Any]:
    """Read the current R6 identity without mutating runtime state."""
    root = Path(package_root or Path(__file__).resolve().parents[1])
    version_path = root / "VERSION"
    attestation_path = root / "LIVE_CONFIG_ATTESTATION.json"
    policy_path = root / "governance" / "approved_live_config.json"
    if not version_path.is_file() and not attestation_path.is_file():
        return {}
    try:
        fields = version_path.read_text(encoding="utf-8").splitlines()[0].split()
        if not fields or not fields[0]:
            raise ValueError(f"invalid VERSION: {version_path}")
        release_hash = fields[0]
        attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
        policy_sha256 = hashlib.sha256(policy_path.read_bytes()).hexdigest()
        if str(attestation.get("release_hash") or "") != release_hash:
            raise ValueError("VERSION and live attestation release hash differ")
        if str(attestation.get("policy_sha256") or "") != policy_sha256:
            raise ValueError("live attestation and policy sha256 differ")
        attested_at = str(attestation.get("generated_at") or "")
        if _parse_timestamp(attested_at) is None:
            raise ValueError("live attestation generated_at is missing or invalid")
        return {
            "status": "VERIFIED",
            "release_hash": release_hash,
            "policy_sha256": policy_sha256,
            "attested_at": attested_at,
        }
    except Exception as exc:
        return {"status": "INVALID", "error": str(exc)}


def post_deploy_certification(
    report: Any,
    runtime_identity: Any,
) -> Dict[str, Any]:
    """Classify immutable health evidence against the currently deployed code."""
    if not isinstance(runtime_identity, dict) or not runtime_identity:
        return {"status": "UNINSTRUMENTED"}
    if str(runtime_identity.get("status") or "VERIFIED") == "INVALID":
        return {
            "status": "RUNTIME_IDENTITY_INVALID",
            "detail": str(runtime_identity.get("error") or "runtime identity invalid"),
        }
    if not isinstance(report, dict) or not report:
        return {"status": "NO_BOUND_REPORT"}
    current_release = str(runtime_identity.get("release_hash") or "")
    current_policy = str(runtime_identity.get("policy_sha256") or "")
    report_release = str(report.get("generator_release_hash") or "")
    report_policy = str(report.get("generator_policy_sha256") or "")
    base = {
        "report_generator_release_hash": report_release or None,
        "report_generator_policy_sha256": report_policy or None,
        "current_release_hash": current_release or None,
        "current_policy_sha256": current_policy or None,
        "report_generated_at": report.get("generated_at"),
        "current_attested_at": runtime_identity.get("attested_at"),
    }
    report_time = _parse_timestamp(report.get("generated_at"))
    attested_at = _parse_timestamp(runtime_identity.get("attested_at"))
    next_scheduled_at = _next_natural_daily_at(attested_at)
    base["next_scheduled_at"] = (
        next_scheduled_at.isoformat() if next_scheduled_at is not None else None
    )
    generator_matches = bool(
        current_release
        and current_policy
        and report_release == current_release
        and report_policy == current_policy
    )
    if (
        report_time is not None
        and attested_at is not None
        and report_time < attested_at
    ):
        return {"status": "PENDING_POST_DEPLOY", **base}
    if (
        report_time is not None
        and next_scheduled_at is not None
        and report_time < next_scheduled_at
        and generator_matches
    ):
        return {"status": "PENDING_POST_DEPLOY", **base}
    if (
        report_time is not None
        and next_scheduled_at is not None
        and report_time >= next_scheduled_at
        and generator_matches
    ):
        return {"status": "CERTIFIED", **base}
    return {"status": "GENERATOR_MISMATCH", **base}


def _next_natural_daily_at(attested_at: Optional[datetime]) -> Optional[datetime]:
    if attested_at is None:
        return None
    local = attested_at.astimezone(_LOCAL_TZ)
    candidate = datetime.combine(local.date(), time(7, 10), tzinfo=_LOCAL_TZ)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate


class _HealthEvaluator:
    """Evaluate health rules while keeping the public entry point small."""

    def __init__(
        self,
        payload: Dict[str, Any],
        manifest_status: Optional[Dict[str, Any]],
        today: Optional[date],
        now: Optional[datetime],
        ibkr_max_age_seconds: float,
        receipt_timeout_seconds: float,
        receipt_max_age_seconds: float,
    ) -> None:
        self.manifest_status = manifest_status or {}
        self.today = today or date.today()
        self.now = now or datetime.now(timezone.utc)
        if self.now.tzinfo is None:
            self.now = self.now.replace(tzinfo=timezone.utc)
        self.ibkr_max_age_seconds = ibkr_max_age_seconds
        self.receipt_timeout_seconds = receipt_timeout_seconds
        self.receipt_max_age_seconds = receipt_max_age_seconds
        self.checks: List[Dict[str, str]] = []

        self.cache = payload.get("cache_status") or {}
        self.as_of = str(payload.get("as_of", ""))[:10]
        self.breakdown = payload.get("data_quality_breakdown") or {}
        self.ibkr = payload.get("ibkr") or {}
        self.data_quality = payload.get("data_quality") or {}
        self.receipt = payload.get("run_receipt") or {}
        self.sip_flow = payload.get("alpaca_daily_flow") or {}
        self.sip_status = payload.get("alpaca_daily_flow_status") or {}
        self.external_sources = payload.get("external_source_status") or {}
        self.market_admission = payload.get("market_admission_status") or {}

        runtime_identity = payload.get("runtime_release_identity")
        if not isinstance(runtime_identity, dict):
            runtime_identity = runtime_release_identity()
        self.certification = post_deploy_certification(
            payload.get("system_health_report"),
            runtime_identity,
        )
        self.retired_soft_names = (
            {
                "naaim"
                for source_id, row in self.external_sources.items()
                if source_id == "naaim_exposure"
                and isinstance(row, dict)
                and str(row.get("lifecycle_status") or "") == "RETIRED_PAYWALL"
            }
            if isinstance(self.external_sources, dict)
            else set()
        )
        self.stale = (
            _completed_trading_days_after(self.as_of, self.today)
            if self.as_of
            else 99
        )
        self.receipt_status = str(
            self.receipt.get("status")
            or (
                "OK"
                if self.receipt.get("ok")
                else "FAILED"
                if self.receipt
                else "MISSING"
            )
        )
        self.receipt_age: Optional[float] = None
        self.ibkr_age: Optional[float] = None
        self.sip_as_of = ""

    def evaluate(self) -> Dict[str, Any]:
        self._check_scored_payload()
        self._check_price_freshness()
        self._check_manifest()
        self._check_market_admission()
        self._check_data_quality()
        self._check_soft_sources()
        self._check_receipt()
        self._check_ibkr()
        self._check_sip()
        self._check_external_sources()
        self._check_certification()

        layers = _layers(self.checks)
        overall = layers["strategy_data"]["level"]
        return {
            "level": overall,
            "layers": layers,
            "as_of": self.as_of,
            "stale_trading_days": self.stale,
            "receipt_status": self.receipt_status,
            "receipt_age_seconds": self.receipt_age,
            "ibkr_age_seconds": self.ibkr_age,
            "sip_as_of": self.sip_as_of,
            "post_deploy_certification": self.certification,
            "checks": self.checks,
            "summary": _summary(overall, self.checks),
        }

    def _add(
        self,
        level: str,
        label: str,
        detail: str = "",
        layer: str = "strategy_data",
    ) -> None:
        self.checks.append(
            {"level": level, "label": label, "detail": detail, "layer": layer}
        )

    def _check_scored_payload(self) -> None:
        if not self.cache.get("hit"):
            self._add(
                "CRITICAL",
                "无评分缓存",
                "NO_CACHE — 点『更新策略数据』或跑 run_daily",
            )

    def _check_price_freshness(self) -> None:
        if not self.as_of:
            return
        if self.stale >= 3:
            self._add(
                "CRITICAL",
                f"行情陈旧 {self.stale} 个交易日",
                f"as_of={self.as_of}",
            )
        elif self.stale >= 1:
            self._add(
                "DEGRADED",
                f"行情落后 {self.stale} 个交易日",
                f"as_of={self.as_of}",
            )

    def _check_manifest(self) -> None:
        status = str(self.manifest_status.get("status") or "")
        if status == "DRIFT":
            self._add("CRITICAL", "数据清单漂移", "manifest 与历史 CSV 不一致")
        elif status == "MISSING":
            self._add("DEGRADED", "数据清单缺失", "")

    def _check_market_admission(self) -> None:
        """Keep uncertain market candidates frozen and visibly classified."""
        mode = str(self.market_admission.get("mode") or "")
        status = str(self.market_admission.get("status") or "")
        if mode != "enforce_consensus":
            return
        if status == "FETCH_ERROR":
            self._add(
                "DEGRADED",
                "双源行情见证不可用",
                str(
                    self.market_admission.get("fetch_error")
                    or "Alpaca witness unavailable"
                )[:160],
            )
        elif status == "ERROR":
            self._add(
                "DEGRADED",
                "双源行情准入失败",
                str(
                    self.market_admission.get("run_error")
                    or "market admission failed"
                )[:160],
            )
        elif status == "MISSING":
            self._add(
                "DEGRADED",
                "双源行情准入证据缺失",
                str(
                    self.market_admission.get("reason")
                    or "required market admission evidence is missing"
                )[:160],
            )
        elif status == "STALE":
            self._add(
                "DEGRADED",
                "双源行情准入证据过期",
                str(
                    self.market_admission.get("evidence_detail")
                    or "market admission evidence is stale"
                )[:160],
            )
        elif status == "SUPERSEDED_BY_NEWER_DATA":
            self._add(
                "DEGRADED",
                "官方评分已有更新行情待重跑",
                str(
                    self.market_admission.get("evidence_detail")
                    or "newer certified market data is available"
                )[:160],
            )
        elif status == "EVIDENCE_DRIFT":
            self._add(
                "CRITICAL",
                "双源行情证据漂移",
                str(
                    self.market_admission.get("evidence_detail")
                    or "canonical history no longer matches evidence"
                )[:160],
            )
        elif status == "BLOCKED":
            self._add_blocked_market_admission()

    def _add_blocked_market_admission(self) -> None:
        summary = self.market_admission.get("summary") or {}
        summary_text = ", ".join(
            f"{key}={value}" for key, value in sorted(summary.items())
        )
        evidence_parts = []
        for label, field in (
            ("price", "price_evidence_summary"),
            ("volume", "volume_evidence_summary"),
        ):
            evidence = self.market_admission.get(field) or {}
            if evidence:
                values = ",".join(
                    f"{key}={value}" for key, value in sorted(evidence.items())
                )
                evidence_parts.append(f"{label}[{values}]")
        evidence_text = " ".join(evidence_parts) or summary_text
        rejected_detail = _market_admission_rejected_detail(
            self.market_admission.get("rows") or [],
            self.market_admission.get("third_source_shadow") or {},
        )
        detail = " · ".join(
            part for part in (rejected_detail, evidence_text) if part
        )
        component_only = _market_admission_is_component_only(self.market_admission)
        self._add(
            "DEGRADED",
            (
                "穿透成分行情候选已隔离"
                if component_only
                else "双源行情候选已隔离"
            ),
            (
                f"rejected={self.market_admission.get('rejected_rows', 0)} "
                f"{detail}"
            ).strip()[:240],
            "auxiliary_flows" if component_only else "strategy_data",
        )

    def _check_data_quality(self) -> None:
        level = str(self.data_quality.get("level") or "")
        if level in {"LOW", "BLOCKED", "NO_CACHE"}:
            self._add(
                "CRITICAL",
                f"数据质量 {level}",
                f"overall={self.data_quality.get('overall_score')}",
            )
        elif level == "MEDIUM":
            self._add("DEGRADED", "数据质量 MEDIUM", "")

    def _check_soft_sources(self) -> None:
        buckets: Dict[str, List[str]] = {
            "stale_critical": [],
            "stale_degraded": [],
            "missing_unexpected": [],
            "research_unready": [],
            "auxiliary_unready": [],
        }
        for source in self.breakdown.get("sources") or []:
            classified = self._classify_soft_source(source)
            if classified is not None:
                bucket, name = classified
                buckets[bucket].append(name)
        for bucket, level, label, layer, include_count in (
            ("stale_critical", "CRITICAL", "在线软数据源过期", "strategy_data", True),
            ("stale_degraded", "DEGRADED", "软数据源过期", "strategy_data", True),
            ("missing_unexpected", "DEGRADED", "软数据源意外缺失", "strategy_data", True),
            ("research_unready", "INFO", "研究数据源未就绪", "auxiliary_flows", False),
            ("auxiliary_unready", "INFO", "辅助数据源未就绪", "auxiliary_flows", False),
        ):
            names = buckets[bucket]
            if not names:
                continue
            self._add(
                level,
                f"{label} {len(names)}" if include_count else label,
                ", ".join(names[:6]),
                layer,
            )

    def _classify_soft_source(
        self,
        source: Dict[str, Any],
    ) -> Optional[tuple[str, str]]:
        name = str(source.get("name") or "")
        status = str(source.get("status") or "")
        reason = str(source.get("reason") or "")
        if status != "MISSING":
            return None
        if name in _EXPECTED_OFF_SOURCES or name in self.retired_soft_names:
            return None
        if "feature disabled" in reason:
            return None
        decision_role = str(source.get("decision_role") or "strategy")
        if decision_role == "research":
            return "research_unready", name
        if decision_role == "auxiliary":
            return "auxiliary_unready", name
        if "stale" in reason:
            bucket = (
                "stale_critical"
                if name in _ONLINE_SOFT_SOURCES
                else "stale_degraded"
            )
            return bucket, name
        return "missing_unexpected", name

    def _check_receipt(self) -> None:
        """Validate the 07:10 receipt, which is written every calendar day."""
        receipt_time = _parse_timestamp(
            self.receipt.get("finished_at") or self.receipt.get("run_at")
        )
        receipt_started = _parse_timestamp(
            self.receipt.get("started_at") or self.receipt.get("run_at")
        )
        self.receipt_age = _age_seconds(receipt_time, self.now)
        if self.receipt_status == "MISSING":
            self._add("CRITICAL", "今日官方 run 无回执", "scheduled receipt missing")
        elif str(self.receipt.get("run_type") or "") != "scheduled":
            self._add(
                "CRITICAL",
                "官方 run 回执类型异常",
                f"run_type={self.receipt.get('run_type')}",
            )
        elif self.receipt_status == "FAILED":
            detail = str(self.receipt.get("failed_step") or "unknown")
            error = str(self.receipt.get("error") or "")
            self._add(
                "CRITICAL",
                "官方 run 失败",
                f"step={detail} {error}".strip()[:160],
            )
        elif self.receipt_status == "RUNNING":
            running_age = _age_seconds(receipt_started, self.now)
            if (
                running_age is None
                or running_age > self.receipt_timeout_seconds
            ):
                self._add(
                    "CRITICAL",
                    "官方 run 超时",
                    f"running_age_seconds={running_age}",
                )
            else:
                self._add(
                    "DEGRADED",
                    "官方 run 正在执行",
                    f"running_age_seconds={running_age:.0f}",
                )
        elif self.receipt_status == "OK":
            if not self.receipt.get("ok"):
                self._add(
                    "CRITICAL",
                    "官方 run 自检失败",
                    "receipt status=OK but ok=false",
                )
            elif (
                self.receipt_age is None
                or self.receipt_age > self.receipt_max_age_seconds
            ):
                self._add(
                    "CRITICAL",
                    "官方 run 已停摆",
                    f"last_run={self.receipt.get('run_at')}",
                )
        else:
            self._add("CRITICAL", "官方 run 回执状态未知", self.receipt_status)

    def _check_ibkr(self) -> None:
        """Expose reconciliation age without downgrading strategy health."""
        source = str(self.ibkr.get("source") or "")
        ibkr_time = _parse_timestamp(self.ibkr.get("sync_time"))
        self.ibkr_age = _age_seconds(ibkr_time, self.now)
        if source in {"", "unavailable", "disabled"}:
            self._add(
                "INFO",
                "IBKR 未连接",
                str(self.ibkr.get("error") or "")[:60],
                "position_reconciliation",
            )
        elif self.ibkr_age is None:
            self._add(
                "INFO",
                "IBKR 快照时间缺失",
                f"source={source}",
                "position_reconciliation",
            )
        elif self.ibkr_age > max(float(self.ibkr_max_age_seconds), 0.0):
            self._add(
                "INFO",
                "IBKR 快照陈旧",
                (
                    f"age={self.ibkr_age:.0f}s "
                    f"max={self.ibkr_max_age_seconds:.0f}s"
                ),
                "position_reconciliation",
            )

    def _check_sip(self) -> None:
        """Treat SIP evidence as auxiliary even when unavailable or stale."""
        self.sip_as_of = str(self.sip_flow.get("as_of") or "")[:10]
        if str(self.sip_status.get("status") or "") in {"ERROR", "MISSING"}:
            self._add(
                "DEGRADED",
                "SIP 资金流不可用",
                str(
                    self.sip_status.get("error")
                    or self.sip_status.get("status")
                    or ""
                )[:120],
                "auxiliary_flows",
            )
        elif self.sip_flow and self.sip_as_of:
            sip_stale = _completed_trading_days_after(
                self.sip_as_of,
                self.today,
            )
            if sip_stale >= 1:
                self._add(
                    "DEGRADED",
                    "SIP 资金流陈旧",
                    f"as_of={self.sip_as_of} stale={sip_stale}d",
                    "auxiliary_flows",
                )

    def _check_external_sources(self) -> None:
        """Separate refresh machinery failures from canonical freshness."""
        if not isinstance(self.external_sources, dict):
            return
        for source_id, row in self.external_sources.items():
            self._check_external_source(source_id, row)

    def _check_external_source(self, source_id: Any, row: Any) -> None:
        if not isinstance(row, dict) or row.get("active") is False:
            return
        profile = profile_for(str(source_id))
        decision_role = str(
            row.get("decision_role")
            or (profile.decision_role if profile is not None else "strategy")
        )
        source_layer = (
            "strategy_data"
            if decision_role in {"strategy", "hard_gate"}
            else "auxiliary_flows"
        )
        failure_level = "INFO" if decision_role == "research" else "DEGRADED"
        evidence_critical_level = (
            "CRITICAL"
            if decision_role in {"strategy", "hard_gate"}
            else failure_level
        )
        evidence = canonical_evidence_issue(row)
        if evidence:
            self._add_external_evidence(
                source_id,
                row,
                evidence,
                source_layer,
                failure_level,
                evidence_critical_level,
            )
            return

        status = str(row.get("status") or "")
        attempt_status = str(row.get("latest_attempt_status") or status)
        if str(row.get("lifecycle_status") or "") == "RETIRED_PAYWALL":
            self._add_retired_external_source(source_id, row, attempt_status)
            return
        if self._add_failed_external_attempt(
            source_id,
            row,
            attempt_status,
            decision_role,
            source_layer,
            failure_level,
        ):
            return
        self._add_external_status(
            source_id,
            row,
            status,
            profile,
            source_layer,
            failure_level,
        )

    def _add_external_evidence(
        self,
        source_id: Any,
        row: Dict[str, Any],
        evidence: str,
        source_layer: str,
        failure_level: str,
        evidence_critical_level: str,
    ) -> None:
        detail = (
            f"{source_id}: {evidence} {row.get('evidence_detail') or ''}"
        ).strip()
        if evidence in CANONICAL_EVIDENCE_CRITICAL_STATUSES:
            self._add(
                evidence_critical_level,
                "外部数据证据失配",
                detail[:160],
                source_layer,
            )
        else:
            self._add(
                failure_level,
                "外部数据证据未绑定",
                detail[:160],
                source_layer,
            )

    def _add_retired_external_source(
        self,
        source_id: Any,
        row: Dict[str, Any],
        attempt_status: str,
    ) -> None:
        reason = str(row.get("lifecycle_reason") or "certified history frozen")
        if attempt_status not in {"", "OK"}:
            detail = f"{source_id}: {attempt_status} {reason}".strip()
            checked_today = timestamp_to_shanghai_date(
                row.get("latest_attempt_finished_at") or row.get("finished_at")
            ) == self.today
            if checked_today:
                self._add(
                    "DEGRADED",
                    "退役外部源每周探测失败（认证历史冻结）",
                    detail[:160],
                    "operations",
                )
            else:
                self._add(
                    "INFO",
                    "外部数据源已付费退役（上次探测失败）",
                    detail[:160],
                    "operations",
                )
            return
        self._add(
            "INFO",
            "外部数据源已付费退役",
            f"{source_id}: {reason}"[:160],
            "operations",
        )

    def _add_failed_external_attempt(
        self,
        source_id: Any,
        row: Dict[str, Any],
        attempt_status: str,
        decision_role: str,
        source_layer: str,
        failure_level: str,
    ) -> bool:
        if attempt_status == "MISSING":
            self._add(
                failure_level,
                "外部数据源未自动刷新",
                str(source_id),
                source_layer,
            )
            return True
        if attempt_status in {"", "OK"}:
            return False

        attempt_error = (
            row.get("latest_attempt_error_message")
            or row.get("latest_attempt_error_type")
            or row.get("error_message")
            or row.get("error")
            or ""
        )
        detail = f"{source_id}: {attempt_status} {attempt_error}".strip()
        if certified_canonical_is_current(row):
            operational_level = (
                "INFO" if decision_role == "research" else "DEGRADED"
            )
            self._add(
                operational_level,
                "外部数据源刷新失败（认证缓存仍有效）",
                detail[:160],
                "operations",
            )
        else:
            self._add(
                failure_level,
                "外部数据源刷新失败",
                detail[:160],
                source_layer,
            )
        return True

    def _add_external_status(
        self,
        source_id: Any,
        row: Dict[str, Any],
        status: str,
        profile: Any,
        source_layer: str,
        failure_level: str,
    ) -> None:
        freshness = str(row.get("freshness_status") or "")
        if status == "OK" and freshness == "STALE":
            detail = (
                f"{source_id}: age={row.get('age_days')}d "
                f"{row.get('next_action') or ''}"
            ).strip()
            if _verified_policy_stale_after_refresh(
                row,
                profile=profile,
                today=self.today,
            ):
                self._add(
                    "DEGRADED",
                    "外部数据发布延迟（官方已核验）",
                    detail[:160],
                    "operations",
                )
            else:
                self._add(
                    failure_level,
                    "外部数据源陈旧",
                    detail[:160],
                    source_layer,
                )
            return
        if status == "OK":
            return
        if status == "MISSING":
            self._add(
                failure_level,
                "外部数据源未自动刷新",
                str(source_id),
                source_layer,
            )
            return
        detail = (
            f"{source_id}: {status} "
            f"{row.get('error_message') or row.get('error') or ''}"
        ).strip()
        self._add(
            failure_level,
            "外部数据源刷新失败",
            detail[:160],
            source_layer,
        )

    def _check_certification(self) -> None:
        status = str(self.certification.get("status") or "")
        if status == "PENDING_POST_DEPLOY":
            self._add(
                "INFO",
                "新版本待自然日跑再认证",
                (
                    f"report={self.certification.get('report_generator_release_hash') or 'legacy'} "
                    f"live={self.certification.get('current_release_hash') or 'unknown'}"
                ),
                "operations",
            )
        elif status in {"GENERATOR_MISMATCH", "RUNTIME_IDENTITY_INVALID"}:
            self._add(
                "CRITICAL",
                "健康报告生成器身份异常",
                str(self.certification.get("detail") or status),
            )


def compute_health(
    payload: Dict[str, Any],
    manifest_status: Optional[Dict[str, Any]] = None,
    today: Optional[date] = None,
    now: Optional[datetime] = None,
    ibkr_max_age_seconds: float = 15 * 60,
    receipt_timeout_seconds: float = 2 * 60 * 60,
    receipt_max_age_seconds: float = 26 * 60 * 60,
) -> Dict[str, Any]:
    """Evaluate health without exposing the rule engine's internal state."""
    return _HealthEvaluator(
        payload=payload,
        manifest_status=manifest_status,
        today=today,
        now=now,
        ibkr_max_age_seconds=ibkr_max_age_seconds,
        receipt_timeout_seconds=receipt_timeout_seconds,
        receipt_max_age_seconds=receipt_max_age_seconds,
    ).evaluate()

def _verified_policy_stale_after_refresh(
    row: Dict[str, Any],
    *,
    profile: Any,
    today: date,
) -> bool:
    if profile is None or not bool(profile.warn_only_stale_after_refresh):
        return False
    if str(row.get("latest_attempt_status") or row.get("status") or "") != "OK":
        return False
    if timestamp_to_shanghai_date(
        row.get("latest_attempt_finished_at") or row.get("finished_at")
    ) != today:
        return False
    if str(row.get("latest_publisher_calendar_status") or "") != "VERIFIED":
        return False
    expected = str(row.get("latest_expected_release_status") or "")
    grace = str(row.get("latest_expected_release_grace_status") or "")
    return expected == "ADVANCED" and grace == "MATCHED"


def _layers(checks: List[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for key, label in _LAYER_LABELS.items():
        subset = [c for c in checks if c.get("layer", "strategy_data") == key]
        out[key] = {
            "label": label,
            "level": _level_from_checks(subset),
            "checks": subset,
        }
    return out


def _market_admission_rejected_detail(rows: Any, shadow: Any = None) -> str:
    if not isinstance(rows, list):
        return ""
    shadow_support = _market_admission_shadow_support(shadow)
    for row in rows:
        detail = _format_market_admission_rejected_row(row, shadow_support)
        if detail:
            return detail
    return ""


def _market_admission_shadow_support(shadow: Any) -> dict[tuple[str, str], str]:
    support_by_key: dict[tuple[str, str], str] = {}
    if not isinstance(shadow, dict):
        return support_by_key
    for item in shadow.get("rows") or []:
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("symbol") or ""),
            str(item.get("date") or "")[:10],
        )
        support = str(item.get("third_source_support") or "")
        if all(key) and support:
            support_by_key[key] = support
    return support_by_key


def _format_market_admission_rejected_row(
    row: Any,
    shadow_support: dict[tuple[str, str], str],
) -> str:
    if not isinstance(row, dict):
        return ""
    if row.get("admitted") is not False or row.get("blocking") is False:
        return ""
    symbol = str(row.get("symbol") or "?")
    day = str(row.get("date") or "?")[:10]
    status = str(row.get("status") or "UNKNOWN")
    parts = [f"{symbol} {day} {status}"]
    price_status = row.get("price_evidence_status")
    if price_status:
        parts.append(f"price={price_status}")
    volume_detail = _format_market_admission_volume_diff(
        row.get("volume_diff_pct")
    )
    if volume_detail:
        parts.append(volume_detail)
    support = shadow_support.get((symbol, day), "")
    if support:
        parts.append(f"third={support}")
    return " ".join(parts)


def _format_market_admission_volume_diff(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"volume diff={float(value):.4f}%"
    except (TypeError, ValueError):
        return ""


def _market_admission_is_component_only(payload: Dict[str, Any]) -> bool:
    rejected_value = payload.get("rejected_rows")
    strategy_rejected_value = payload.get("strategy_blocking_rejected_rows")
    component_rejected_value = payload.get("component_flow_rejected_rows")
    if (
        rejected_value is None
        or strategy_rejected_value is None
        or component_rejected_value is None
    ):
        return False
    try:
        rejected = int(rejected_value)
        strategy_rejected = int(strategy_rejected_value)
        component_rejected = int(component_rejected_value)
    except (TypeError, ValueError):
        return False
    if rejected <= 0 or strategy_rejected != 0 or component_rejected != rejected:
        return False
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return False
    rejected_rows = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("admitted") is False
        and row.get("blocking") is not False
    ]
    return len(rejected_rows) == rejected and all(
        row.get("decision_impact") == "COMPONENT_FLOW_ONLY"
        and set(row.get("decision_roles") or []) == {"component_flow"}
        for row in rejected_rows
    )


def _level_from_checks(checks: List[Dict[str, str]]) -> str:
    if any(c.get("level") == "CRITICAL" for c in checks):
        return "CRITICAL"
    if any(c.get("level") == "DEGRADED" for c in checks):
        return "DEGRADED"
    if any(c.get("level") == "INFO" for c in checks):
        return "INFO"
    return "OK"


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


def _age_seconds(value: Optional[datetime], now: datetime) -> Optional[float]:
    if value is None:
        return None
    return max(0.0, (now - value.astimezone(now.tzinfo)).total_seconds())


def _summary(level: str, checks: List[Dict[str, str]]) -> str:
    if level == "OK":
        return "策略数据正常：行情新鲜、数据清单一致、数据质量达标。"
    crit = [c["label"] for c in checks if c["level"] == "CRITICAL" and c.get("layer", "strategy_data") == "strategy_data"]
    deg = [c["label"] for c in checks if c["level"] == "DEGRADED" and c.get("layer", "strategy_data") == "strategy_data"]
    parts = []
    if crit:
        parts.append("严重：" + "、".join(crit))
    if deg:
        parts.append("降级：" + "、".join(deg))
    return "；".join(parts)
