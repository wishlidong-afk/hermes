from __future__ import annotations

from typing import Any, Mapping


def external_reliability_text(row: Mapping[str, Any]) -> str:
    rate_30 = row.get("success_rate_30d")
    rate_90 = row.get("success_rate_90d")
    samples = int(row.get("samples_30d") or 0)
    samples_90 = int(row.get("samples_90d") or 0)
    failures = int(row.get("consecutive_failures") or 0)
    if rate_30 is None and rate_90 is None:
        return "可靠性：尚无日级样本"
    parts = [
        f"30d {_reliability_rate_text(rate_30, samples)}",
        f"90d {_reliability_rate_text(rate_90, samples_90)}",
        f"连续失败 {failures}",
    ]
    channel = str(row.get("latest_source_channel") or "").strip()
    if channel:
        parts.append(f"渠道 {channel}")
    primary = str(row.get("latest_primary_source") or "").strip()
    if primary and primary != channel:
        parts.append(f"主源 {primary}")
    primary_failure = str(row.get("latest_primary_failure") or "").strip()
    if primary_failure:
        parts.append(f"主源失败 {primary_failure}")
    rescues = int(row.get("fallback_rescues_7d") or 0)
    if rescues:
        parts.append(f"7d fallback 救回 {rescues}")
    primary_rate = row.get("primary_success_rate_30d")
    if primary_rate is not None:
        parts.append(
            f"主源 30d {_reliability_rate_text(primary_rate, int(row.get('primary_samples_30d') or 0))}"
        )
    stages = row.get("stage_reliability")
    if isinstance(stages, Mapping):
        labels = (("transport", "T"), ("parse", "P"), ("validation", "V"), ("promotion", "R"))
        stage_parts = []
        for stage, label in labels:
            metrics = stages.get(stage)
            if not isinstance(metrics, Mapping) or metrics.get("success_rate_30d") is None:
                continue
            stage_parts.append(
                f"{label}{_reliability_rate_text(metrics.get('success_rate_30d'), int(metrics.get('samples_30d') or 0), compact=True)}"
            )
        if stage_parts:
            parts.append("四段 " + "/".join(stage_parts))
    advancement_rate = row.get("advancement_rate_30d")
    if advancement_rate is not None:
        parts.append(
            f"推进 {_reliability_rate_text(advancement_rate, int(row.get('advancement_samples_30d') or 0))}"
        )
    expected_date = str(row.get("latest_expected_release_date") or "").strip()
    expected_status = str(row.get("latest_expected_release_status") or "").strip()
    if expected_date and expected_status:
        parts.append(f"应发 {expected_date} {expected_status}")
    return " · ".join(parts)


def _reliability_rate_text(rate: Any, samples: int, *, compact: bool = False) -> str:
    if int(samples) < 5:
        return f"不足(n={int(samples)})" if compact else f"INSUFFICIENT_EVIDENCE (n={int(samples)})"
    if rate is None:
        return f"无比率(n={int(samples)})" if compact else f"rate unavailable (n={int(samples)})"
    formatted = _fmt_num(rate)
    return f"{formatted}(n={int(samples)})" if compact else f"{formatted}% (n={int(samples)})"


def _fmt_num(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "NA"
