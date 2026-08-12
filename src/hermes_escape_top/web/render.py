from __future__ import annotations

import json
from datetime import date
from html import escape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..core.data.external_sources.ledger import (
    canonical_evidence_issue,
    certified_canonical_is_current,
)
from ..core.data.external_sources.profiles import display_source_ids, profile_for
from ..core.reporting.system_health import decision_input_lifecycle
from ..core.safe_io import atomic_write_text
from ..core.scoring.explain_registry import explain_factor
from ..core.scoring.module_a import module_a_factors
from ..core.scoring.module_b import module_b_factors
from ..core.scoring.module_c import module_c_factors
from ..core.scoring.module_d import module_d_factors
from .external_source_view import external_reliability_text


TRADE_SYMBOLS = ["MSTR", "FNGU", "SOXL"]
REPO_ROOT = Path(__file__).resolve().parents[3]

FACTOR_MODULE_LABELS = {
    "A": "A 宏观/市场温度",
    "B": "B 标的过热/估值",
    "C": "C 结构破坏/技术确认",
    "D": "D 个股/资产自身风险",
}

TRUST_SOURCE_LABELS = {
    "aaii": "aaii_sentiment",
    "cboe_pcr": "cboe_equity_pcr",
    "naaim": "naaim_exposure",
    "net_liquidity": "fred_net_liquidity",
}
TRUST_SOURCE_ALIASES = {value: key for key, value in TRUST_SOURCE_LABELS.items()}
TRUST_SOURCE_ORDER = [
    "cot_nq",
    "real_rate",
    "cboe_pcr",
    "net_liquidity",
    "dollar",
    "occ_equity_pcr",
    "aaii",
    "naaim",
]
EXTERNAL_SOURCE_ORDER = list(display_source_ids())
EXTERNAL_SOURCE_LABELS = {
    source_id: profile_for(source_id).label
    for source_id in EXTERNAL_SOURCE_ORDER
    if profile_for(source_id) is not None
}

RUNBOOK_REFS = {
    "normal": ("runbook-normal", "正常运行", "确认 run_daily/watchdog 成功，检查日报末行、preflight 和 post-run diff。"),
    "data": ("runbook-data", "数据缺失 / 过期", "先补跑 run_daily；若单源过期，按 FRED/AAII/NAAIM/COT 对应命令刷新。"),
    "pending": ("runbook-pending", "Suspect valve PENDING", "坏 tick 嫌疑日不动作，等待次日干净收盘确认；连续 2 天再查源数据。"),
    "ibkr": ("runbook-ibkr", "IBKR 只读连接失败", "确认 TWS/Gateway、端口和 readonly；评分仍有效，但持仓对账不可用。"),
    "gate": ("runbook-gate", "回测 / gate 失败", "FAIL 即归档 Rejected，flag 保持 OFF，不二次调参。"),
    "flag": ("runbook-flag", "Flag 翻闸", "OFF 证明、gate 证据、台账和部署 diff 人工确认齐备后再翻。"),
    "deploy": ("runbook-deploy", "部署 repo -> live", "走 deploy_to_live 备份、rsync、config diff 和 import 对比流程。"),
    "launchd": ("runbook-launchd", "launchd 维护", "用 launchctl print/kickstart 检查 daily/watchdog，停用走 unload。"),
}


def render_dashboard(
    payload: Dict[str, Any],
    manifest_status: Dict[str, Any] | None = None,
    health: Dict[str, Any] | None = None,
) -> str:
    """Render the package-engine dashboard using the new payload schema."""
    manifest_status = manifest_status or {}
    health = health or {}
    as_of = str(payload.get("as_of", ""))
    schema = str(payload.get("schema_version", ""))
    cache = payload.get("cache_status", {})
    data_quality = payload.get("data_quality", {})
    regime = payload.get("regime", {})
    risk = payload.get("portfolio_risk", {})
    ibkr = payload.get("ibkr") or {"source": "disabled"}

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hermes Escape Top / Hermes 逃顶驾驶舱</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --panel: #ffffff;
      --line: #d9dee7;
      --muted: #5f6b7a;
      --text: #111827;
      --blue: #1d4ed8;
      --green: #047857;
      --amber: #b45309;
      --red: #b91c1c;
      --slate: #334155;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      letter-spacing: 0;
    }}
    .shell {{ max-width: 1480px; margin: 0 auto; padding: 18px; }}
    .hero {{
      background: #111827;
      color: white;
      border-radius: 8px;
      padding: 18px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 14px;
      align-items: start;
    }}
    h1 {{ margin: 0 0 8px; font-size: 26px; line-height: 1.15; }}
    h2 {{ margin: 0 0 10px; font-size: 18px; line-height: 1.25; }}
    h3 {{ margin: 0 0 8px; font-size: 15px; line-height: 1.25; }}
    a {{ color: inherit; text-decoration: none; }}
    .subtle {{ color: var(--muted); font-size: 12px; }}
    .hero .subtle {{ color: #cbd5e1; }}
    .controls {{ display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; align-items: center; }}
    button, .button {{
      border: 0;
      border-radius: 6px;
      padding: 8px 12px;
      font-weight: 700;
      cursor: pointer;
      color: white;
      background: var(--slate);
      font-size: 13px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
    }}
    button:disabled {{ opacity: .55; cursor: default; }}
    .btn-primary {{ background: var(--blue); }}
    .btn-position {{ background: #0f766e; }}
    .btn-muted {{ background: #475569; }}
    .btn-mirror {{ background: #7c3aed; }}
    .status-line {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
      background: #e5e7eb;
      color: #374151;
    }}
    .badge.ok {{ background: #d1fae5; color: #065f46; }}
    .badge.warn {{ background: #fef3c7; color: #92400e; }}
    .badge.danger {{ background: #fee2e2; color: #991b1b; }}
    .badge.watch {{ background: #dbeafe; color: #1e40af; }}
    .toolbar-output {{
      display: none;
      margin-top: 12px;
      padding: 10px;
      background: #ecfdf5;
      color: #064e3b;
      border: 1px solid #10b981;
      border-radius: 6px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      white-space: pre-wrap;
      max-height: 220px;
      overflow: auto;
    }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin: 12px 0;
    }}
    .ops-desk {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
      align-items: stretch;
    }}
    .ops-main {{
      border: 1px solid #dbe3ee;
      border-radius: 8px;
      padding: 12px;
      background: #f8fafc;
    }}
    .ops-headline {{ font-size: 24px; font-weight: 900; margin: 6px 0; }}
    .intent-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }}
    .intent-card {{ border: 1px solid #e5e7eb; border-radius: 8px; background: #fff; padding: 10px; min-width: 0; }}
    .intent-card {{ overflow: hidden; }}
    .intent-card b {{ font-size: 16px; }}
    .intent-card .action {{ font-weight: 900; margin-top: 8px; color: #0f172a; }}
    .intent-card .target {{ color: var(--muted); font-size: 12px; margin-top: 5px; }}
    .intent-card .plain-command {{
      margin-top: 8px;
      padding: 8px;
      border-radius: 6px;
      background: #f1f5f9;
      color: #0f172a;
      font-size: 13px;
      font-weight: 800;
      line-height: 1.35;
    }}
    .intent-plan {{ margin-top: 8px; font-size: 12px; overflow-x: auto; max-width: 100%; }}
    .intent-plan table {{ font-size: 12px; }}
    .intent-plan th, .intent-plan td {{ padding: 5px 6px; }}
    .trade-buy {{ color: #047857; font-weight: 900; }}
    .trade-sell {{ color: #b91c1c; font-weight: 900; }}
    .trade-hold {{ color: #334155; font-weight: 900; }}
    .kpi, section, .symbol-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .kpi {{ padding: 12px; min-height: 86px; }}
    .kpi .label {{ color: var(--muted); font-size: 12px; margin-bottom: 8px; }}
    .kpi .value {{ font-size: 22px; font-weight: 800; line-height: 1.1; }}
    .kpi .note {{ color: var(--muted); font-size: 12px; margin-top: 6px; }}
    section {{ padding: 14px; margin-bottom: 12px; min-width: 0; }}
    .command-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 12px;
    }}
    .symbol-card {{ overflow: hidden; }}
    .symbol-head {{
      padding: 14px;
      border-bottom: 1px solid var(--line);
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: start;
    }}
    .symbol-title {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
    .symbol-title strong {{ font-size: 22px; }}
    .score {{ font-size: 28px; font-weight: 850; text-align: right; line-height: 1; }}
    .score small {{ display:block; color: var(--muted); font-size: 11px; margin-top: 4px; font-weight: 600; }}
    .symbol-body {{ padding: 14px; display: grid; gap: 12px; }}
    .mini-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
    .metric {{ background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 6px; padding: 9px; min-width: 0; }}
    .metric .label {{ color: var(--muted); font-size: 11px; margin-bottom: 5px; }}
    .metric .value {{ font-size: 15px; font-weight: 800; overflow-wrap: anywhere; }}
    .module-row {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; }}
    .module {{ background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 6px; padding: 8px; }}
    .module b {{ display: block; font-size: 13px; margin-bottom: 6px; }}
    .bar {{ height: 7px; background: #e5e7eb; border-radius: 999px; overflow: hidden; }}
    .bar span {{ display: block; height: 100%; background: #64748b; }}
    .bar span.warn {{ background: #d97706; }}
    .bar span.danger {{ background: #dc2626; }}
    .facts {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }}
    .macro-summary {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }}
    .macro-tile {{
      background: #f8fafc;
      border: 1px solid #dbe3ee;
      border-radius: 6px;
      padding: 8px;
      min-width: 0;
    }}
    .macro-tile .label {{ color: var(--muted); font-size: 11px; margin-bottom: 5px; }}
    .macro-tile .value {{ font-size: 15px; font-weight: 850; overflow-wrap: anywhere; }}
    .macro-factors {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-top: 8px; }}
    .macro-factor {{ border: 1px solid #e5e7eb; border-radius: 6px; background: #fbfdff; padding: 8px; min-width: 0; }}
    .macro-factor b {{ display:block; font-size: 12px; margin-bottom: 4px; overflow-wrap: anywhere; }}
    .macro-factor .pts {{ font-weight: 900; font-size: 15px; }}
    .macro-details {{ margin-top: 8px; }}
    .flow-header {{ display:flex; justify-content:space-between; gap:10px; align-items:flex-start; flex-wrap:wrap; margin: 12px 0 8px; }}
    .flow-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }}
    .flow-card {{ border: 1px solid #e5e7eb; border-radius: 8px; background: #fbfdff; overflow: hidden; }}
    .flow-card .flow-title {{ padding: 10px 12px; border-bottom: 1px solid #e5e7eb; background: #f8fafc; }}
    .flow-card .flow-body {{ padding: 10px; overflow-x: auto; }}
    .flow-money.pos {{ color: #047857; font-weight: 800; }}
    .flow-money.neg {{ color: #b91c1c; font-weight: 800; }}
    .flow-heat-cell {{ text-align:center; font-weight:850; border-radius:5px; }}
    .flow-hot-neg {{ background:#fecaca; color:#991b1b; }}
    .flow-mid-neg {{ background:#fed7aa; color:#9a3412; }}
    .flow-neutral {{ background:#f1f5f9; color:#475569; }}
    .flow-mid-pos {{ background:#bbf7d0; color:#166534; }}
    .flow-hot-pos {{ background:#86efac; color:#065f46; }}
    .tape-flow-block {{ margin-top:16px; padding-top:14px; border-top:1px solid #dbe3ee; }}
    .tape-flow-grid {{ display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:10px; margin-top:10px; }}
    .tape-flow-card {{ border:1px solid #dbe3ee; border-radius:8px; overflow:hidden; background:#fff; min-width:0; }}
    .tape-flow-card .head {{ padding:10px 12px; background:#f8fafc; border-bottom:1px solid #e5e7eb; }}
    .tape-flow-card .body {{ padding:10px; overflow-x:auto; }}
    .tape-split {{ display:flex; height:8px; min-width:90px; border-radius:999px; overflow:hidden; background:#e5e7eb; margin-top:4px; }}
    .tape-split .buy {{ background:#0f766e; }}
    .tape-split .sell {{ background:#e76f51; }}
    .tape-net-buy {{ color:#047857; font-weight:900; }}
    .tape-net-sell {{ color:#b91c1c; font-weight:900; }}
    .tape-net-flat {{ color:#475569; font-weight:900; }}
    .strategy-console {{ display:grid; gap:10px; }}
    .strategy-overview {{
      border:1px solid #dbe3ee;
      border-radius:8px;
      background:#f8fafc;
      padding:12px;
    }}
    .ops-work-card {{ overflow: hidden; }}
    .data-trust-zone summary {{ cursor:pointer; font-weight:850; }}
    .data-trust-zone[open] summary {{ margin-bottom:8px; }}
    .strategy-overview .headline {{ font-size:22px; font-weight:900; margin:5px 0; }}
    .strategy-metrics {{ display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:8px; margin-top:10px; }}
    .strategy-card-grid {{ display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:10px; }}
    .strategy-card {{ border:1px solid #e5e7eb; border-radius:8px; background:#fff; padding:10px; min-width:0; }}
    .strategy-card .big {{ font-size:20px; font-weight:900; line-height:1.1; margin:7px 0; }}
    .strategy-card .mini-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .position-table-wrap {{ overflow-x:auto; }}
    .position-summary-grid {{ display:grid; grid-template-columns:repeat(5, minmax(0, 1fr)); gap:8px; margin-bottom:10px; }}
    .health-strip {{ display:grid; grid-template-columns:repeat(7, minmax(0, 1fr)); gap:7px; margin-bottom:8px; }}
    .health-pill {{
      border:1px solid #e5e7eb;
      border-radius:7px;
      background:#f8fafc;
      padding:8px;
      min-width:0;
      border-left:4px solid #94a3b8;
    }}
    .health-pill.ok {{ border-left-color:#059669; background:#f0fdf4; }}
    .health-pill.warn {{ border-left-color:#d97706; background:#fffbeb; }}
    .health-pill.danger {{ border-left-color:#dc2626; background:#fef2f2; }}
    .health-pill.watch {{ border-left-color:#2563eb; background:#eff6ff; }}
    .health-pill .label {{ color:var(--muted); font-size:11px; margin-bottom:4px; }}
    .health-pill .value {{ font-size:13px; font-weight:900; line-height:1.25; overflow-wrap:anywhere; }}
    .trust-health {{
      border-left: 4px solid #2563eb;
      background: #fff;
    }}
    .trust-summary {{
      border: 1px solid #dbe3ee;
      border-radius: 8px;
      padding: 12px;
      background: #f8fafc;
      margin-bottom: 10px;
    }}
    .trust-compact-head {{
      display:grid;
      grid-template-columns:minmax(190px, .7fr) minmax(0, 1.8fr);
      gap:14px;
      align-items:center;
    }}
    .trust-verdict {{ display:flex; flex-direction:column; gap:6px; align-items:flex-start; }}
    .trust-verdict .action {{ font-size:22px; font-weight:900; line-height:1.15; }}
    .trust-context {{ min-width:0; }}
    .trust-meta {{ display:flex; flex-wrap:wrap; gap:5px 12px; font-size:12px; color:var(--muted); margin-bottom:5px; }}
    .trust-meta b {{ color:#0f172a; }}
    .trust-headline {{ font-size: 18px; font-weight: 900; margin: 4px 0; }}
    .trust-layer-grid {{ display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:8px; margin-bottom:10px; }}
    .trust-status-lanes .mini-note {{ margin-top:5px; }}
    .trust-layer-card {{
      border:1px solid #e5e7eb;
      border-radius:8px;
      background:#fbfdff;
      padding:10px;
      min-width:0;
    }}
    .trust-layer-card.ok {{ border-left:4px solid #059669; background:#f0fdf4; }}
    .trust-layer-card.warn {{ border-left:4px solid #d97706; background:#fffbeb; }}
    .trust-layer-card.danger {{ border-left:4px solid #dc2626; background:#fef2f2; }}
    .trust-warning-list {{ display:grid; gap:7px; margin-bottom:10px; }}
    .trust-warning {{
      border:1px solid #e5e7eb;
      border-radius:8px;
      padding:9px 10px;
      background:#fff;
      font-size:12px;
    }}
    .trust-warning.warn {{ border-color:#fed7aa; background:#fff7ed; }}
    .trust-warning.danger {{ border-color:#fecaca; background:#fef2f2; }}
    .trust-primary-issue {{ margin-bottom:10px; }}
    .trust-primary-issue .issue-head {{ display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:4px; }}
    .trust-primary-issue.ok {{ border-color:#bbf7d0; background:#f0fdf4; }}
    .trust-evidence-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(130px, 1fr)); gap:8px; margin-bottom:10px; }}
    .trust-evidence {{
      border:1px solid #e5e7eb;
      border-radius:7px;
      background:#f8fafc;
      padding:8px;
      min-width:0;
    }}
    .trust-evidence .label {{ color:var(--muted); font-size:11px; margin-bottom:4px; }}
    .trust-evidence .value {{ font-size:13px; font-weight:900; overflow-wrap:anywhere; }}
    .precheck-evidence-card {{
      border:1px solid #dbe3ee;
      border-radius:8px;
      background:#fbfdff;
      padding:10px;
      margin:0 0 10px;
    }}
    .precheck-evidence-head {{ display:flex; justify-content:space-between; gap:10px; align-items:flex-start; flex-wrap:wrap; }}
    .trust-diagnostics {{ border-top:1px solid #dbe3ee; padding-top:8px; margin-top:2px; }}
    .trust-diagnostics > summary {{ cursor:pointer; font-weight:850; color:#1d4ed8; padding:4px 0; }}
    .trust-diagnostics[open] > summary {{ margin-bottom:10px; }}
    .trust-diagnostics-body {{ padding-top:2px; }}
    .trust-diagnostics-title {{ font-size:13px; font-weight:850; margin:4px 0 7px; }}
    .precheck-report-raw summary {{ cursor:pointer; font-weight:850; margin-top:8px; }}
    .precheck-report-raw pre {{
      white-space:pre-wrap;
      overflow:auto;
      margin:8px 0 0;
      padding:10px;
      border-radius:7px;
      background:#0f172a;
      color:#e5e7eb;
      font-size:11px;
      line-height:1.45;
    }}
    .position-action {{ font-weight:900; }}
    .position-action.buy {{ color:#047857; }}
    .position-action.sell {{ color:#b91c1c; }}
    .position-action.hold {{ color:#334155; }}
    .flow-summary-strip {{ display:flex; flex-wrap:wrap; gap:8px; margin:8px 0 10px; }}
    .flow-heat-grid {{ display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:8px; }}
    .flow-heat-item {{ border:1px solid #e5e7eb; border-radius:6px; background:#fff; padding:8px; min-width:0; }}
    .details-strip {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:8px; }}
    .full-detail-block {{ margin-bottom:12px; }}
    .full-detail-block > summary {{ background:#fff; }}
    .full-detail-block section {{ border:0; margin:0; padding:10px; }}
    .workbench-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    .work-card {{ border: 1px solid #e5e7eb; border-radius: 8px; background: #fbfdff; padding: 10px; min-width: 0; }}
    .work-card h3 {{ display:flex; justify-content:space-between; gap:8px; align-items:center; flex-wrap:wrap; }}
    .symbol-strip {{ display: grid; gap: 8px; }}
    .symbol-strip-row {{ border: 1px solid #e5e7eb; border-radius: 6px; background: #fff; padding: 8px; min-width: 0; }}
    .row-head {{ display:flex; justify-content:space-between; gap:8px; align-items:flex-start; flex-wrap:wrap; margin-bottom:6px; }}
    .row-title {{ font-weight:900; }}
    .mini-note {{ color: var(--muted); font-size: 12px; line-height: 1.45; overflow-wrap: anywhere; }}
    .valve-grid {{ display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap:6px; margin-top:6px; }}
    .valve-item {{ border:1px solid #e5e7eb; border-radius:6px; padding:7px; background:#f8fafc; min-width:0; }}
    .valve-item.triggered {{ border-color:#fecaca; background:#fef2f2; }}
    .valve-item.pending, .valve-item.buffered {{ border-color:#fed7aa; background:#fff7ed; }}
    .valve-item.clear {{ background:#f9fafb; }}
    .valve-title {{ display:flex; justify-content:space-between; gap:6px; align-items:flex-start; flex-wrap:wrap; margin-bottom:4px; }}
    .valve-title b {{ overflow-wrap:anywhere; }}
    .valve-metrics {{ color:var(--muted); font-size:11px; line-height:1.4; overflow-wrap:anywhere; }}
    .diff-box {{ max-height: 260px; overflow: auto; border:1px solid #e5e7eb; border-radius:6px; background:#fff; padding:10px; font-size:12px; line-height:1.5; }}
    .diff-box h3 {{ margin-top: 8px; }}
    .diff-box ul {{ margin: 5px 0 8px; padding-left: 18px; }}
    .runbook-mini {{ margin-top: 10px; border-top: 1px solid rgba(0,0,0,.08); padding-top: 8px; display:grid; gap:6px; }}
    .runbook-mini div {{ font-size: 12px; color: var(--muted); }}
    .runbook-mini b {{ color: var(--text); }}
    .risk-bar-row {{ display:grid; grid-template-columns: 72px minmax(0,1fr) 86px; gap:8px; align-items:center; margin:8px 0; font-size:12px; }}
    .risk-bar-label {{ font-weight:900; overflow-wrap:anywhere; }}
    .risk-bar-track {{ height:14px; background:#e5e7eb; border-radius:999px; overflow:hidden; }}
    .risk-bar-fill {{ height:100%; background:#64748b; border-radius:999px; }}
    .stress-grid {{ display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:8px; }}
    .stress-card {{ border:1px solid #e5e7eb; border-radius:6px; background:#fff; padding:8px; min-width:0; }}
    .condition-chain {{ display:grid; gap:8px; }}
    .condition-step {{ border:1px solid #e5e7eb; border-radius:6px; background:#fff; padding:8px; }}
    .condition-step.pass {{ border-color:#86efac; background:#f0fdf4; }}
    .condition-step.fail {{ border-color:#fed7aa; background:#fff7ed; }}
    .condition-step.danger {{ border-color:#fecaca; background:#fef2f2; }}
    .risk-routing-block {{ border:1px solid #e5e7eb; border-radius:8px; background:#fbfdff; padding:10px; margin-top:10px; }}
    .risk-routing-grid {{ display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:10px; }}
    .factor-map details, details.factor-map {{ background:#fbfdff; }}
    .factor-module-row td {{ background:#eef2ff; color:#1e3a8a; font-weight:900; }}
    .evidence-ladder {{ border:1px solid #dbe3ee; border-radius:8px; background:#f8fafc; padding:12px; }}
    .ladder-track {{ position:relative; height:18px; margin:24px 8px 18px; background:#e5e7eb; border-radius:999px; }}
    .ladder-band {{ position:absolute; top:0; bottom:0; border-radius:999px; opacity:.9; }}
    .ladder-marker {{ position:absolute; top:-7px; width:4px; height:32px; border-radius:2px; background:#111827; }}
    .ladder-label {{ position:absolute; top:-21px; transform:translateX(-50%); font-size:10px; color:#64748b; white-space:nowrap; }}
    .ladder-symbol {{ position:absolute; top:24px; transform:translateX(-50%); font-size:11px; font-weight:900; white-space:nowrap; }}
    .radar-row {{ display:grid; grid-template-columns:88px 1fr; gap:10px; align-items:start; border:1px solid #e5e7eb; border-radius:8px; background:#fff; padding:10px; margin-bottom:8px; }}
    .danger-bar {{ height:10px; background:#e5e7eb; border-radius:999px; overflow:hidden; margin:5px 0 6px; }}
    .danger-fill {{ height:100%; background:#dc2626; border-radius:999px; }}
    .matrix-table td {{ text-align:center; }}
    .spark-svg {{ width:100%; max-width:420px; height:58px; display:block; margin-top:6px; }}
    details {{ border: 1px solid #e5e7eb; border-radius: 6px; background: #fbfdff; }}
    summary {{ cursor: pointer; padding: 9px 10px; font-weight: 800; color: #334155; }}
    details .detail-body {{ padding: 0 10px 10px; overflow-x: auto; }}
    .table-scroll {{ max-width: 100%; overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12px; min-width: 0; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 7px 8px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word; }}
    th {{ background: #f1f5f9; color: #334155; font-weight: 800; }}
    tr:last-child td {{ border-bottom: 0; }}
    .two-col {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .two-col > * {{ min-width: 0; }}
    .route-text {{ font-weight: 800; color: #0f172a; }}
    .reason {{ color: var(--muted); font-size: 12px; line-height: 1.45; }}
    .warning-box {{ background:#fff7ed; border:1px solid #fed7aa; border-radius:6px; padding:10px; color:#7c2d12; font-size:12px; }}
    .ibkr-head {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(190px, 250px);
      gap: 10px;
      align-items: stretch;
      margin-bottom: 10px;
    }}
    .ibkr-total-box {{
      background: #f0fdf4;
      border: 1px solid #86efac;
      border-radius: 8px;
      padding: 12px;
      min-width: 0;
    }}
    .ibkr-total-box .label {{ color: #166534; font-size: 12px; font-weight: 800; margin-bottom: 6px; }}
    .ibkr-total-box .amount {{ color: #052e16; font-size: 24px; font-weight: 900; line-height: 1.1; overflow-wrap: anywhere; }}
    .ibkr-total-box .note {{ color: #166534; font-size: 11px; margin-top: 6px; }}
    .ops details {{ background: white; }}
    @media (max-width: 1100px) {{
      .hero {{ grid-template-columns: 1fr; }}
      .controls {{ justify-content: flex-start; }}
      .kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .ops-desk, .intent-grid {{ grid-template-columns: 1fr; }}
      .command-grid {{ grid-template-columns: 1fr; }}
      .two-col {{ grid-template-columns: 1fr; }}
      .ibkr-head {{ grid-template-columns: 1fr; }}
      .macro-summary, .macro-factors {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .flow-grid {{ grid-template-columns: 1fr; }}
      .tape-flow-grid {{ grid-template-columns: 1fr; }}
      .workbench-grid {{ grid-template-columns: 1fr; }}
      .strategy-card-grid, .strategy-metrics, .flow-heat-grid, .position-summary-grid, .health-strip, .risk-routing-grid {{ grid-template-columns: 1fr; }}
      .trust-compact-head {{ grid-template-columns:1fr; }}
      .trust-layer-grid, .trust-evidence-grid {{ grid-template-columns:repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 720px) {{
      .shell {{ padding: 10px; }}
      .kpis, .facts, .mini-grid, .module-row {{ grid-template-columns: 1fr; }}
      .valve-grid, .stress-grid {{ grid-template-columns: 1fr; }}
      .trust-layer-grid, .trust-evidence-grid {{ grid-template-columns:1fr; }}
      .macro-summary, .macro-factors {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      h1 {{ font-size: 22px; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <header class="hero">
      <div>
        <h1>Hermes Escape Top / Hermes 逃顶驾驶舱</h1>
        <div class="subtle">as_of={esc(as_of)} · schema={esc(schema)} · 新系统 package payload</div>
        <div class="status-line">
          {_badge('策略输入 ' + str(data_quality.get('level', 'NA')), _quality_kind(data_quality.get('level')))}
          {_badge('Cache ' + ('hit' if cache.get('hit') else 'live/none'), 'ok' if cache.get('hit') else 'warn')}
          {_badge('IBKR ' + str(ibkr.get('source', 'disabled')), _ibkr_kind(ibkr))}
          {_badge('Regime ' + str(regime.get('current', 'NA')), 'watch')}
        </div>
      </div>
      <div>
        <div class="controls">
          <button class="btn-primary" onclick="refreshScore()" id="refresh-score-btn">更新策略数据</button>
          <button class="btn-position" onclick="refreshPositions()" id="refresh-positions-btn">更新持仓</button>
          <button class="btn-muted" onclick="refreshExternalSources()" id="external-sources-refresh-all-header-btn">刷新全部外部源</button>
          <button class="btn-muted" onclick="location.reload()">重新载入</button>
        </div>
        <div class="subtle" id="refresh-score-status" style="margin-top:8px;text-align:right"></div>
        <div class="subtle" id="refresh-positions-status" style="margin-top:4px;text-align:right"></div>
        <div class="subtle" id="external-source-header-status" style="margin-top:4px;text-align:right"></div>
      </div>
    </header>

    <div id="refresh-result" class="toolbar-output"></div>

    {_render_run_receipt_banner(payload)}
    {_render_preview_banner(payload)}
    {_render_trust_section(payload, manifest_status, health)}
    {_render_cache_hint(cache)}
    {_render_strategy_console(payload, health)}
    {_render_status_history(payload)}
    {_render_evidence_strip(payload)}
    {_render_hard_valve_radar(payload)}
    {_render_position_desk(payload, payload.get("ibkr_history") or [])}

    {_render_component_flow_section(payload)}

    {_render_secondary_details(payload)}
    {_render_bottom_system_ops_details(payload, manifest_status)}

  </div>
  {_render_scripts(as_of)}
</body>
</html>
"""


def write_dashboard(payload: Dict[str, Any], output_path: Path) -> Path:
    atomic_write_text(output_path, render_dashboard(payload))
    return output_path


def _render_strategy_console(payload: Dict[str, Any], health: Dict[str, Any]) -> str:
    ops = payload.get("today_ops") or {}
    scores = payload.get("scores") or {}
    statuses = " | ".join(
        f"{symbol} {esc((scores.get(symbol) or {}).get('status', 'NA'))}"
        for symbol in TRADE_SYMBOLS
    )
    worst_flow = _worst_flow_symbol(payload)
    hard_total = sum(len((scores.get(symbol) or {}).get("hard_valve_hits") or []) for symbol in TRADE_SYMBOLS)
    route_text = _dominant_route_text(payload)
    flow_text = (
        f"{worst_flow['symbol']} {worst_flow['severity']}"
        if worst_flow else "暂无穿透流数据"
    )
    return f"""
    <section>
      <h2>今日操作台 / One Command Desk</h2>
      <div class="strategy-console">
        <div class="strategy-overview">
          <div class="subtle">health {esc((health or {}).get('level', 'NA'))} · advisory only · 不自动下单</div>
          <div class="headline">{esc(ops.get('headline') or '暂无今日策略结论')}</div>
          <div class="subtle">结论：{statuses} · 防守路由：{route_text} · 主要证据：硬阀门 {hard_total} 个 / 穿透流 {esc(flow_text)}</div>
          <div class="strategy-metrics">
            {_metric('动作数', esc(ops.get('action_count', 0)))}
            {_metric('策略输入质量', f"{esc(ops.get('data_quality', 'NA'))} {_fmt_num(ops.get('data_quality_score'))}")}
            {_metric('IBKR', esc(ops.get('ibkr_source', 'NA')) + (' / STALE' if ops.get('ibkr_stale') else ''))}
            {_metric('资金流最弱桶', esc(flow_text))}
          </div>
        </div>
        {_render_today_ops(payload, embedded=True, show_title=False, show_headline=False)}
      </div>
    </section>
    """


def _render_trust_section(payload: Dict[str, Any], manifest_status: Dict[str, Any], health: Dict[str, Any]) -> str:
    dq = payload.get("data_quality") or {}
    ibkr = payload.get("ibkr") or {}
    external_text, external_kind = _external_precheck_metric(payload)
    receipt = payload.get("run_receipt") or {}
    health_level = str((health or {}).get("level") or "OK")
    strategy_layer = ((health or {}).get("layers") or {}).get("strategy_data") or {}
    strategy_level = str(strategy_layer.get("level") or health_level)
    strategy_usable = strategy_level != "CRITICAL" and str(dq.get("level") or "") not in {"BLOCKED", "NO_CACHE"}
    certification_status = str(
        ((health or {}).get("post_deploy_certification") or {}).get("status") or ""
    )
    certification_pending = certification_status == "PENDING_POST_DEPLOY"
    action_mode = (
        "STOP"
        if not strategy_usable
        else "WAIT"
        if certification_pending
        else "READY"
        if health_level == "OK"
        else "REVIEW ONLY"
    )
    summary_text = (
        "策略链路不可直接使用，请先处理红色阻断项。"
        if not strategy_usable
        else "新版本运行正常，但尚未经过下一次自然日跑再认证；当前不得据此授权交易。"
        if certification_pending
        else "策略链路正常；当前黄灯来自可解释的外部/日历/对账因素。"
        if strategy_usable and health_level != "OK"
        else "策略链路正常，数据证据齐备。"
    )
    receipt_text = _receipt_status_text(receipt)
    health_report_text = _health_report_evidence_text(payload, health)
    sip_text = _sip_evidence_text(payload)
    warnings = _trust_warning_rows(health)
    latest_market = _latest_certified_market_date(payload)
    return f"""
    <section class="trust-health">
      <h2>今日可信度与系统状态 / Trust &amp; System Health</h2>
      <div class="trust-summary trust-compact-head">
        <div class="trust-verdict">
          {_badge('策略不可用' if not strategy_usable else '策略待认证' if certification_pending else '策略可用', 'danger' if not strategy_usable else 'warn' if certification_pending else 'ok')}
          <div class="action">今日操作：{esc(action_mode)}</div>
        </div>
        <div class="trust-context">
          <div class="trust-meta">
            <span><b>官方</b> {esc(receipt_text)}</span>
            <span><b>as_of</b> {esc(str(payload.get('as_of') or 'NA'))}</span>
            <span><b>认证行情</b> {esc(latest_market)}</span>
            <span><b>策略输入质量</b> {esc(str(dq.get('level', 'NA')))} {_fmt_num(dq.get('overall_score'))}</span>
          </div>
          <div class="trust-headline">{esc(summary_text)}</div>
          <div class="mini-note">策略输入质量只统计会影响决策的数据；研究/辅助源另计入全源观测质量，不阻断策略。</div>
        </div>
      </div>

      <div class="trust-layer-grid trust-status-lanes">
        {_trust_layer_card('策略数据链', _health_layer_metric(health, 'strategy_data'), _health_layer_kind(health, 'strategy_data'), [
            f"as_of={payload.get('as_of', 'NA')} · manifest={manifest_status.get('status', 'NA')} · 阻断策略：{'否' if strategy_usable else '是'}",
        ])}
        {_trust_layer_card('外部数据链', external_text, external_kind, [
            f"{_external_due_text(payload)} · {_external_precheck_freshness_text(payload)} · 阻断策略：否",
        ])}
        {_trust_layer_card('持仓对账', _health_layer_metric(health, 'position_reconciliation'), _health_layer_kind(health, 'position_reconciliation'), [
            f"IBKR={ibkr.get('source', 'disabled')}{' / STALE' if ibkr.get('snapshot_stale') else ''} · 不影响策略评分",
        ])}
        {_trust_layer_card('辅助资金流', _health_layer_metric(health, 'auxiliary_flows'), _health_layer_kind(health, 'auxiliary_flows'), [
            f"SIP={sip_text} · 只作辅助",
        ])}
      </div>

      {_render_trust_primary_issue(health, strategy_usable)}

      <details class="trust-diagnostics">
        <summary>展开诊断、质量与运行证据</summary>
        <div class="trust-diagnostics-body">
          <div class="trust-diagnostics-title">完整告警清单</div>
          <div class="trust-warning-list">
            {warnings}
          </div>

          <div class="trust-diagnostics-title">质量拆分</div>
          {_render_quality_dimensions(payload)}

          <div class="trust-diagnostics-title">运行证据</div>
          <div class="trust-evidence-grid">
            {_trust_evidence('官方回执', receipt_text)}
            {_trust_evidence('Health 报告', health_report_text)}
            {_trust_evidence('Manifest', str(manifest_status.get('status', 'NA')))}
            {_trust_evidence('External Run', external_text)}
            {_trust_evidence('SIP Flow', sip_text)}
            {_trust_evidence('OHLCV 见证', _market_witness_evidence_text(payload))}
          </div>

          {_render_due_external_source_actions(payload)}
          {_render_quality_penalty_summary(payload)}
          {_render_external_precheck_evidence_card(payload)}
        </div>
      </details>

      {_render_data_trust_zone(payload)}
    </section>
    """


def _render_quality_dimensions(payload: Dict[str, Any]) -> str:
    report = payload.get("system_health_report")
    dimensions = report.get("data_quality_dimensions") if isinstance(report, dict) else None
    if not isinstance(dimensions, dict):
        dq = payload.get("data_quality") if isinstance(payload.get("data_quality"), dict) else {}
        dimensions = {
            "market_completeness": dq.get("completeness_score"),
            "provenance": dq.get("quality_score"),
            "timeliness": dq.get("latency_score"),
            "decision_input_coverage": None,
        }
    decision_quality = payload.get("data_quality") or {}
    all_source_quality = payload.get("all_source_data_quality") or decision_quality
    return (
        "<div class='trust-evidence-grid quality-dimensions'>"
        + _trust_evidence(
            "策略输入质量",
            f"{decision_quality.get('level', 'NA')} {_fmt_num(decision_quality.get('overall_score'))}",
        )
        + _trust_evidence(
            "全源观测质量",
            f"{all_source_quality.get('level', 'NA')} {_fmt_num(all_source_quality.get('overall_score'))}",
        )
        + _trust_evidence("行情完整度", _fmt_num(dimensions.get("market_completeness")))
        + _trust_evidence("来源真实性", _fmt_num(dimensions.get("provenance")))
        + _trust_evidence("数据时效性", _fmt_num(dimensions.get("timeliness")))
        + _trust_evidence("评分置信权重覆盖", _fmt_num(dimensions.get("decision_input_coverage")))
        + "</div>"
        + "<div class='mini-note'>策略输入质量用于策略置信度；全源观测质量用于研究/辅助源运维。评分置信权重按每个标的 100 分归一化后等权统计，不是因子数量覆盖率。</div>"
    )


def _render_due_external_source_actions(payload: Dict[str, Any]) -> str:
    external = payload.get("external_source_status")
    if not isinstance(external, dict) or not external:
        return ""
    rows = []
    for source_id, row in sorted(external.items(), key=lambda item: EXTERNAL_SOURCE_ORDER.index(item[0]) if item[0] in EXTERNAL_SOURCE_ORDER else 99):
        if not isinstance(row, dict):
            continue
        freshness = str(row.get("freshness_status") or "")
        status = _external_attempt_status(row)
        evidence = canonical_evidence_issue(row)
        retired = str(row.get("lifecycle_status") or "") == "RETIRED_PAYWALL"
        if retired and not evidence:
            continue
        needs_action = bool(evidence) or freshness in {"DUE_SOON", "STALE"} or status not in {"OK", "MISSING"}
        if not needs_action:
            continue
        safe_id = _external_source_dom_id(source_id)
        latest = row.get("latest_promoted_as_of") or row.get("latest_normalized_as_of") or "NA"
        age = row.get("age_days")
        age_text = f" · {age}d" if age is not None else ""
        rows.append(
            "<div class='trust-warning warn'>"
            f"<b>{esc(str(source_id))}</b> — {esc(evidence or freshness or status)}{esc(age_text)}"
            f"<div class='mini-note'>latest={esc(str(latest)[:10])} · {esc(str(row.get('evidence_detail') or _external_attempt_error(row) or row.get('next_action') or '到期前刷新，若发布方尚未更新则缓存继续可用。'))}</div>"
            f"<button class='btn-muted' style='padding:3px 9px;font-size:12px;min-height:26px;margin-top:5px' "
            f"onclick=\"refreshExternalSource('{safe_id}')\" id='external-source-quick-{safe_id}-btn'>到期前刷新</button>"
            f" <span class='subtle' id='external-source-quick-{safe_id}-status'></span>"
            "</div>"
        )
    if not rows:
        return ""
    return (
        "<div class='precheck-evidence-card'>"
        "<div class='precheck-evidence-head'>"
        "<div><b>外部源到期前处置 / Source Actions</b>"
        "<div class='mini-note'>只刷新对应 ledger/soft_history；不评分、不写官方 run。</div></div>"
        f"{_badge(str(len(rows)) + ' 个待处置', 'warn')}"
        "</div>"
        "<div class='trust-warning-list' style='margin:8px 0 0'>"
        f"{''.join(rows)}"
        "</div>"
        "</div>"
    )


def _render_quality_penalty_summary(payload: Dict[str, Any]) -> str:
    dq = payload.get("data_quality") or {}
    penalties = [p for p in (dq.get("penalties") or []) if isinstance(p, dict)]
    if not penalties:
        return (
            "<div class='precheck-evidence-card'>"
            "<div class='precheck-evidence-head'>"
            "<div><b>策略输入质量扣分账本</b>"
            "<div class='mini-note'>暂无策略输入质量惩罚；当前总分来自完整度、质量、延迟三项综合。</div></div>"
            f"{_badge('CLEAN', 'ok')}"
            "</div>"
            "</div>"
        )
    counts: Dict[str, int] = {}
    for item in penalties:
        reason = str(item.get("reason") or "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    count_text = " · ".join(f"{esc(reason)} × {count}" for reason, count in sorted(counts.items()))
    rows = "".join(
        "<tr>"
        f"<td>{esc(str(item.get('reason') or 'unknown'))}</td>"
        f"<td>{esc(_quality_penalty_field_summary(item.get('field')))}</td>"
        f"<td>{_fmt_num(item.get('penalty'))}</td>"
        "</tr>"
        for item in penalties[:6]
    )
    more = len(penalties) - 6
    more_note = f"<div class='mini-note'>另有 {more} 条扣分在底部 Audit Detail 展开查看。</div>" if more > 0 else ""
    return (
        "<div class='precheck-evidence-card'>"
        "<div class='precheck-evidence-head'>"
        "<div><b>策略输入质量扣分账本</b>"
        f"<div class='mini-note'>{count_text or '无扣分'} · 影响策略置信度；是否阻断由策略数据链综合判定</div></div>"
        f"{_badge(str(dq.get('level') or 'NA') + ' ' + _fmt_num(dq.get('overall_score')), _quality_kind(dq.get('level')))}"
        "</div>"
        "<div class='table-scroll' style='margin-top:8px'>"
        "<table>"
        "<thead><tr><th>类型</th><th>字段组</th><th>扣分</th></tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table>"
        "</div>"
        f"{more_note}"
        "</div>"
    )


def _quality_penalty_field_summary(value: Any) -> str:
    fields = [str(part).replace("SOFT.", "") for part in str(value or "").split(",") if str(part).strip()]
    if not fields:
        return "NA"
    head = ", ".join(fields[:3])
    if len(fields) > 3:
        return f"{head} (+{len(fields) - 3})"
    return head


def _trust_layer_card(title: str, status_html: str, kind: str, notes: List[str]) -> str:
    kind = kind if kind in {"ok", "warn", "danger", "watch"} else "watch"
    rows = "".join(f"<div class='mini-note'>{esc(note)}</div>" for note in notes if note)
    return (
        f"<div class='trust-layer-card health-pill {kind}'>"
        f"<div class='label'>{esc(title)}</div>"
        f"<div class='value'>{status_html}</div>"
        f"{rows}"
        "</div>"
    )


def _trust_evidence(label: str, value: str) -> str:
    return (
        "<div class='trust-evidence'>"
        f"<div class='label'>{esc(label)}</div>"
        f"<div class='value'>{esc(value)}</div>"
        "</div>"
    )


def _receipt_status_text(receipt: Dict[str, Any]) -> str:
    if not isinstance(receipt, dict) or not receipt:
        return "无回执"
    status = str(receipt.get("status") or ("OK" if receipt.get("ok") else "FAILED"))
    when = _run_receipt_when(str(receipt.get("run_at") or ""))
    if status == "OK" and receipt.get("ok"):
        return when
    return status


def _health_report_evidence_text(
    payload: Dict[str, Any],
    health: Dict[str, Any] | None = None,
) -> str:
    certification = (health or {}).get("post_deploy_certification") or {}
    certification_status = str(certification.get("status") or "")
    if certification_status == "PENDING_POST_DEPLOY":
        return "待当前版本自然日跑再认证"
    if certification_status in {"GENERATOR_MISMATCH", "RUNTIME_IDENTITY_INVALID"}:
        return "生成器身份异常"
    report = payload.get("system_health_report")
    if not isinstance(report, dict):
        return "无报告"
    payload_hash = str(payload.get("input_hash") or "")
    report_hash = str(report.get("input_hash") or "")
    if payload_hash and report_hash and payload_hash == report_hash:
        return "hash 匹配"
    if payload_hash and report_hash:
        return "hash 不一致"
    return "已挂载"


def _sip_evidence_text(payload: Dict[str, Any]) -> str:
    status = payload.get("alpaca_daily_flow_status")
    flow = payload.get("alpaca_daily_flow")
    if isinstance(status, dict):
        label = str(status.get("status") or "NA")
        as_of = str(status.get("as_of") or "")
        return f"{label}{(' ' + as_of) if as_of else ''}"
    if isinstance(flow, dict) and flow.get("as_of"):
        return "OK " + str(flow.get("as_of"))
    return "无 SIP"


def _market_witness_evidence_text(payload: Dict[str, Any]) -> str:
    report = payload.get("system_health_report")
    witness = report.get("market_witness_status") if isinstance(report, dict) else None
    if not isinstance(witness, dict):
        witness = payload.get("market_witness_status")
    if not isinstance(witness, dict) or not witness:
        return "无见证报告"
    status = str(witness.get("status") or "NA")
    summary = witness.get("summary") if isinstance(witness.get("summary"), dict) else {}
    matched = int(summary.get("MATCH") or 0)
    mismatches = sum(
        int(summary.get(key) or 0)
        for key in ("DATE_MISMATCH", "PRICE_MISMATCH", "VOLUME_MISMATCH")
    )
    text = f"{status} · MATCH {matched}"
    return f"{text} · mismatch {mismatches}" if mismatches else text


def _factor_symbol_count_text(payload: Dict[str, Any]) -> str:
    scores = payload.get("scores") if isinstance(payload.get("scores"), dict) else {}
    count = 0
    for row in scores.values():
        factors = row.get("factor_scores") if isinstance(row, dict) else None
        if isinstance(factors, dict) and factors:
            count += 1
    return f"{count}/{len(scores)} symbols"


def _external_official_evidence_text(payload: Dict[str, Any]) -> str:
    external = payload.get("external_source_status")
    if not isinstance(external, dict) or not external:
        return "官方文件证据：NA"
    count = sum(
        1
        for row in external.values()
        if isinstance(row, dict) and (row.get("official_issue_as_of") or row.get("official_file_sha256"))
    )
    return f"官方文件证据：{count}"


def _external_due_text(payload: Dict[str, Any]) -> str:
    external = payload.get("external_source_status")
    if not isinstance(external, dict) or not external:
        return "外部源数据 SLO：NA"
    due = [
        str(source_id)
        for source_id, row in external.items()
        if isinstance(row, dict) and str(row.get("freshness_status") or "") == "DUE_SOON"
    ]
    if due:
        return "外部源数据 DUE_SOON：" + ", ".join(due[:3])
    return "外部源数据 SLO：OK"


def _external_precheck_freshness_text(payload: Dict[str, Any]) -> str:
    precheck = payload.get("external_precheck_status")
    if not isinstance(precheck, dict):
        return "预检报告：未生成"
    if precheck.get("stale"):
        return f"预检报告：陈旧（{precheck.get('mtime_date') or 'NA'}）"
    if precheck.get("mtime_date"):
        return f"预检报告：今日（{precheck.get('mtime_date')}）"
    return "预检报告：已挂载"


def _latest_certified_market_date(payload: Dict[str, Any]) -> str:
    admission = payload.get("market_admission_status")
    canonical = admission.get("canonical_files") if isinstance(admission, dict) else None
    dates = [
        str(row.get("latest_as_of") or "")[:10]
        for row in (canonical or {}).values()
        if isinstance(row, dict) and row.get("latest_as_of")
    ]
    return max(dates) if dates else str(payload.get("as_of") or "NA")[:10]


def _render_trust_primary_issue(health: Dict[str, Any], strategy_usable: bool) -> str:
    layers = (health or {}).get("layers") or {}
    candidates: List[Dict[str, Any]] = []
    strategy_candidates: List[Dict[str, Any]] = []
    seen = set()
    strategy_seen = set()

    strategy_rows = list((layers.get("strategy_data") or {}).get("checks") or [])
    strategy_rows.extend(
        check
        for check in ((health or {}).get("checks") or [])
        if isinstance(check, dict) and str(check.get("layer") or "") == "strategy_data"
    )
    for check in strategy_rows:
        if not isinstance(check, dict):
            continue
        key = (
            str(check.get("level") or "INFO"),
            str(check.get("label") or ""),
            str(check.get("detail") or ""),
        )
        if key not in strategy_seen:
            strategy_seen.add(key)
            strategy_candidates.append(check)

    sources = [((layers.get("strategy_data") or {}).get("checks") or [])]
    sources.append((health or {}).get("checks") or [])
    sources.extend(
        (row or {}).get("checks") or []
        for name, row in layers.items()
        if name != "strategy_data"
    )
    for rows in sources:
        for check in rows:
            if not isinstance(check, dict):
                continue
            key = (
                str(check.get("level") or "INFO"),
                str(check.get("label") or ""),
                str(check.get("detail") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            candidates.append(check)

    priority = {"CRITICAL": 0, "DEGRADED": 1, "INFO": 2, "OK": 3}
    candidates.sort(key=lambda row: priority.get(str(row.get("level") or "INFO"), 2))
    strategy_candidates.sort(key=lambda row: priority.get(str(row.get("level") or "INFO"), 2))
    if not strategy_usable and not strategy_candidates:
        return (
            "<div class='trust-warning trust-primary-issue danger'>"
            "<div class='issue-head'><b>当前阻断</b>"
            f"{_badge('STOP', 'danger')}</div>"
            "<div class='mini-note'>策略数据链不可用；展开诊断查看完整证据。</div>"
            "</div>"
        )
    if strategy_usable and not candidates:
        return (
            "<div class='trust-warning trust-primary-issue ok'>"
            "<div class='issue-head'><b>当前无阻断</b>"
            f"{_badge('READY', 'ok')}</div>"
            "<div class='mini-note'>策略数据链证据齐备。</div>"
            "</div>"
        )

    check = strategy_candidates[0] if not strategy_usable else candidates[0]
    level = str(check.get("level") or "INFO")
    label = str(check.get("label") or "检查项")
    detail = str(check.get("detail") or "")
    blocks = not strategy_usable
    kind = "danger" if blocks else ("warn" if level in {"CRITICAL", "DEGRADED", "INFO"} else "ok")
    heading = "当前阻断" if blocks else "当前关注"
    impact = "影响：阻断策略" if blocks else "影响：不阻断策略，按需复核"
    return (
        f"<div class='trust-warning trust-primary-issue {kind}'>"
        f"<div class='issue-head'><b>{esc(heading)}</b>{_badge(level, _health_level_kind(level))}</div>"
        f"<div><b>{esc(label)}</b>{(' — ' + esc(detail)) if detail else ''}</div>"
        f"<div class='mini-note'>{esc(impact)}</div>"
        "</div>"
    )


def _trust_warning_rows(health: Dict[str, Any]) -> str:
    checks: List[Dict[str, Any]] = []
    seen = set()
    for check in (health or {}).get("checks") or []:
        key = (str(check.get("label") or ""), str(check.get("detail") or ""), str(check.get("level") or ""))
        if key not in seen:
            seen.add(key)
            checks.append(check)
    for layer in ((health or {}).get("layers") or {}).values():
        for check in (layer or {}).get("checks") or []:
            key = (str(check.get("label") or ""), str(check.get("detail") or ""), str(check.get("level") or ""))
            if key not in seen:
                seen.add(key)
                checks.append(check)
    if not checks:
        return "<div class='trust-warning'>当前无影响判断项。</div>"
    rows = []
    for check in checks:
        level = str(check.get("level") or "INFO")
        label = str(check.get("label") or "检查项")
        detail = str(check.get("detail") or "")
        kind = "danger" if level == "CRITICAL" else ("warn" if level == "DEGRADED" else "")
        title = "HOLIDAY-LAG" if "行情落后" in label else label
        blocks_strategy = "是" if level == "CRITICAL" and "IBKR" not in label else "否"
        blocks_trade = "需复核" if "IBKR" in label or level in {"CRITICAL", "DEGRADED"} else "否"
        rows.append(
            f"<div class='trust-warning {kind}'>"
            f"<b>{esc(title)}</b>{(' — ' + esc(detail)) if detail else ''}"
            f"<div class='mini-note'>阻断策略？{blocks_strategy} · 阻断下单？{blocks_trade}</div>"
            "</div>"
        )
    return "".join(rows)


def _health_layer_metric(health: Dict[str, Any], layer: str) -> str:
    layers = (health or {}).get("layers") or {}
    row = layers.get(layer) or {}
    level = str(row.get("level") or ((health or {}).get("level") if layer == "strategy_data" else "OK") or "OK")
    checks = row.get("checks") or []
    actionable = [c for c in checks if c.get("level") in {"CRITICAL", "DEGRADED"}]
    info = [c for c in checks if c.get("level") == "INFO"]
    if actionable:
        detail = str(actionable[0].get("label") or "")[:18]
    elif info:
        detail = str(info[0].get("label") or "")[:18]
    else:
        detail = "OK"
    return f"{_badge(level, _health_level_kind(level))} <span class='subtle'>{esc(detail)}</span>"


def _health_pill(label: str, value: str, kind: str = "") -> str:
    kind = kind if kind in {"ok", "warn", "danger", "watch"} else "watch"
    return (
        f"<div class='health-pill {kind}'>"
        f"<div class='label'>{esc(label)}</div>"
        f"<div class='value'>{value}</div>"
        "</div>"
    )


def _health_layer_kind(health: Dict[str, Any], layer: str) -> str:
    layers = (health or {}).get("layers") or {}
    row = layers.get(layer) or {}
    level = str(row.get("level") or ((health or {}).get("level") if layer == "strategy_data" else "OK") or "OK")
    return _health_level_kind(level)


def _manifest_kind(manifest_status: Dict[str, Any]) -> str:
    status = str((manifest_status or {}).get("status") or "UNKNOWN")
    return {"OK": "ok", "DRIFT": "danger", "MISSING": "warn", "UNKNOWN": "watch"}.get(status, "watch")


def _external_precheck_metric(payload: Dict[str, Any]) -> tuple[str, str]:
    external = payload.get("external_source_status") or {}
    if isinstance(external, dict) and external:
        ok = 0
        err = 0
        miss = 0
        retry = 0
        retired = 0
        evidence_errors = 0
        for row in external.values():
            if not isinstance(row, dict):
                continue
            if row.get("active") is False:
                continue
            status = _external_attempt_status(row)
            evidence = canonical_evidence_issue(row)
            if evidence:
                evidence_errors += 1
                err += 1
            elif str(row.get("lifecycle_status") or "") == "RETIRED_PAYWALL":
                ok += 1
                retired += 1
            elif status == "OK":
                ok += 1
            elif certified_canonical_is_current(row):
                ok += 1
                retry += 1
            elif status == "MISSING":
                miss += 1
            else:
                err += 1
        kind = "danger" if err else ("warn" if miss or retry else "ok")
        evidence_text = f" · EVIDENCE {evidence_errors}" if evidence_errors else ""
        retry_text = f" · RETRY {retry}" if retry else ""
        retired_text = f" · RETIRED {retired}" if retired else ""
        return f"OK {ok} / ERR {err} / MISS {miss}{evidence_text}{retry_text}{retired_text}", kind
    precheck = payload.get("external_precheck_status")
    if isinstance(precheck, dict):
        ready = bool(precheck.get("ready"))
        refresh = precheck.get("refresh") if isinstance(precheck.get("refresh"), dict) else {}
        nonblocking_refresh_errors = len(precheck.get("nonblocking_refresh_error_sources") or [])
        ok_count = refresh.get("ok_count")
        error_count = refresh.get("error_count")
        blocking = len(precheck.get("blocking_sources") or [])
        warnings = len(precheck.get("warning_sources") or [])
        if ready and nonblocking_refresh_errors and not blocking:
            text = f"READY · retry_error={nonblocking_refresh_errors}"
        elif ok_count is not None or error_count is not None:
            text = f"{'READY' if ready else 'BLOCK'} · ok={esc(ok_count or 0)} err={esc(error_count or 0)}"
        else:
            text = f"{'READY' if ready else 'BLOCK'} · block={blocking} warn={warnings}"
        kind = "ok" if ready and not warnings else ("danger" if blocking else "warn")
        return text, kind
    return "无 precheck", "watch"


def _render_external_precheck_evidence_card(payload: Dict[str, Any]) -> str:
    precheck = payload.get("external_precheck_status")
    if not isinstance(precheck, dict):
        return (
            "<div class='precheck-evidence-card'>"
            "<div class='precheck-evidence-head'>"
            "<div><b>晨间外部源取证 / Morning Source Evidence</b>"
            "<div class='mini-note'>尚无 <code>external_precheck_latest.{json,md}</code>；等待 06:45/07:05 预检或手动刷新。</div></div>"
            "<div>"
            f"{_badge('NO REPORT', 'watch')} "
            "<button class='btn-muted' style='padding:3px 9px;font-size:12px;min-height:26px' "
            "onclick='rerunExternalPrecheck()' id='external-precheck-rerun-btn'>重跑晨间预检</button>"
            "<div class='subtle' id='external-precheck-rerun-status'></div>"
            "</div>"
            "</div>"
            "</div>"
        )

    ready = bool(precheck.get("ready"))
    stale = bool(precheck.get("stale"))
    refresh = precheck.get("refresh") if isinstance(precheck.get("refresh"), dict) else {}
    warnings = [str(item) for item in (precheck.get("warning_sources") or [])]
    blocking = [str(item) for item in (precheck.get("blocking_sources") or [])]
    nonblocking = [str(item) for item in (precheck.get("nonblocking_refresh_error_sources") or [])]
    blocking_refresh = [str(item) for item in (precheck.get("blocking_refresh_error_sources") or [])]
    kind = "warn" if stale else ("danger" if blocking or blocking_refresh or not ready else ("warn" if warnings or nonblocking else "ok"))
    badge = "STALE REPORT" if stale else ("READY" if ready else "NOT READY")
    source_path = str(precheck.get("markdown_path") or precheck.get("source_path") or "external_precheck_latest.json")
    markdown = str(precheck.get("markdown_text") or "")
    report_date = str(precheck.get("mtime_date") or "NA")
    status_line = (
        f"ready={ready} · warning={len(warnings)} · blocking={len(blocking)} "
        f"· retry_error={len(nonblocking)} · refresh_blocking={len(blocking_refresh)}"
    )
    stale_note = (
        f"<div class='mini-note'>报告日期={esc(report_date)}；等待今日 06:45/07:05 预检或手动重跑后再作为今日证据。</div>"
        if stale
        else ""
    )
    cache_note = (
        "<div class='mini-note'>缓存可用：刷新尝试失败但未阻断策略；优先看 daily ledger 与数据信任区。</div>"
        if ready and nonblocking and not blocking_refresh
        else ""
    )
    raw = (
        "<details class='precheck-report-raw'>"
        "<summary>查看原始 Markdown 取证报告</summary>"
        f"<pre>{esc(markdown)}</pre>"
        "</details>"
        if markdown
        else "<div class='mini-note'>尚未挂载 Markdown 原文；可查看 JSON precheck source。</div>"
    )
    return (
        "<div class='precheck-evidence-card'>"
        "<div class='precheck-evidence-head'>"
        "<div>"
        f"<b>晨间外部源取证 / Morning Source Evidence</b> {_badge(badge, kind)}"
        f"<div class='mini-note'>{esc(status_line)}</div>"
        f"<div class='mini-note'>source={esc(source_path)}</div>"
        "</div>"
        "<div style='text-align:right'>"
        f"<div class='subtle'>ok={esc(str(refresh.get('ok_count', '—')))} · err={esc(str(refresh.get('error_count', '—')))}</div>"
        "<button class='btn-muted' style='padding:3px 9px;font-size:12px;min-height:26px;margin-top:4px' "
        "onclick='rerunExternalPrecheck()' id='external-precheck-rerun-btn'>重跑晨间预检</button>"
        "<div class='subtle' id='external-precheck-rerun-status'></div>"
        "</div>"
        "</div>"
        f"{stale_note}"
        f"{cache_note}"
        f"{raw}"
        "</div>"
    )


def _external_daily_ledger_all_ok(payload: Dict[str, Any]) -> bool:
    external = payload.get("external_source_status")
    if not isinstance(external, dict) or not external:
        return False
    rows = [
        row
        for row in external.values()
        if isinstance(row, dict) and row.get("active") is not False
    ]
    return bool(rows) and all(
        (
            _external_attempt_status(row) == "OK"
            or str(row.get("lifecycle_status") or "") == "RETIRED_PAYWALL"
        )
        and not canonical_evidence_issue(row)
        for row in rows
    )


def _render_external_precheck_summary(payload: Dict[str, Any]) -> str:
    precheck = payload.get("external_precheck_status")
    if not isinstance(precheck, dict):
        return (
            "<details class='work-card external-precheck-summary' style='margin:10px 0 0'>"
            "<summary>外部源预检 / External Precheck "
            "<span class='subtle'>尚无 precheck 结果</span></summary>"
            "<div class='detail-body'><div class='mini-note'>等待 "
            "<code>~/.hermes/logs/external/external_precheck_latest.json</code>。</div></div>"
            "</details>"
        )

    ready = bool(precheck.get("ready"))
    daily_ledger_ok = _external_daily_ledger_all_ok(payload)
    refresh = precheck.get("refresh") if isinstance(precheck.get("refresh"), dict) else {}
    blocking = [str(item) for item in (precheck.get("blocking_sources") or [])]
    warnings = [str(item) for item in (precheck.get("warning_sources") or [])]
    nonblocking_refresh_errors = [str(item) for item in (precheck.get("nonblocking_refresh_error_sources") or [])]
    blocking_refresh_errors = [str(item) for item in (precheck.get("blocking_refresh_error_sources") or [])]
    skipped_imports = _external_precheck_skipped_imports(refresh)
    sources = precheck.get("sources") if isinstance(precheck.get("sources"), dict) else {}
    source_ids = list(EXTERNAL_SOURCE_ORDER)
    source_ids.extend(sorted(str(name) for name in sources.keys() if str(name) not in EXTERNAL_SOURCE_ORDER))
    rows = []
    for source_id in source_ids:
        row = sources.get(source_id) if isinstance(sources.get(source_id), dict) else None
        if not row:
            continue
        status = _external_attempt_status(row, default="UNKNOWN")
        latest = str(row.get("latest_promoted_as_of") or "—")[:10]
        finished = str(
            row.get("latest_attempt_finished_at")
            or row.get("finished_at")
            or row.get("latest_attempt_started_at")
            or row.get("started_at")
            or "—"
        )
        label = str(row.get("label") or EXTERNAL_SOURCE_LABELS.get(source_id) or source_id)
        freshness = str(row.get("freshness_status") or "")
        age = row.get("age_days")
        freshness_note = freshness
        if freshness_note and age is not None:
            freshness_note += f" · {age}d"
        official_note = ""
        if row.get("official_issue_as_of") or row.get("official_file_sha256"):
            official_note = (
                f"issue={str(row.get('official_issue_as_of') or '—')[:10]} "
                f"sha={str(row.get('official_file_sha256') or '—')[:8]}"
            )
        failure_note = str(_external_attempt_error(row) or row.get("failure_kind") or "")
        skip_note = skipped_imports.get(source_id, "")
        note = " · ".join(part for part in (freshness_note, official_note, failure_note, skip_note) if part)
        rows.append(
            "<tr>"
            f"<td><b>{esc(source_id)}</b><div class='subtle'>{esc(label)}</div></td>"
            f"<td>{_external_source_status_badge(status)}</td>"
            f"<td>{esc(latest)}</td>"
            f"<td><span class='subtle'>{esc(finished)}</span></td>"
            f"<td>{esc(note or '—')}</td>"
            "</tr>"
        )
    rows_html = "".join(rows) if rows else '<tr><td colspan="5">precheck 文件存在，但没有 sources 明细。</td></tr>'
    issue_text = []
    if blocking:
        issue_text.append("blocking=" + ",".join(blocking))
    if warnings:
        issue_text.append("warning=" + ",".join(warnings))
    if nonblocking_refresh_errors:
        issue_text.append("nonblocking=" + ",".join(nonblocking_refresh_errors))
    if blocking_refresh_errors:
        issue_text.append("refresh_blocking=" + ",".join(blocking_refresh_errors))
    issue_html = f"<span class='subtle'>{esc(' · '.join(issue_text))}</span>" if issue_text else "<span class='subtle'>无 blocking/warning</span>"
    badge_text = "READY" if ready else ("PRECHECK WARN" if daily_ledger_ok else "NOT READY")
    badge_kind = "ok" if ready else ("warn" if daily_ledger_ok else "danger")
    retry_text = (
        f"retry_error={len(nonblocking_refresh_errors)}"
        if ready and nonblocking_refresh_errors and not blocking_refresh_errors
        else f"error={refresh.get('error_count', '—')}"
    )
    scope_note = (
        "<div class='mini-note'>正式 daily ledger OK，本预检异常不影响今日策略；"
        "下次 06:45/07:05 预检会再次尝试。</div>"
        if daily_ledger_ok and not ready
        else ""
    )
    if ready and nonblocking_refresh_errors:
        scope_note += (
            "<div class='mini-note'>缓存可用；部分刷新尝试失败但未阻断策略，"
            "通常是官方源暂时拦截或旧下载文件被拒绝。</div>"
        )
    return (
        "<details class='work-card external-precheck-summary' style='margin:10px 0 0'>"
        "<summary>外部源预检 / External Precheck "
        f"{_badge(badge_text, badge_kind)} "
        f"<span class='subtle'>ok={esc(str(refresh.get('ok_count', '—')))} {esc(retry_text)}</span> "
        f"{issue_html}</summary>"
        "<div class='detail-body'>"
        f"{scope_note}"
        "<div class='table-scroll'>"
        "<table><thead><tr><th>源</th><th>precheck</th><th>最新数据日</th><th>最近预检</th><th>证据 / 问题</th></tr></thead>"
        f"<tbody>{rows_html}</tbody></table>"
        "</div>"
        f"<div class='subtle' style='margin-top:7px'>source={esc(str(precheck.get('source_path') or '~/.hermes/logs/external/external_precheck_latest.json'))}</div>"
        "</div>"
        "</details>"
    )


def _external_precheck_skipped_imports(refresh: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for run in refresh.get("runs") or []:
        if not isinstance(run, dict):
            continue
        source_id = str(run.get("source_id") or "")
        skipped = str(run.get("fallback_import_skipped") or "")
        if not source_id or not skipped:
            continue
        reason = str(run.get("fallback_import_skip_reason") or "previous failure")
        out[source_id] = f"跳过旧下载文件 {Path(skipped).name}: {reason}"
    return out


def _render_system_health_audit(payload: Dict[str, Any]) -> str:
    report = payload.get("system_health_report")
    if not isinstance(report, dict):
        return (
            "<details class='work-card system-health-audit' style='margin:10px 0 0'>"
            "<summary>20 维系统自检 / System Health Audit "
            "<span class='subtle'>尚无 daily 报告</span></summary>"
            "<div class='detail-body'><div class='mini-note'>等待下一次 daily 生成 "
            "<code>reports/system_health_YYYY-MM-DD.json</code>。</div></div>"
            "</details>"
        )

    dimensions = report.get("audit_dimensions") if isinstance(report.get("audit_dimensions"), list) else []
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for row in dimensions:
        if isinstance(row, dict):
            status = str(row.get("status") or "UNKNOWN").upper()
            if status in counts:
                counts[status] += 1

    report_as_of = str(report.get("as_of") or "NA")
    page_as_of = str(payload.get("as_of") or "NA")
    generated = str(report.get("generated_at") or "NA")
    health = report.get("health") if isinstance(report.get("health"), dict) else {}
    level = str(health.get("level") or "NA")
    stale = bool(report.get("stale"))
    stale_note = (
        f" {_badge('STALE', 'warn')} <span class='subtle'>报告 as_of={esc(report_as_of)} · 页面 as_of={esc(page_as_of)}</span>"
        if stale else ""
    )
    rows = []
    for row in dimensions:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "UNKNOWN").upper()
        rows.append(
            "<tr>"
            f"<td>{_badge(status, _audit_status_kind(status))}</td>"
            f"<td><b>{esc(str(row.get('label') or row.get('id') or '未命名维度'))}</b></td>"
            f"<td>{esc(str(row.get('detail') or ''))}</td>"
            "</tr>"
        )
    rows_html = "".join(rows) if rows else '<tr><td colspan="3">报告存在，但没有 audit_dimensions。</td></tr>'
    return (
        "<details class='work-card system-health-audit' style='margin:10px 0 0'>"
        "<summary>20 维系统自检 / System Health Audit "
        f"<span class='subtle'>health={esc(level)} · as_of={esc(report_as_of)}</span>{stale_note}</summary>"
        "<div class='detail-body'>"
        "<div class='status-line'>"
        f"{_badge('PASS ' + str(counts['PASS']), 'ok')}"
        f"{_badge('WARN ' + str(counts['WARN']), 'warn')}"
        f"{_badge('FAIL ' + str(counts['FAIL']), 'danger' if counts['FAIL'] else 'ok')}"
        f"<span class='subtle'>generated={esc(generated)}</span>"
        "</div>"
        "<div class='table-scroll' style='margin-top:10px'>"
        "<table><thead><tr><th>状态</th><th>维度</th><th>证据</th></tr></thead>"
        f"<tbody>{rows_html}</tbody></table>"
        "</div>"
        "</div>"
        "</details>"
    )


def _render_system_health_history(payload: Dict[str, Any]) -> str:
    history = payload.get("system_health_history")
    if not isinstance(history, list) or not history:
        return (
            "<details class='work-card system-health-history' style='margin:10px 0 0'>"
            "<summary>最近 7 次系统健康 / Health History "
            "<span class='subtle'>尚无历史报告</span></summary>"
            "<div class='detail-body'><div class='mini-note'>等待 daily 生成 "
            "<code>reports/system_health_YYYY-MM-DD.json</code> 后展示趋势。</div></div>"
            "</details>"
        )
    rows = []
    for row in history[:7]:
        if not isinstance(row, dict):
            continue
        counts = row.get("counts") if isinstance(row.get("counts"), dict) else {}
        layers = row.get("layers") if isinstance(row.get("layers"), dict) else {}
        layer_text = (
            f"策略数据={layers.get('strategy_data', 'NA')} · "
            f"持仓={layers.get('position_reconciliation', 'NA')} · "
            f"资金流={layers.get('auxiliary_flows', 'NA')}"
        )
        rows.append(
            "<tr>"
            f"<td><b>{esc(str(row.get('as_of') or 'NA'))}</b></td>"
            f"<td>{_badge(str(row.get('health_level') or 'NA'), _health_level_kind(str(row.get('health_level') or 'NA')))}</td>"
            f"<td>{_badge('PASS ' + str(counts.get('PASS', 0)), 'ok')} "
            f"{_badge('WARN ' + str(counts.get('WARN', 0)), 'warn')} "
            f"{_badge('FAIL ' + str(counts.get('FAIL', 0)), 'danger' if counts.get('FAIL') else 'ok')}</td>"
            f"<td>{esc(layer_text)}</td>"
            f"<td><span class='subtle'>{esc(str(row.get('generated_at') or 'NA'))}</span></td>"
            "</tr>"
        )
    rows_html = "".join(rows) if rows else '<tr><td colspan="5">暂无历史报告</td></tr>'
    return (
        "<details class='work-card system-health-history' style='margin:10px 0 0'>"
        "<summary>最近 7 次系统健康 / Health History "
        f"<span class='subtle'>{len(rows)} 条 daily 报告</span></summary>"
        "<div class='detail-body'>"
        "<div class='table-scroll'>"
        "<table><thead><tr><th>as_of</th><th>health</th><th>20维统计</th><th>分层</th><th>生成时间</th></tr></thead>"
        f"<tbody>{rows_html}</tbody></table>"
        "</div>"
        "</div>"
        "</details>"
    )


def _audit_status_kind(status: str) -> str:
    upper = str(status or "").upper()
    if upper == "PASS":
        return "ok"
    if upper == "WARN":
        return "warn"
    if upper == "FAIL":
        return "danger"
    return "watch"


def _health_level_kind(level: str) -> str:
    upper = str(level or "OK").upper()
    if upper == "CRITICAL":
        return "danger"
    if upper == "DEGRADED":
        return "warn"
    if upper == "INFO":
        return "watch"
    return "ok"


_STATUS_HISTORY_COLOR = {
    "HOLD": "#16a34a", "WATCH": "#84cc16", "TRIM": "#eab308",
    "REDUCE": "#f97316", "DEFENSIVE_EXIT": "#ef4444", "EXIT": "#b91c1c",
    "NO_ADVICE": "#6b7280",
}


def _render_status_history(payload: Dict[str, Any]) -> str:
    """Compact per-symbol status over recent OFFICIAL trading days, so a one-off
    flip reads as anomalous and a sustained EXIT reads as a real response — the
    '前后一致性' legibility the operator asked for. Renders only when the server
    injects payload['status_history']; absent => empty (back-compatible)."""
    hist = payload.get("status_history") or {}
    rows = []
    for symbol in TRADE_SYMBOLS:
        seq = hist.get(symbol) or []
        if not seq:
            continue
        chips = ""
        for p in seq:
            status = str(p.get("status", "?"))
            color = _STATUS_HISTORY_COLOR.get(status, "#9ca3af")
            valve = bool(p.get("valve"))
            border = "border:2px solid #111827;" if valve else "border:1px solid rgba(0,0,0,.12);"
            chips += (
                f"<span title='{esc(str(p.get('as_of','')))}: {esc(status)}{' ⚠硬阀门' if valve else ''}' "
                f"style='display:inline-flex;align-items:center;justify-content:center;"
                f"width:18px;height:18px;margin-right:3px;border-radius:4px;{border}"
                f"background:{color};color:#fff;font-size:11px;font-weight:800'>{'!' if valve else ''}</span>"
            )
        last = str(seq[-1].get("status", "?"))
        flips = sum(1 for a, b in zip(seq, seq[1:]) if a.get("status") != b.get("status"))
        rows.append(
            "<div style='display:flex;align-items:center;gap:8px;margin:4px 0'>"
            f"<b style='width:52px;flex:none'>{esc(symbol)}</b>"
            f"<span style='white-space:nowrap;overflow-x:auto;flex:1;min-width:0'>{chips}</span>"
            f"<span class='mini-note' style='flex:none'>近 {len(seq)} 个交易日 · 当前 {esc(last)} · 翻转 {flips} 次</span>"
            "</div>"
        )
    if not rows:
        return ""
    return (
        "<section><h2>决策历史 / Decision History "
        "<span style='font-weight:400;font-size:13px;color:var(--muted)'>"
        "每标的最近官方交易日状态 — 一眼看出稳定还是翻转（! = 当日硬阀门）</span></h2>"
        + "".join(rows) +
        "</section>"
    )


def _render_evidence_strip(payload: Dict[str, Any]) -> str:
    scores = payload.get("scores") or {}
    spine = payload.get("confidence_spine") or {}
    ctx = payload.get("routing_context") or {}
    thresholds = [(20, "WATCH"), (35, "TRIM"), (50, "REDUCE"), (70, "D-EXIT"), (75, "EXIT")]
    threshold_html = "".join(
        f"<span class='ladder-label' style='left:{value}%'>{label} {value}</span>"
        for value, label in thresholds
    )
    markers = []
    colors = {"MSTR": "#534AB7", "FNGU": "#D85A30", "SOXL": "#BA7517"}
    for symbol in TRADE_SYMBOLS:
        score = _float((scores.get(symbol) or {}).get("final_score"), 0.0)
        left = max(0.0, min(100.0, score))
        color = colors.get(symbol, "#111827")
        markers.append(
            f"<span class='ladder-marker' style='left:{left}%;background:{color}'></span>"
            f"<span class='ladder-symbol' style='left:{left}%;color:{color}'>{esc(symbol)} {_fmt_num(score)}</span>"
        )
    qqq = ctx.get("qqq") or {}
    module_a = ctx.get("module_a") or {}
    brkb = ctx.get("brkb_defense") or {}
    qqq_broken = bool(qqq.get("below_ma200") or qqq.get("below_ema50") or qqq.get("below_ema20"))
    # module_a is per-symbol A scores ({MSTR:..,FNGU:..,SOXL:..}); the DEFCON gate
    # keys off the max across symbols (A>=12). Reading .get("score") on this dict
    # returned None -> "NA"; show the real max instead.
    a_vals = [_float(v, 0.0) for v in module_a.values() if isinstance(v, (int, float))]
    a_score = max(a_vals) if a_vals else None
    # BRK.B corr is None when BRK.B already failed MA200 (the defense check
    # short-circuits before computing correlation) — show the real reason already
    # in the payload instead of a bare "NA".
    brkb_corr = brkb.get("corr_to_spy")
    if brkb_corr is None:
        brkb_bit = str(brkb.get("reason") or "BRK.B 防守腿状态未知")
    else:
        brkb_bit = f"BRK.B corr {_fmt_num(brkb_corr)}/{_fmt_num(brkb.get('threshold'))}"
    defcon_bits = [
        f"A模块 {_fmt_num(a_score)}",
        "QQQ趋势破坏" if qqq_broken else "QQQ趋势未破坏",
        brkb_bit,
        _dominant_route_text(payload),
    ]
    components = spine.get("components") or {}
    conf_bits = [
        f"mode={esc(spine.get('mode', 'NA'))}",
        f"weakest={esc(spine.get('weakest_link', 'NA'))}",
        " / ".join(f"{esc(k)} {_fmt_num(v)}" for k, v in sorted(components.items())[:4]),
    ]
    return f"""
    <section>
      <h2>为什么这么做 / Evidence Strip</h2>
      <div class="evidence-ladder">
        <div class="ladder-track">
          <span class="ladder-band" style="left:0;width:35%;background:#d1fae5"></span>
          <span class="ladder-band" style="left:35%;width:35%;background:#fef3c7"></span>
          <span class="ladder-band" style="left:70%;width:30%;background:#fee2e2"></span>
          {threshold_html}{''.join(markers)}
        </div>
        <div class="mini-note">DEFCON：{esc(' · '.join(defcon_bits))}</div>
        <div class="mini-note">置信度：{esc(' · '.join(conf_bits))}</div>
      </div>
    </section>
    """


def _render_hard_valve_radar(payload: Dict[str, Any]) -> str:
    scores = payload.get("scores") or {}
    layers = payload.get("decision_layers") or {}
    radar_rows: List[str] = []
    matrix_rows: List[str] = []
    buckets = ["MA200", "EMA50", "Chandelier", "1D Crash", "2D Crash", "BTC/QQQ", "Score/Flow"]
    worst_symbol, worst_score = "", -1
    for symbol in TRADE_SYMBOLS:
        score = scores.get(symbol) or {}
        hv_state = ((layers.get(symbol) or {}).get("hard_valve_state") or {})
        _prev_hits = set((payload.get("prev_valves") or {}).get(symbol) or [])
        _newly = ([h for h in (score.get("hard_valve_hits") or []) if h not in _prev_hits]
                  if payload.get("prev_valves") else [])
        candidates = _valve_candidates_for(score, hv_state)
        summary = _summarize_valve_candidates(candidates)
        danger_points = summary["triggered"] * 3 + summary["pending"] * 2 + summary["near"]
        max_points = max(3, len(candidates) * 3)
        danger_pct = min(100, int(round(danger_points / max_points * 100)))
        if danger_points > worst_score:
            worst_symbol, worst_score = symbol, danger_points
        radar_rows.append(
            "<div class='radar-row'>"
            f"<div><b>{esc(symbol)}</b><div class='danger-bar'><div class='danger-fill' style='width:{danger_pct}%'></div></div>"
            f"<div class='mini-note'>危险度 {danger_pct}%</div></div>"
            f"<div><div>{_badge('已触发 ' + str(summary['triggered']), 'danger' if summary['triggered'] else 'ok')} "
            f"{_badge('待确认 ' + str(summary['pending']), 'warn' if summary['pending'] else 'ok')} "
            f"{_badge('接近 ' + str(summary['near']), 'watch' if summary['near'] else 'ok')}</div>"
            f"<div class='mini-note' style='margin-top:6px'>{esc(summary['note'])}</div>"
            + (f"<div style='margin-top:6px'>{_badge('🆕 今日新触发 ' + ', '.join(_newly) + ' · 待明日收盘确认', 'warn')}</div>" if _newly else "")
            + "</div>"
            "</div>"
        )
        by_bucket = _valve_bucket_statuses(candidates)
        matrix_rows.append(
            "<tr>"
            f"<td><b>{esc(symbol)}</b></td>"
            + "".join(_valve_matrix_cell(by_bucket.get(bucket)) for bucket in buckets)
            + "</tr>"
        )
    overview = f"{worst_symbol} 风险最高" if worst_symbol else "暂无硬阀门数据"
    return f"""
    <section>
      <h2>硬阀门雷达 + 点阵 / Hard Valve Radar</h2>
      <div class="mini-note" style="margin-bottom:8px">总览：{esc(overview)}。红=已触发，黄=待确认，橙=接近触发，灰=安全，空白=不适用。</div>
      {''.join(radar_rows)}
      {_render_factor_map_panel(payload)}
      <details style="margin-top:10px">
        <summary>展开点阵矩阵 / Valve Matrix</summary>
        <div class="detail-body">
          <table class="matrix-table">
            <thead><tr><th>标的</th>{''.join(f'<th>{esc(bucket)}</th>' for bucket in buckets)}</tr></thead>
            <tbody>{''.join(matrix_rows)}</tbody>
          </table>
        </div>
      </details>
    </section>
    """


def _render_escape_decisions_details(payload: Dict[str, Any]) -> str:
    return f"""
    <details class="full-detail-block">
      <summary>展开完整处置指令 / Escape Decisions</summary>
      <section>
        <h2>Escape Decisions / 今日处置指令</h2>
        <div class="command-grid">
          {''.join(_render_symbol_card(symbol, payload) for symbol in TRADE_SYMBOLS)}
        </div>
      </section>
    </details>
    """


def _render_secondary_details(
    payload: Dict[str, Any],
) -> str:
    return f"""
    <details class="full-detail-block">
      <summary>其他折叠详情 / Details</summary>
      <div class="detail-body">
        {_render_macro_section(payload)}
        <section>
          <h2>决策工作台细节 / Workbench Details</h2>
          {_render_decision_workbench(payload)}
        </section>
      </div>
    </details>
    """


def _render_bottom_system_ops_details(payload: Dict[str, Any], manifest_status: Dict[str, Any]) -> str:
    return f"""
    <details class="full-detail-block">
      <summary>页面底部系统运维详情 / System Ops Details</summary>
      <div class="detail-body">
        {_render_external_precheck_summary(payload)}
        {_render_system_health_audit(payload)}
        {_render_system_health_history(payload)}
        <details style="margin-top:10px">
          <summary>展开 Audit Detail / 数据源、质量扣分、manifest</summary>
          <div class="detail-body">
            {_render_quality_detail_body(payload, manifest_status)}
          </div>
        </details>
      </div>
    </details>
    """


def _render_strategy_symbol_card(symbol: str, payload: Dict[str, Any]) -> str:
    score = (payload.get("scores") or {}).get(symbol) or {}
    sizing = (payload.get("sizing") or {}).get(symbol) or {}
    intent = (payload.get("action_intents") or {}).get(symbol) or {}
    hard = score.get("hard_valve_hits") or []
    ibkr = _ibkr_row(payload.get("ibkr") or {}, symbol) or {}
    flow_state = _flow_state_for_symbol(payload, symbol)
    status = str(score.get("status", "NA"))
    target_weight = sizing.get("target_weight", intent.get("target_weight"))
    reason = _strategy_card_reason(score, intent)
    flow_value = f"{_badge(flow_state['severity'], _flow_kind(flow_state['severity']))} {esc(flow_state['summary'])}"
    return (
        "<div class='strategy-card'>"
        f"<div class='row-head'><span class='row-title'>{esc(symbol)}</span>{_badge(status, _status_kind(status))}</div>"
        f"<div class='big'>{esc(_action_cn(intent.get('action')))}</div>"
        "<div class='mini-grid'>"
        f"{_metric('当前', _fmt_pct(ibkr.get('actual_weight')))}"
        f"{_metric('目标', _fmt_pct(target_weight))}"
        f"{_metric('硬阀门', f'{len(hard)} 个' if hard else '未触发')}"
        f"{_metric('穿透流', flow_value)}"
        "</div>"
        f"<div class='mini-note' style='margin-top:8px'>{esc(reason)}</div>"
        "</div>"
    )


def _strategy_card_reason(score: Dict[str, Any], intent: Dict[str, Any]) -> str:
    hard = score.get("hard_valve_hits") or []
    if hard:
        return "硬阀门：" + ", ".join(str(item) for item in hard[:4])
    top = intent.get("top_reasons") or []
    if top:
        return str(top[0])
    factors = _top_factor_items(score, limit=1)
    if factors:
        _, row = factors[0]
        return str(row.get("plain_explain") or row.get("explain") or row.get("factor_id") or "主要因子")
    return "暂无强触发项"


def _render_position_gap_section(payload: Dict[str, Any]) -> str:
    rows = _position_gap_rows(payload)
    body = []
    for row in rows:
        action, cls = _position_action(row["gap_weight"], row["category"])
        body.append(
            "<tr>"
            f"<td>{esc(row['category'])}</td>"
            f"<td><b>{esc(row['symbol'])}</b></td>"
            f"<td>{_fmt_pct(row['actual_weight'])}<div class='subtle'>{_fmt_money(row['actual_notional'])}</div></td>"
            f"<td>{_fmt_pct(row['target_weight'])}<div class='subtle'>{_fmt_money(row['target_notional'])}</div></td>"
            f"<td>{_fmt_pct(row['gap_weight'], signed=True)}<div class='subtle'>{_fmt_money(row['gap_notional'])}</div></td>"
            f"<td><span class='position-action {cls}'>{esc(action)}</span><div class='subtle'>{esc(row['status'])}</div></td>"
            "</tr>"
        )
    body_html = "".join(body) if body else '<tr><td colspan="6">暂无持仓对账数据</td></tr>'
    return (
        "<div class='work-card'>"
        "<h3>当前持仓 vs 系统目标 <span class='subtle'>Position Gap</span></h3>"
        "<div class='position-table-wrap'>"
        "<table>"
        "<thead><tr><th>类别</th><th>标的</th><th>当前</th><th>目标</th><th>目标缺口</th><th>动作 / 状态</th></tr></thead>"
        f"<tbody>{body_html}</tbody>"
        "</table>"
        "</div>"
        "</div>"
    )


def _render_position_desk(payload: Dict[str, Any], history: List[Dict[str, Any]]) -> str:
    ibkr = payload.get("ibkr") or {}
    stale = bool(ibkr.get("snapshot_stale"))
    _age_s = _float(ibkr.get("snapshot_age_seconds"), 0.0)
    _age_txt = f"约 {_age_s / 3600:.0f} 小时前" if _age_s else "陈旧"
    _dim_attr = ' style="opacity:.45"' if stale else ''
    rows = _position_gap_rows(payload)
    buy_gap = sum(max(0.0, _float(row.get("gap_notional"), 0.0)) for row in rows if row.get("category") != "额外持仓")
    sell_gap = sum(abs(min(0.0, _float(row.get("gap_notional"), 0.0))) for row in rows)
    max_gap = max((abs(_float(row.get("gap_weight"), 0.0)) for row in rows), default=0.0)
    extra_count = sum(1 for row in rows if row.get("category") == "额外持仓")
    body = []
    for row in rows:
        action, cls = _position_action(row["gap_weight"], row["category"])
        body.append(
            "<tr>"
            f"<td>{esc(row['category'])}</td>"
            f"<td><b>{esc(row['symbol'])}</b><div class='subtle'>{esc(row.get('note', ''))}</div></td>"
            f"<td>{_fmt_pct(row['actual_weight'])}<div class='subtle'>{_fmt_money(row['actual_notional'])} · {_fmt_num(row.get('actual_shares'))}股</div></td>"
            f"<td>{_fmt_pct(row['target_weight'])}<div class='subtle'>{_fmt_money(row['target_notional'])}</div></td>"
            f"<td>{_fmt_pct(row['gap_weight'], signed=True)}<div class='subtle'>{_fmt_money(row['gap_notional'])}</div></td>"
            f"<td><span class='position-action {cls}'{_dim_attr}>{esc(action)}</span><div class='subtle'>{esc(row['status'])}</div></td>"
            "</tr>"
        )
    body_html = "".join(body) if body else '<tr><td colspan="6">暂无持仓对账数据</td></tr>'
    return f"""
    <section>
      <h2>当前持仓 + IBKR 对账 / Position Desk</h2>
      {(f'<div style="background:#fef3c7;border:1px solid #f59e0b;border-radius:8px;padding:10px 12px;margin-bottom:10px;color:#92400e;font-weight:700">⚠️ IBKR 快照{esc(_age_txt)}（非实时）。下面的买入/卖出股数与金额都据此陈旧快照计算，仅供参考——请勿据此下单，等实时快照恢复再核对。</div>') if stale else ''}
      <div class="position-summary-grid">
        {_metric('IBKR 现有总资产', _fmt_money(ibkr.get('net_liq')))}
        {_metric('需买入缺口', _fmt_money(buy_gap))}
        {_metric('需卖出/额外', _fmt_money(sell_gap))}
        {_metric('最大权重差', _fmt_pct(max_gap))}
        {_metric('额外持仓', esc(extra_count))}
      </div>
      <div class="subtle" style="margin-bottom:8px">source={esc(ibkr.get('source', 'disabled'))} · clientId={esc(ibkr.get('client_id', 'NA'))} · account={esc(ibkr.get('account_id', 'NA'))} · sync={esc(str(ibkr.get('sync_time', ''))[:19])} · max delta {_fmt_pct(ibkr.get('max_abs_delta'))}</div>
      {_warning(ibkr.get('error'))}
      <div class="position-table-wrap">
        <table>
          <thead><tr><th>类别</th><th>标的</th><th>当前仓位</th><th>系统目标</th><th>目标缺口</th><th>动作 / 状态</th></tr></thead>
          <tbody>{body_html}</tbody>
        </table>
      </div>
      {_render_posterior_section(payload, collapsed=True)}
      {_render_ibkr_history_details(history)}
    </section>
    """


def _position_gap_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    ibkr = payload.get("ibkr") or {}
    net_liq = _float(ibkr.get("net_liq"), 0.0)
    rows: List[Dict[str, Any]] = []
    groups = [
        ("策略腿", ibkr.get("trade_symbols", []) or []),
        ("防守腿", ibkr.get("route_legs", []) or []),
        ("额外持仓", ibkr.get("extra_positions", []) or []),
    ]
    for category, items in groups:
        for item in items:
            actual_weight = _float(item.get("actual_weight"), 0.0)
            target_weight = _float(item.get("ideal_weight"), 0.0)
            gap_weight = target_weight - actual_weight
            rows.append({
                "category": category,
                "symbol": str(item.get("symbol") or ""),
                "actual_weight": actual_weight,
                "target_weight": target_weight,
                "gap_weight": gap_weight,
                "actual_notional": _float(item.get("actual_notional"), 0.0),
                "actual_shares": _float(item.get("actual_shares"), 0.0),
                "avg_cost": _float(item.get("avg_cost"), 0.0),
                "target_notional": item.get("ideal_notional", target_weight * net_liq if net_liq else None),
                "gap_notional": gap_weight * net_liq if net_liq else None,
                "status": str(item.get("status", "NA")),
                "note": str(item.get("note") or ""),
            })
    order = {symbol: i for i, symbol in enumerate(TRADE_SYMBOLS)}
    category_order = {"策略腿": 0, "防守腿": 1, "额外持仓": 2}
    rows.sort(key=lambda row: (
        category_order.get(row["category"], 9),
        order.get(row["symbol"], 99),
        -abs(_float(row["gap_weight"], 0.0)),
        row["symbol"],
    ))
    return rows


def _position_action(gap_weight: float, category: str) -> tuple[str, str]:
    if abs(gap_weight) < 0.002:
        return "OK", "hold"
    if gap_weight > 0:
        return "买入缺口", "buy"
    if category == "额外持仓":
        return "额外持仓/人工判断", "sell"
    return "减仓缺口", "sell"


def _render_flow_heat_section(payload: Dict[str, Any]) -> str:
    states = [_flow_state_for_symbol(payload, symbol) for symbol in TRADE_SYMBOLS]
    worst = _worst_flow_symbol(payload)
    weak = _top_flow_components(payload, limit=5, negative_only=False)
    weak_text = " / ".join(f"{esc(row.get('symbol'))} {esc(row.get('severity'))}" for row in weak) or "暂无"
    flow_order = " > ".join(
        f"{state['symbol']} {state['severity']}"
        for state in sorted(states, key=lambda row: _flow_rank(row["severity"]))
    )
    return (
        "<div class='work-card'>"
        "<h3>资金流热力解释 <span class='subtle'>flow heat</span></h3>"
        "<div class='flow-heat-grid'>"
        f"<div class='flow-heat-item'><b>哪个桶最危险</b><div class='mini-note'>{esc(worst['symbol'] + ' / ' + worst['severity']) if worst else '暂无'}</div></div>"
        f"<div class='flow-heat-item'><b>风险排序</b><div class='mini-note'>{flow_order}</div></div>"
        f"<div class='flow-heat-item'><b>主要底层票</b><div class='mini-note'>{weak_text}</div></div>"
        "<div class='flow-heat-item'><b>策略含义</b><div class='mini-note'>已 EXIT/REDUCE 时用于确认风险；HOLD 时升级为观察项。</div></div>"
        "</div>"
        "</div>"
    )


def _dominant_route_text(payload: Dict[str, Any]) -> str:
    routes = []
    for symbol in TRADE_SYMBOLS:
        route = (payload.get("routing") or {}).get(symbol) or {}
        text = _route_text(route)
        if text and "不路由" not in text:
            routes.append(text)
    return routes[0] if routes else "未触发防守路由"


def _flow_state_for_symbol(payload: Dict[str, Any], symbol: str) -> Dict[str, str]:
    flow = payload.get("flow") or {}
    basket = (flow.get("component_baskets") or {}).get(symbol)
    if basket:
        severity = str(basket.get("severity", "MISSING"))
        summary = f"abnormal {basket.get('abnormal_components', 0)}/{basket.get('component_count', 0)}"
        return {"symbol": symbol, "severity": severity, "summary": summary}
    row = (flow.get("symbols") or {}).get(symbol) or {}
    severity = str(row.get("severity", "MISSING"))
    summary = f"CMF {_fmt_num(row.get('cmf20'))} / MFI {_fmt_num(row.get('mfi14'))}"
    return {"symbol": symbol, "severity": severity, "summary": summary}


def _worst_flow_symbol(payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
    states = [_flow_state_for_symbol(payload, symbol) for symbol in TRADE_SYMBOLS]
    available = [state for state in states if state["severity"] != "MISSING"]
    if not available:
        return None
    return sorted(available, key=lambda row: (_flow_rank(row["severity"]), row["symbol"]))[0]


def _top_flow_components(payload: Dict[str, Any], limit: int = 5, negative_only: bool = True) -> List[Dict[str, Any]]:
    components: List[Dict[str, Any]] = []
    flow = payload.get("flow") or {}
    for basket in (flow.get("component_baskets") or {}).values():
        for row in basket.get("components") or []:
            if negative_only and _float(row.get("legacy_signed_5d"), 0.0) >= 0:
                continue
            components.append(row)
    components.sort(key=lambda row: (
        _flow_rank(str(row.get("severity", "MISSING"))),
        _float(row.get("legacy_signed_5d"), 0.0),
        str(row.get("symbol", "")),
    ))
    return components[:limit]


def _flow_rank(severity: str) -> int:
    return {"SEVERE": 0, "ABNORMAL": 1, "WATCH": 2, "NORMAL": 3, "MISSING": 4}.get(str(severity), 5)


def _flow_heat_cell(value: Any, lo: float, hi: float, digits: int = 2) -> str:
    try:
        val = float(value)
    except (TypeError, ValueError):
        return "<td class='flow-heat-cell flow-neutral'>—</td>"
    clipped = max(lo, min(hi, val))
    span = (hi - lo) or 1.0
    frac = (clipped - lo) / span
    if frac < 0.20:
        cls = "flow-hot-neg"
    elif frac < 0.45:
        cls = "flow-mid-neg"
    elif frac > 0.80:
        cls = "flow-hot-pos"
    elif frac > 0.55:
        cls = "flow-mid-pos"
    else:
        cls = "flow-neutral"
    text = f"{val:.{digits}f}"
    return f"<td class='flow-heat-cell {cls}'>{esc(text)}</td>"


def _flow_divergence(symbol: str, rows: List[Dict[str, Any]], fund_flow: Dict[str, Any]) -> str:
    if not rows:
        return ""
    worst = rows[0]
    try:
        fund_cmf = float(fund_flow.get("cmf20"))
        worst_cmf = float(worst.get("cmf20"))
    except (TypeError, ValueError):
        return ""
    if fund_cmf > 0 and worst_cmf < 0 and str(worst.get("severity")) in {"SEVERE", "ABNORMAL"}:
        return (
            "<div class='warning-box' style='margin-top:8px'>"
            f"背离：{esc(symbol)} 基金层 CMF {_fmt_num(fund_cmf)} 仍为正，但 {esc(worst.get('symbol'))} "
            f"底层量价流向信号恶化（CMF {_fmt_num(worst_cmf)}，5日方向成交额代理 {_fmt_flow_money(worst.get('legacy_signed_5d'))}）。"
            "</div>"
        )
    return ""


def _render_decision_workbench(payload: Dict[str, Any]) -> str:
    return f"""
    <section>
      <h2>决策工作台 / Decision Workbench</h2>
      <div class="workbench-grid">
        {_render_hard_valve_panel(payload)}
        {_render_reentry_lock_panel(payload)}
        {_render_top_factor_panel(payload)}
      </div>
      {_render_p3_visuals(payload)}
    </section>
    """


def _render_hard_valve_panel(payload: Dict[str, Any]) -> str:
    rows: List[str] = []
    scores = payload.get("scores") or {}
    layers = payload.get("decision_layers") or {}
    for symbol in TRADE_SYMBOLS:
        score = scores.get(symbol) or {}
        hv_state = ((layers.get(symbol) or {}).get("hard_valve_state") or {})
        candidates = _valve_candidates_for(score, hv_state)
        hits = list(score.get("hard_valve_hits") or hv_state.get("ids") or [])
        pending = list(hv_state.get("pending_ids") or hv_state.get("pending") or [])
        if candidates:
            badge = _valve_summary_badge(candidates)
            detail = _render_valve_candidate_grid(candidates)
        elif hits:
            badge = _badge("已触发", "danger")
            detail = f"<div class='mini-note'>{esc(_valve_reason_text(score, hits))}</div>"
        elif pending:
            badge = _badge("PENDING", "warn")
            detail = f"<div class='mini-note'>{esc('等待确认：' + ', '.join(str(item) for item in pending))}</div>"
        else:
            badge = _badge("未触发", "ok")
            detail = f"<div class='mini-note'>{esc(_valve_distance_text(symbol, payload))}</div>"
        rows.append(
            "<div class='symbol-strip-row'>"
            f"<div class='row-head'><span class='row-title'>{esc(symbol)}</span>{badge}</div>"
            f"{detail}"
            "</div>"
        )
    return (
        "<div class='work-card'>"
        "<h3>硬阀门全景 <span class='subtle'>triggered / pending / distance</span></h3>"
        f"<div class='symbol-strip'>{''.join(rows)}</div>"
        "</div>"
    )


def _render_reentry_lock_panel(payload: Dict[str, Any]) -> str:
    rows: List[str] = []
    scores = payload.get("scores") or {}
    reentry = payload.get("reentry") or {}
    state_payload = payload.get("reentry_state") or {}
    states = state_payload.get("states") or {}
    for symbol in TRADE_SYMBOLS:
        plan = reentry.get(symbol) or {}
        score = scores.get(symbol) or {}
        state = states.get(symbol) or {}
        final_score = _float(score.get("final_score"), 0.0)
        c_score = _float((score.get("module_scores") or {}).get("C"), 0.0)
        eligible = bool(plan.get("eligible"))
        lock_reason = str(plan.get("locked_reason") or ("unlocked" if eligible else "NA"))
        tranche = str(plan.get("tranche") or state.get("last_tranche") or "NA")
        t1 = bool(state.get("t1_active")) or tranche == "T1"
        t2 = bool(state.get("t2_active")) or tranche == "T2"
        t3 = tranche == "T3"
        rows.append(
            "<div class='symbol-strip-row'>"
            f"<div class='row-head'><span class='row-title'>{esc(symbol)}</span>{_badge('UNLOCKED' if eligible else 'LOCKED', 'ok' if eligible else 'warn')}</div>"
            "<table>"
            "<tbody>"
            f"{_tr('时间锁', esc(lock_reason), '解锁条件：距上次卖出 ≥ 11 个交易日')}"
            f"{_tr('分数锁', _fmt_num(final_score), '解锁条件：总分 < 19')}"
            f"{_tr('结构锁', _fmt_num(c_score), '解锁条件：C < 5 且背离解除')}"
            f"{_tr('批次状态', f'T1={esc(t1)} / T2={esc(t2)} / T3={esc(t3)}', esc('; '.join(plan.get('explain') or []) or state.get('updated_at', '')))}"
            "</tbody>"
            "</table>"
            "</div>"
        )
    return (
        "<div class='work-card'>"
        "<h3>再入场三锁 <span class='subtle'>time / score / structure</span></h3>"
        f"<div class='symbol-strip'>{''.join(rows)}</div>"
        "</div>"
    )


def _render_daily_diff_panel(payload: Dict[str, Any]) -> str:
    path = _latest_daily_diff_path(str(payload.get("as_of") or ""))
    if not path:
        body = "<div class='diff-box'>首日无对比：未找到 post-run diff。</div>"
        source = "no diff"
    else:
        body = f"<div class='diff-box'>{_markdown_to_html(path.read_text(encoding='utf-8'))}</div>"
        source = path.relative_to(REPO_ROOT).as_posix() if _is_relative_to(path, REPO_ROOT) else str(path)
    return (
        "<div class='work-card'>"
        f"<h3>今日变化 <span class='subtle'>{esc(source)}</span></h3>"
        f"{body}"
        "</div>"
    )


def _render_top_factor_panel(payload: Dict[str, Any]) -> str:
    blocks: List[str] = []
    for symbol in TRADE_SYMBOLS:
        score = (payload.get("scores") or {}).get(symbol) or {}
        factors = _top_factor_items(score, limit=5)
        rows = []
        for module, row in factors:
            rows.append(
                "<tr>"
                f"<td>{esc(symbol)}<div class='subtle'>{esc(module)}</div></td>"
                f"<td><b>{esc(row.get('factor_id', row.get('name', '')))}</b></td>"
                f"<td>{_fmt_num(row.get('score'))} / {_fmt_num(row.get('max_score'))}</td>"
                f"<td>{_factor_explain_cell(row)}</td>"
                "</tr>"
            )
        blocks.append("".join(rows) or f"<tr><td colspan='4'>{esc(symbol)} 暂无正贡献因子</td></tr>")
    return (
        "<div class='work-card'>"
        "<h3>Top 5 因子贡献 <span class='subtle'>per symbol</span></h3>"
        "<table>"
        "<thead><tr><th>标的/模块</th><th>因子</th><th>得分</th><th>解释</th></tr></thead>"
        f"<tbody>{''.join(blocks)}</tbody>"
        "</table>"
        "</div>"
    )


def _render_factor_map_panel(payload: Dict[str, Any]) -> str:
    observed = _observed_factor_rows(payload)
    catalog = _factor_catalog(payload, observed)
    lifecycle = decision_input_lifecycle(payload)
    table_rows: List[str] = []
    for module in ("A", "B", "C", "D"):
        module_rows = [
            row
            for row in catalog
            if row["module"] == module and _float(row.get("max_score"), 0.0) > 0
        ]
        if not module_rows:
            continue
        table_rows.append(
            "<tr class='factor-module-row'>"
            f"<td colspan='6'>{esc(FACTOR_MODULE_LABELS.get(module, module))}</td>"
            "</tr>"
        )
        for row in module_rows:
            meta = row["meta"]
            table_rows.append(
                "<tr>"
                f"<td>{esc(module)}</td>"
                f"<td><b>{esc(row['factor_id'])}</b></td>"
                f"<td>{_fmt_num(row.get('max_score'))}</td>"
                f"<td>{esc(meta.get('plain_explain') or meta.get('professional_explain') or '—')}</td>"
                f"<td>{esc(meta.get('professional_explain') or meta.get('plain_explain') or '—')}</td>"
                f"<td>{_factor_current_score_html(row['factor_id'], observed, lifecycle)}<div class='subtle'>{esc(meta.get('data_hint') or '—')}</div></td>"
                "</tr>"
            )
    placeholder_rows: List[str] = []
    for row in catalog:
        if _float(row.get("max_score"), 0.0) > 0:
            continue
        meta = row["meta"]
        placeholder_rows.append(
            "<tr>"
            f"<td>{esc(row['module'])}</td>"
            f"<td><b>{esc(row['factor_id'])}</b></td>"
            f"<td>{esc(meta.get('plain_explain') or meta.get('professional_explain') or '—')}</td>"
            f"<td>{_factor_current_score_text(row['factor_id'], observed)}"
            "<div class='subtle'>不计分 · 不进入策略 missing_weight</div></td>"
            "</tr>"
        )
    placeholder_html = (
        "<details class='non-scoring-placeholders' style='margin-top:10px'>"
        "<summary>非计分占位 <span class='subtle'>max_score=0，不影响策略缺失权重</span></summary>"
        "<div class='detail-body'><div class='table-scroll'><table>"
        "<thead><tr><th>模块</th><th>占位因子</th><th>用途</th><th>当前状态</th></tr></thead>"
        f"<tbody>{''.join(placeholder_rows)}</tbody>"
        "</table></div></div></details>"
        if placeholder_rows
        else ""
    )
    empty_rows = "<tr><td colspan='6'>暂无因子定义。</td></tr>"
    return (
        "<details class='work-card factor-map' style='margin-top:10px'>"
        "<summary>全量打分因子表 / Factor Map <span class='subtle'>计分因子按 A/B/C/D 分组，非计分占位单独折叠</span></summary>"
        "<div class='detail-body'>"
        "<div class='table-scroll'>"
        "<table>"
        "<thead><tr><th>模块</th><th>因子</th><th>上限</th><th>看什么</th><th>何时加分</th><th>当前分 / 数据</th></tr></thead>"
        f"<tbody>{''.join(table_rows) if table_rows else empty_rows}</tbody>"
        "</table>"
        "</div>"
        f"{placeholder_html}"
        "</div>"
        "</details>"
    )


def _observed_factor_rows(payload: Dict[str, Any]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for symbol, score in (payload.get("scores") or {}).items():
        if not isinstance(score, dict):
            continue
        for module, rows in (score.get("factor_scores") or {}).items():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                factor_id = str(row.get("factor_id") or "")
                if not factor_id:
                    continue
                enriched = dict(row)
                enriched.setdefault("module", str(module))
                out.setdefault(factor_id, {})[str(symbol)] = enriched
    return out


def _factor_catalog(payload: Dict[str, Any], observed: Dict[str, Dict[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    for definition in _factor_definitions_for_map():
        factor_id = str(definition.factor_id)
        if factor_id in by_id:
            by_id[factor_id]["max_score"] = max(_float(by_id[factor_id].get("max_score"), 0.0), _float(definition.max_score, 0.0))
            continue
        by_id[factor_id] = {
            "factor_id": factor_id,
            "module": str(definition.module),
            "max_score": definition.max_score,
            "meta": explain_factor(factor_id, str(definition.module)),
        }
    for factor_id, by_symbol in observed.items():
        sample = next(iter(by_symbol.values()), {})
        module = str(sample.get("module") or factor_id[:1] or "")
        meta = {
            "professional_explain": sample.get("professional_explain") or explain_factor(factor_id, module).get("professional_explain", ""),
            "plain_explain": sample.get("plain_explain") or explain_factor(factor_id, module).get("plain_explain", ""),
            "data_hint": sample.get("data_hint") or explain_factor(factor_id, module).get("data_hint", ""),
        }
        by_id.setdefault(
            factor_id,
            {
                "factor_id": factor_id,
                "module": module,
                "max_score": sample.get("max_score"),
                "meta": meta,
            },
        )
    order = {"A": 0, "B": 1, "C": 2, "D": 3}
    return sorted(by_id.values(), key=lambda row: (order.get(str(row.get("module")), 9), str(row.get("factor_id"))))


def _factor_definitions_for_map() -> List[Any]:
    definitions: List[Any] = []
    definitions.extend(module_a_factors())
    for symbol in TRADE_SYMBOLS:
        definitions.extend(module_b_factors(symbol))
    definitions.extend(module_c_factors())
    for symbol in TRADE_SYMBOLS:
        definitions.extend(module_d_factors(symbol))
    return definitions


def _factor_current_score_text(factor_id: str, observed: Dict[str, Dict[str, Dict[str, Any]]]) -> str:
    rows = observed.get(factor_id) or {}
    parts = []
    for symbol in TRADE_SYMBOLS:
        row = rows.get(symbol)
        if not row:
            continue
        parts.append(f"{symbol} {_fmt_num(row.get('score'))}/{_fmt_num(row.get('max_score'))}")
    return esc(" · ".join(parts) if parts else "—")


def _factor_current_score_html(
    factor_id: str,
    observed: Dict[str, Dict[str, Dict[str, Any]]],
    lifecycle: Dict[str, Any],
) -> str:
    base = _factor_current_score_text(factor_id, observed)
    notes: List[str] = []
    if factor_id == "A2_NAAIM" and lifecycle.get("retired_naaim"):
        notes.append("已退役来源，等待 SLO 缺失路径")
    if factor_id == "B6_VALUATION_HEAT":
        missing_points = _float(lifecycle.get("mstr_b6_missing_points"), 0.0)
        if missing_points > 0:
            points = int(missing_points) if missing_points.is_integer() else missing_points
            notes.append(f"MSTR：计分输入缺失 {points} 分")
    return base + "".join(f"<div class='subtle'>{esc(note)}</div>" for note in notes)


def _render_p3_visuals(payload: Dict[str, Any]) -> str:
    return f"""
      <div class="risk-routing-block">
        <h3>风险与路由解释 <span class='subtle'>Portfolio Risk / stress / DEFCON</span></h3>
        <div class="risk-routing-grid">
          {_render_risk_contribution_panel(payload)}
          {_render_stress_scenario_panel(payload)}
          {_render_defcon_chain_panel(payload)}
        </div>
      </div>
    """


def _portfolio_has_no_active_risk_legs(payload: Dict[str, Any]) -> bool:
    block = payload.get("portfolio_risk") or {}
    if not isinstance(block, dict) or not block:
        return False
    if str(block.get("binding_constraint") or "") == "NO_ACTIVE_LEGS":
        return True
    legs = block.get("legs_used")
    if isinstance(legs, list) and not legs:
        weights = block.get("target_weights") or {}
        return (
            isinstance(weights, dict)
            and bool(weights)
            and all(abs(_float(weight, 0.0)) <= 1e-9 for weight in weights.values())
        )
    return False


def _no_active_risk_legs_note() -> str:
    return (
        "<div class='mini-note'>当前风险腿目标为 0；防守腿路由后风险尚未纳入该 ex-ante "
        "风险视图，持仓执行以今日操作台和 DEFCON 路由为准。</div>"
    )


def _render_risk_contribution_panel(payload: Dict[str, Any]) -> str:
    block = payload.get("risk_contributions") or {}
    if not block:
        if _portfolio_has_no_active_risk_legs(payload):
            body = _no_active_risk_legs_note()
        else:
            body = "<div class='mini-note'>等待下一次日跑写入 risk_contributions。</div>"
    elif block.get("_error"):
        body = f"<div class='warning-box'>{esc(block.get('_error'))}</div>"
    else:
        rows = []
        for symbol, row in sorted((item for item in block.items() if item[0] != "_portfolio"),
                                  key=lambda item: _float((item[1] or {}).get("vol_contribution_pct"), 0.0),
                                  reverse=True):
            pct = max(0.0, min(1.0, _float((row or {}).get("vol_contribution_pct"), 0.0)))
            rows.append(
                "<div class='risk-bar-row'>"
                f"<div class='risk-bar-label'>{esc(symbol)}</div>"
                f"<div class='risk-bar-track'><div class='risk-bar-fill' style='width:{pct*100:.1f}%'></div></div>"
                f"<div>{_fmt_pct(pct)}<div class='subtle'>vol {_fmt_pct((row or {}).get('vol_contribution'))}</div></div>"
                "</div>"
        )
        portfolio = block.get("_portfolio") or {}
        row_html = "".join(rows) if rows else "<div class='mini-note'>暂无非零风险贡献。</div>"
        body = (
            f"<div class='subtle'>portfolio forecast vol {_fmt_pct(portfolio.get('forecast_vol'))}</div>"
            f"{row_html}"
        )
    return (
        "<div class='work-card'>"
        "<h3>风险贡献条形图 <span class='subtle'>ex-ante vol</span></h3>"
        f"{body}"
        "</div>"
    )


def _render_stress_scenario_panel(payload: Dict[str, Any]) -> str:
    scenarios = payload.get("stress_scenarios") or []
    if not scenarios:
        if _portfolio_has_no_active_risk_legs(payload):
            body = _no_active_risk_legs_note()
        else:
            body = "<div class='mini-note'>等待下一次日跑写入 stress_scenarios。</div>"
    else:
        cards = []
        for row in scenarios:
            if row.get("_error"):
                cards.append(f"<div class='stress-card warning-box'>{esc(row.get('_error'))}</div>")
                continue
            name = str(row.get("name") or "scenario")
            if row.get("est_pnl_pct") is not None:
                val = _float(row.get("est_pnl_pct"), 0.0)
                kind = "danger" if val < 0 else "ok"
                cards.append(
                    "<div class='stress-card'>"
                    f"<div class='row-head'><b>{esc(name)}</b>{_badge(_fmt_pct(val/100.0, signed=True), kind)}</div>"
                    "<div class='mini-note'>估算当前目标账本冲击损益</div>"
                    "</div>"
                )
            else:
                before = _float(row.get("forecast_vol_before"), 0.0)
                after = _float(row.get("forecast_vol_after"), 0.0)
                ratio = after / before if before > 0 else 0.0
                cards.append(
                    "<div class='stress-card'>"
                    f"<div class='row-head'><b>{esc(name)}</b>{_badge('vol x ' + _fmt_num(ratio), 'warn' if ratio > 1 else 'ok')}</div>"
                    f"{_mini_vol_svg(before, after)}"
                    f"<div class='mini-note'>before {_fmt_pct(before)} -> after {_fmt_pct(after)}</div>"
                    "</div>"
                )
        body = f"<div class='stress-grid'>{''.join(cards)}</div>"
    return (
        "<div class='work-card'>"
        "<h3>四情景压力测试 <span class='subtle'>QQQ / BTC / corr / VIX</span></h3>"
        f"{body}"
        "</div>"
    )


def _render_defcon_chain_panel(payload: Dict[str, Any]) -> str:
    ctx = payload.get("routing_context") or {}
    if not ctx:
        body = "<div class='mini-note'>等待下一次日跑写入 routing_context。</div>"
    elif ctx.get("_error"):
        body = f"<div class='warning-box'>{esc(ctx.get('_error'))}</div>"
    else:
        qqq = ctx.get("qqq") or {}
        module_a = ctx.get("module_a") or {}
        brkb = ctx.get("brkb_defense") or {}
        qqq_broken = any(bool(qqq.get(key)) for key in ("below_ma200", "below_ema50", "below_ema20"))
        max_a = max([_float(v, 0.0) for v in module_a.values()] or [0.0])
        defcon1_ready = max_a >= 12 and qqq_broken
        brkb_degraded = bool(brkb.get("degraded"))
        body = (
            "<div class='condition-chain'>"
            f"<div class='condition-step {'pass' if defcon1_ready else 'fail'}'>"
            f"<div class='row-head'><b>DEFCON1</b>{_badge('MATCH' if defcon1_ready else 'not now', 'danger' if defcon1_ready else 'watch')}</div>"
            f"<div class='mini-note'>{esc(ctx.get('defcon1_rule'))}</div>"
            f"<div class='mini-note'>max A={_fmt_num(max_a)} · QQQ close {_fmt_money(qqq.get('close'))} / EMA20 {_fmt_money(qqq.get('ema20'))} / EMA50 {_fmt_money(qqq.get('ema50'))} / MA200 {_fmt_money(qqq.get('ma200'))}</div>"
            "</div>"
            "<div class='condition-step pass'>"
            f"<div class='row-head'><b>DEFCON2</b>{_badge('BRK.B degraded' if brkb_degraded else 'BRK.B usable', 'warn' if brkb_degraded else 'ok')}</div>"
            f"<div class='mini-note'>{esc(ctx.get('defcon2_rule'))}</div>"
            f"<div class='mini-note'>BRK.B reason={esc(brkb.get('reason', 'NA'))} · corr={_fmt_num(brkb.get('corr_to_spy'))} / threshold {_fmt_num(brkb.get('threshold'))}</div>"
            f"{_correlation_gauge(brkb.get('corr_to_spy'), brkb.get('threshold'))}"
            "</div>"
            "<div class='condition-step'>"
            f"<div class='row-head'><b>DEFCON3</b>{_badge('1x same-thesis route', 'watch')}</div>"
            "<div class='mini-note'>SOXL -> SOXX · FNGU -> QQQ · MSTR -> BTC-USD；未命中 DEFCON1/2 时走常规去杠杆。</div>"
            "</div>"
            "</div>"
        )
    return (
        "<div class='work-card'>"
        "<h3>DEFCON 条件链 <span class='subtle'>routing_context</span></h3>"
        f"{body}"
        "</div>"
    )


def _render_kpis(payload: Dict[str, Any]) -> str:
    risk = payload.get("portfolio_risk", {})
    regime = payload.get("regime", {})
    dq = payload.get("data_quality", {})
    ibkr = payload.get("ibkr") or {}
    vix_pct = regime.get("vix_percentile")
    gross = risk.get("gross_scaler", risk.get("effective_gross_scaler"))
    return f"""
    <section>
      <h2>System Health / Portfolio Risk / 系统状态</h2>
      <div class="kpis" style="margin:0">
      <div class="kpi">
        <div class="label">策略输入质量</div>
        <div class="value">{esc(dq.get('level', 'NA'))}</div>
        <div class="note">overall {_fmt_num(dq.get('overall_score'))} · latency {_fmt_num(dq.get('latency_score'))}</div>
      </div>
      <div class="kpi">
        <div class="label">市场状态</div>
        <div class="value">{esc(regime.get('current', 'NA'))}</div>
        <div class="note">VIX pct {_fmt_num(vix_pct)} · QQQ { _fmt_money((regime.get('inputs') or {}).get('QQQ.close')) }</div>
      </div>
      <div class="kpi">
        <div class="label">组合风险</div>
        <div class="value">{_fmt_pct(risk.get('forecast_portfolio_vol'))}</div>
        <div class="note">gross {_fmt_num(gross)} · corr {esc(risk.get('corr_regime', 'NA'))}</div>
      </div>
      <div class="kpi">
        <div class="label">IBKR 对账</div>
        <div class="value">{esc(ibkr.get('source', 'disabled'))}</div>
        <div class="note">NetLiq {_fmt_money(ibkr.get('net_liq'))} · max delta {_fmt_pct(ibkr.get('max_abs_delta'))}</div>
      </div>
      </div>
    </section>
    """


def _render_today_ops(
    payload: Dict[str, Any],
    *,
    embedded: bool = False,
    show_title: bool = True,
    show_headline: bool = True,
) -> str:
    ops = payload.get("today_ops") or {}
    intents = payload.get("action_intents") or {}
    state = payload.get("state") or {}
    destinations = _execution_destination_totals(payload)
    dest_text = _format_destination_totals(destinations) or "无资金路由"
    amounts_are_estimates = bool(ops.get("destinations_are_estimates"))
    destination_label = "估算资金去向" if amounts_are_estimates else "执行计划资金去向"
    amount_warning = (
        "<div class='warning-box' style='margin-top:8px'><b>金额层未就绪：</b>"
        "策略方向与目标权重仍有效；金额/股数仅为估算，等待新鲜 IBKR 对账后再生成差额动作。</div>"
        if amounts_are_estimates else ""
    )
    route_text = _dominant_route_text(payload)
    mismatch = _route_execution_mismatch(payload)
    reasons = ops.get("top_reasons") or []
    reason_rows = "".join(f"<li>{esc(item)}</li>" for item in reasons[:3])
    cards = []
    for symbol in TRADE_SYMBOLS:
        cards.append(_render_intent_card(symbol, payload))
    headline_html = (
        f"<div class=\"ops-headline\">{esc(ops.get('headline', '暂无结论'))}</div>"
        if show_headline else ""
    )
    body = f"""
      <div class="ops-desk">
        <div class="ops-main">
          <div class="subtle">advisory only · 不下单 · state_db={esc(Path(str(state.get('db_path', ''))).name if state.get('db_path') else 'NA')} · run={esc(state.get('score_run_id', 'NA'))}</div>
          {headline_html}
          <div class="subtle">动作数 {esc(ops.get('action_count', 0))} · 策略输入质量 {esc(ops.get('data_quality', 'NA'))} {_fmt_num(ops.get('data_quality_score'))} · IBKR {esc(ops.get('ibkr_source', 'NA'))}{' · STALE' if ops.get('ibkr_stale') else ''}</div>
          <div style="margin-top:10px"><b>DEFCON 路由：</b>{route_text}</div>
          <div style="margin-top:6px"><b>{destination_label}：</b>{dest_text}</div>
          {amount_warning}
          {mismatch}
          <details style="margin-top:10px">
            <summary>核心原因 / 失效前提</summary>
            <div class="detail-body">
              <ol>{reason_rows or '<li>暂无强制动作原因。</li>'}</ol>
              <div class="subtle">失效条件在每个标的卡的“唯一处置指令”里展开。</div>
            </div>
          </details>
        </div>
        <div class="intent-grid">{''.join(cards)}</div>
      </div>
    """
    if embedded:
        title_html = (
            "<h3>今日操作台 / One Command Desk <span class='subtle'>route vs execution</span></h3>"
            if show_title else ""
        )
        return (
            "<div class='work-card ops-work-card'>"
            f"{title_html}"
            f"{body}"
            "</div>"
        )
    return f"""
    <section>
      <h2>今日操作台 / One Command Desk</h2>
      {body}
    </section>
    """


def _execution_destination_totals(payload: Dict[str, Any]) -> Dict[str, float]:
    totals: Dict[str, float] = {}
    for intent in (payload.get("action_intents") or {}).values():
        legs = ((intent.get("trade_plan") or {}).get("legs") or [])
        if legs:
            for leg in legs:
                if str(leg.get("role") or "") != "defense_route":
                    continue
                symbol = str(leg.get("symbol") or "")
                if symbol:
                    totals[symbol] = totals.get(symbol, 0.0) + _float(leg.get("target_notional"), 0.0)
        else:
            symbol = str(intent.get("target_symbol") or "")
            notional = _float(intent.get("target_notional"), 0.0)
            if symbol and notional:
                totals[symbol] = totals.get(symbol, 0.0) + notional
    if totals:
        return totals
    return {str(k): _float(v, 0.0) for k, v in ((payload.get("today_ops") or {}).get("destinations") or {}).items()}


def _format_destination_totals(destinations: Dict[str, float]) -> str:
    items = [(symbol, value) for symbol, value in sorted(destinations.items()) if abs(value) > 1e-9]
    return ", ".join(f"{esc(symbol)} {_fmt_money(value)}" for symbol, value in items)


def _route_execution_mismatch(payload: Dict[str, Any]) -> str:
    route_symbols = _routing_destination_symbols(payload)
    execution_symbols = {symbol for symbol, value in _execution_destination_totals(payload).items() if abs(value) > 1e-9}
    if not route_symbols or route_symbols == execution_symbols:
        return "<div class='mini-note'>路由与执行计划一致：以 action_intents.trade_plan.legs 为准。</div>"
    missing = sorted(route_symbols - execution_symbols)
    extra = sorted(execution_symbols - route_symbols)
    bits = []
    if missing:
        bits.append("DEFCON 路由包含但执行腿未展开：" + ", ".join(missing))
    if extra:
        bits.append("执行腿额外包含：" + ", ".join(extra))
    return (
        "<div class='warning-box' style='margin-top:8px'>"
        "<b>路由/执行口径不一致：</b>"
        f"{esc('；'.join(bits))}。当前操作台资金去向按执行腿显示；请刷新 payload 或检查 action_intents 接线。"
        "</div>"
    )


def _routing_destination_symbols(payload: Dict[str, Any]) -> set[str]:
    symbols: set[str] = set()
    for route in (payload.get("routing") or {}).values():
        if not route or route.get("applies") is False:
            continue
        weights = route.get("weights") or {}
        if weights:
            symbols.update(str(symbol) for symbol in weights.keys() if symbol)
        elif route.get("destination"):
            symbols.add(str(route.get("destination")))
    return symbols


def _render_intent_card(symbol: str, payload: Dict[str, Any]) -> str:
    row = (payload.get("action_intents") or {}).get(symbol) or {}
    score = (payload.get("scores") or {}).get(symbol) or {}
    status = str(row.get("status", "NA"))
    command_rows = _intent_trade_rows(symbol, payload)
    command_text = _plain_command(symbol, row, command_rows)
    status_note = _score_status_note(score, status)
    execution_ready = bool(row.get("execution_ready"))
    strategy_level = row.get("strategy_confidence_level", row.get("confidence_level", "NA"))
    strategy_score = row.get("strategy_confidence_score", row.get("confidence_score"))
    amount_level = row.get("execution_amount_confidence_level", "NA")
    amount_score = row.get("execution_amount_confidence_score")
    amount_note = (
        "<div class='warning-box' style='margin-top:8px'>金额/股数仅为估算；"
        "等待新鲜 IBKR 对账后生成差额动作。</div>"
        if not execution_ready else ""
    )
    table_rows = []
    for plan in command_rows:
        table_rows.append(
            "<tr>"
            f"<td><b>{esc(plan['symbol'])}</b><div class='subtle'>{esc(plan['role_label'])}</div></td>"
            f"<td>{_fmt_pct(plan['target_weight'])}<div class='subtle'>{_fmt_money(plan['target_notional'])}</div></td>"
            f"<td>{_fmt_num(plan['target_shares'])}<div class='subtle'>@ {_fmt_money(plan['reference_price'])}</div></td>"
            f"<td>{_fmt_num(plan['current_shares'])}<div class='subtle'>{_fmt_pct(plan['current_weight'])}</div></td>"
            f"<td class='{esc(plan['trade_class'])}'>{esc(plan['trade_label'])}<div class='subtle'>{_fmt_num(abs(plan['delta_shares']))}股 · {_fmt_pct(abs(plan['delta_weight']))}</div></td>"
            "</tr>"
        )
    body_rows = "".join(table_rows) or "<tr><td colspan='5'>暂无计划</td></tr>"
    return (
        "<div class='intent-card'>"
        f"<b>{esc(symbol)}</b> {_badge(status, _status_kind(status))}"
        f"<div class='action'>系统裁决：{esc(_action_cn(row.get('action')))}</div>"
        f"{status_note}"
        f"<div class='plain-command'>{command_text}</div>"
        "<div class='intent-plan'>"
        "<table>"
        "<thead><tr><th>腿</th><th>目标占比/金额</th><th>目标股数</th><th>当前IBKR</th><th>差额动作</th></tr></thead>"
        f"<tbody>{body_rows}</tbody>"
        "</table>"
        "</div>"
        f"{amount_note}"
        f"<div class='target'>策略置信度 {esc(strategy_level)} {_fmt_num(strategy_score)} · "
        f"金额置信度 {esc(amount_level)} {_fmt_num(amount_score)}"
        f"{' · 当前 IBKR → 目标仓位差额可用' if execution_ready else ' · 不作为下单清单'}</div>"
        "</div>"
    )


def _score_status_note(score: Dict[str, Any], final_status: str) -> str:
    score_value = _num_or_none(score.get("final_score"))
    explain = [str(item) for item in (score.get("explain") or [])]
    base_line = next((item for item in explain if item.startswith("Base score status:")), "")
    base_status = ""
    if base_line:
        base_status = base_line.split(":", 1)[1].strip().split(" ", 1)[0]
    force_line = next(
        (
            item for item in explain
            if "minimum " in item or item.startswith("Hard valve override") or "buffer floor" in item
        ),
        "",
    )
    if not base_line and not force_line:
        return ""
    if not base_status:
        base_status = final_status
    bits = [f"分数 {_fmt_num(score_value)} → 分数档 {base_status}"]
    if force_line and final_status != base_status:
        bits.append(f"裁决档 {final_status}（{force_line}）")
    elif final_status:
        bits.append(f"裁决档 {final_status}")
    return f"<div class='mini-note' style='margin-top:6px'>{esc('；'.join(bits))}</div>"


def _intent_trade_rows(symbol: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    intent = (payload.get("action_intents") or {}).get(symbol) or {}
    legs = ((intent.get("trade_plan") or {}).get("legs") or [])
    if not legs:
        target_symbol = str(intent.get("target_symbol") or symbol)
        legs = [{
            "role": "risk" if target_symbol == symbol else "defense_route",
            "symbol": target_symbol,
            "target_weight": intent.get("target_weight"),
            "target_notional": intent.get("target_notional"),
            "reference_price": intent.get("reference_price"),
            "target_shares": intent.get("target_shares"),
        }]
    out = []
    execution_ready = bool(intent.get("execution_ready"))
    for leg in legs:
        target_symbol = str(leg.get("symbol") or "")
        role = str(leg.get("role") or "risk")
        target_weight = _float(leg.get("target_weight"), 0.0)
        target_notional = _float(leg.get("target_notional"), 0.0)
        target_shares = _float(leg.get("target_shares"), 0.0)
        reference_price = leg.get("reference_price")
        current = _current_position_for_leg(payload, symbol, target_symbol, role, target_weight)
        delta_shares = target_shares - current["shares"]
        delta_notional = target_notional - current["notional"]
        delta_weight = target_weight - current["weight"]
        if execution_ready:
            trade_label, trade_class = _trade_delta_label(delta_shares, delta_notional, delta_weight)
        else:
            trade_label, trade_class = "待 IBKR 刷新", "trade-hold"
        out.append({
            "symbol": target_symbol,
            "role": role,
            "role_label": "风险腿" if role == "risk" else "防守去向",
            "target_weight": target_weight,
            "target_notional": target_notional,
            "target_shares": target_shares,
            "reference_price": reference_price,
            "current_shares": current["shares"],
            "current_notional": current["notional"],
            "current_weight": current["weight"],
            "delta_shares": delta_shares,
            "delta_notional": delta_notional,
            "delta_weight": delta_weight,
            "trade_label": trade_label,
            "trade_class": trade_class,
        })
    return out


def _current_position_for_leg(
    payload: Dict[str, Any],
    sleeve_symbol: str,
    leg_symbol: str,
    role: str,
    target_weight: float,
) -> Dict[str, float]:
    ibkr = payload.get("ibkr") or {}
    row = _ibkr_row(ibkr, leg_symbol) or {}
    shares = _float(row.get("actual_shares"), 0.0)
    notional = _float(row.get("actual_notional"), 0.0)
    weight = _float(row.get("actual_weight"), 0.0)
    if role != "defense_route":
        return {"shares": shares, "notional": notional, "weight": weight}
    total = _route_target_total(payload, leg_symbol)
    if total <= 0:
        return {"shares": 0.0, "notional": 0.0, "weight": 0.0}
    share = max(0.0, target_weight) / total
    return {
        "shares": shares * share,
        "notional": notional * share,
        "weight": weight * share,
    }


def _route_target_total(payload: Dict[str, Any], leg_symbol: str) -> float:
    total = 0.0
    for intent in (payload.get("action_intents") or {}).values():
        for leg in ((intent.get("trade_plan") or {}).get("legs") or []):
            if str(leg.get("role") or "") == "defense_route" and str(leg.get("symbol") or "") == leg_symbol:
                total += _float(leg.get("target_weight"), 0.0)
    return total


def _trade_delta_label(delta_shares: float, delta_notional: float, delta_weight: float) -> tuple[str, str]:
    if abs(delta_weight) < 0.002 or abs(delta_notional) < 50:
        return "不用动", "trade-hold"
    if delta_shares > 0:
        return "买入", "trade-buy"
    return "卖出", "trade-sell"


def _plain_command(symbol: str, intent: Dict[str, Any], rows: List[Dict[str, Any]]) -> str:
    if not bool(intent.get("execution_ready")):
        target = "；".join(f"{row['symbol']} 目标 {_fmt_pct(row['target_weight'])}" for row in rows)
        return (
            f"策略目标：{target}。金额/股数仅为估算；"
            "等待新鲜 IBKR 对账后生成差额动作。"
        )
    active = [row for row in rows if row["trade_class"] != "trade-hold"]
    if not active:
        target = "；".join(
            f"{row['symbol']} {_fmt_pct(row['target_weight'])} / {_fmt_num(row['target_shares'])}股"
            for row in rows
        )
        return f"实际调仓：{symbol} 不需要交易；目标配置为 {target}。"
    parts = []
    for row in active:
        verb = "买入" if row["trade_class"] == "trade-buy" else "卖出"
        parts.append(
            f"{verb} {row['symbol']} 约 {_fmt_num(abs(row['delta_shares']))} 股"
            f"（{_fmt_money(abs(row['delta_notional']))}，占总资产 {_fmt_pct(abs(row['delta_weight']))}）"
        )
    target = "；".join(
        f"{row['symbol']} 目标 {_fmt_pct(row['target_weight'])} / {_fmt_num(row['target_shares'])}股"
        for row in rows
    )
    return f"实际调仓：{'；'.join(parts)}。执行后：{target}。"


def _intent_target_summary(intent: Dict[str, Any]) -> Dict[str, str]:
    defense_legs = [
        leg for leg in ((intent.get("trade_plan") or {}).get("legs") or [])
        if str(leg.get("role") or "") == "defense_route"
    ]
    if defense_legs:
        return {
            "target": " / ".join(
                f"{str(leg.get('symbol') or '-')} {_fmt_pct(leg.get('target_weight'))}"
                for leg in defense_legs
            ),
            "notional": _fmt_money(sum(_float(leg.get("target_notional"), 0.0) for leg in defense_legs)),
            "shares": " / ".join(
                f"{str(leg.get('symbol') or '-')} {_fmt_num(leg.get('target_shares'))}股"
                for leg in defense_legs
            ),
        }
    return {
        "target": str(intent.get("target_symbol", "-")),
        "notional": _fmt_money(intent.get("target_notional")),
        "shares": _fmt_num(intent.get("target_shares")),
    }


def _render_macro_section(payload: Dict[str, Any]) -> str:
    score = _first_score(payload)
    factors = ((score.get("factor_scores") or {}).get("A") or []) if score else []
    module_score = _float((score.get("module_scores") or {}).get("A") if score else None, 0.0)
    max_score = sum(_float(row.get("max_score"), 0.0) for row in factors if _float(row.get("max_score"), 0.0) > 0)
    regime = payload.get("regime") or {}
    verdict = "BOXX 避险阈值已触发" if module_score >= 12 else "未触发 BOXX 宏观核爆阈值"
    verdict_kind = "danger" if module_score >= 12 else "ok"
    rows: List[str] = []
    for row in factors:
        max_points = _float(row.get("max_score"), 0.0)
        if max_points <= 0 and not row.get("missing_fields"):
            continue
        rows.append(
            "<tr>"
            f"<td><b>{esc(row.get('factor_id'))}</b></td>"
            f"<td>{_fmt_num(row.get('score'))} / {_fmt_num(row.get('max_score'))}</td>"
            f"<td>{_factor_explain_cell(row)}</td>"
            f"<td>{esc(', '.join(row.get('missing_fields') or [])) or '-'}</td>"
            "</tr>"
        )
    key_cards = []
    visible_factors = sorted(
        [row for row in factors if _float(row.get("max_score"), 0.0) > 0],
        key=lambda row: (_float(row.get("score"), 0.0), _float(row.get("max_score"), 0.0)),
        reverse=True,
    )[:4]
    for row in visible_factors:
        key_cards.append(
            "<div class='macro-factor'>"
            f"<b>{esc(_short_factor_id(row.get('factor_id')))}</b>"
            f"<div class='pts'>{_fmt_num(row.get('score'))} / {_fmt_num(row.get('max_score'))}</div>"
            f"<div class='subtle'>{esc(row.get('plain_explain') or row.get('explain'))}</div>"
            "</div>"
        )
    return f"""
    <section>
      <h2>宏观 A 模块评分</h2>
      <div class="macro-summary">
        <div class="macro-tile">
          <div class="label">A 模块总分</div>
          <div class="value">{_fmt_num(module_score)} / {_fmt_num(max_score)}</div>
        </div>
        <div class="macro-tile">
          <div class="label">避险阈值</div>
          <div class="value">{_badge(verdict, verdict_kind)}</div>
        </div>
        <div class="macro-tile">
          <div class="label">市场状态</div>
          <div class="value">{esc(regime.get('current', 'NA'))}</div>
          <div class="subtle">VIX pct {_fmt_num(regime.get('vix_percentile'))}</div>
        </div>
        <div class="macro-tile">
          <div class="label">QQQ 趋势</div>
          <div class="value">{_fmt_money((regime.get('inputs') or {}).get('QQQ.close'))}</div>
          <div class="subtle">MA200 {_fmt_money((regime.get('inputs') or {}).get('QQQ.ma200'))}</div>
        </div>
      </div>
      <div class="macro-factors">
        {''.join(key_cards) if key_cards else '<div class="macro-factor">暂无主要触发项</div>'}
      </div>
      <details class="macro-details">
        <summary>展开全部宏观 A 指标</summary>
        <div class="detail-body">
          <table>
            <thead><tr><th>宏观指标</th><th>得分</th><th>解释</th><th>缺失</th></tr></thead>
            <tbody>{''.join(rows) if rows else '<tr><td colspan="4">暂无 A 模块评分</td></tr>'}</tbody>
          </table>
        </div>
      </details>
    </section>
    """


def _render_component_flow_section(payload: Dict[str, Any]) -> str:
    flow = payload.get("flow") or {}
    symbol_rows = flow.get("symbols") or {}
    baskets = flow.get("component_baskets") or {}
    worst = _worst_flow_symbol(payload)
    weak = _top_flow_components(payload, limit=5, negative_only=False)
    weak_text = " / ".join(f"{esc(row.get('symbol'))} {esc(row.get('severity'))}" for row in weak) or "暂无"
    order_text = " > ".join(
        f"{state['symbol']} {state['severity']}"
        for state in sorted([_flow_state_for_symbol(payload, symbol) for symbol in TRADE_SYMBOLS], key=lambda row: _flow_rank(row["severity"]))
    )
    tables = []
    for symbol in TRADE_SYMBOLS:
        if symbol in baskets:
            basket = baskets.get(symbol) or {}
            components = basket.get("components") or []
            summary = (
                f"severity={esc(basket.get('severity', 'NA'))} · "
                f"avg CMF {_fmt_num(basket.get('avg_cmf20'))} · "
                f"avg MFI {_fmt_num(basket.get('avg_mfi14'))} · "
                f"abnormal {esc(basket.get('abnormal_components', 0))}/{esc(basket.get('component_count', 0))}"
            )
        else:
            components = [symbol_rows.get(symbol, {"symbol": symbol, "severity": "MISSING"})]
            row = components[0]
            summary = (
                f"severity={esc(row.get('severity', 'NA'))} · "
                f"CMF {_fmt_num(row.get('cmf20'))} · "
                f"MFI {_fmt_num(row.get('mfi14'))}"
            )
        tables.append(_render_flow_card(symbol, components, summary, symbol_rows.get(symbol) or {}))
    return f"""
    <section>
      <div class="flow-header">
        <div>
          <h2 style="margin-bottom:4px">穿透股票成交与流向参考 / Underlying Turnover</h2>
          <div class="subtle">量价流向热力：最危险桶 {esc(worst['symbol'] + ' / ' + worst['severity']) if worst else '暂无'} · 风险排序 {esc(order_text)} · 主要底层票 {weak_text}</div>
          <div class="subtle">CMF20 / MFI-50 / 弱量价天数 / 5日方向成交额代理只表示量价趋势，不是真实资金净流。coral=偏弱，teal=偏强。db={esc(flow.get('db_path', '未固化'))}</div>
        </div>
        {_badge('flow as_of ' + esc(flow.get('as_of', 'NA')), 'watch')}
      </div>
      <div class="flow-grid">{''.join(tables)}</div>
      {_render_alpaca_daily_flow(payload)}
    </section>
    """


def _render_alpaca_daily_flow(payload: Dict[str, Any]) -> str:
    flow = payload.get("alpaca_daily_flow") or {}
    baskets = flow.get("baskets") or {}
    if not baskets:
        return """
        <div class="tape-flow-block">
          <h3>上一交易日成交额拆分估算 / SIP Turnover Estimate</h3>
          <div class="warning-box">尚无 Alpaca SIP 日成交缓存；旧的 CMF/MFI 趋势参考仍可用。</div>
        </div>
        """

    cards = []
    for symbol in TRADE_SYMBOLS:
        basket = baskets.get(symbol) or {}
        components = sorted(
            basket.get("components") or [],
            key=lambda row: abs(_float(row.get("net_notional"), 0.0)),
            reverse=True,
        )
        rows = []
        for row in components:
            buy_share = min(1.0, max(0.0, _float(row.get("buy_share"), 0.5)))
            net = _float(row.get("net_notional"), 0.0)
            net_class = "tape-net-buy" if net > 0 else "tape-net-sell" if net < 0 else "tape-net-flat"
            rows.append(
                "<tr>"
                f"<td><b>{esc(row.get('symbol'))}</b></td>"
                f"<td>{_fmt_flow_gross(row.get('buy_notional'))}</td>"
                f"<td>{_fmt_flow_gross(row.get('sell_notional'))}</td>"
                f"<td class='{net_class}'>{_fmt_flow_money(row.get('net_notional'))}</td>"
                "<td>"
                f"{buy_share * 100:.1f}%"
                "<div class='tape-split' aria-label='主动买卖估算占比'>"
                f"<span class='buy' style='width:{buy_share * 100:.1f}%'></span>"
                f"<span class='sell' style='width:{(1.0 - buy_share) * 100:.1f}%'></span>"
                "</div></td>"
                f"<td>{int(_float(row.get('trade_count'), 0.0)):,}</td>"
                "</tr>"
            )
        basket_net = _float(basket.get("net_notional"), 0.0)
        basket_class = "tape-net-buy" if basket_net > 0 else "tape-net-sell" if basket_net < 0 else "tape-net-flat"
        direction = {
            "NET_BUY": "估算买入侧占优",
            "NET_SELL": "估算卖出侧占优",
            "BALANCED": "买卖接近平衡",
            "MISSING": "数据缺失",
        }.get(str(basket.get("direction")), str(basket.get("direction") or "NA"))
        rows_html = "".join(rows) if rows else '<tr><td colspan="6">暂无成交数据</td></tr>'
        cards.append(
            "<div class='tape-flow-card'>"
            "<div class='head'>"
            f"<h3>{esc(symbol)} · {esc(direction)}</h3>"
            f"<div class='{basket_class}'>估算差额 {_fmt_flow_money(basket.get('net_notional'))}</div>"
            f"<div class='subtle'>总成交额 {_fmt_flow_gross(basket.get('total_notional'))} · "
            f"覆盖 {esc(basket.get('component_count', 0))}/{esc(basket.get('requested_component_count', 0))} 只</div>"
            "</div>"
            "<div class='body'><table>"
            "<thead><tr><th>股票</th><th>买入侧估算</th><th>卖出侧估算</th><th>估算差额</th><th>买入侧占比</th><th>成交笔</th></tr></thead>"
            f"<tbody>{rows_html}</tbody>"
            "</table></div></div>"
        )
    source_day = str(flow.get("as_of") or "NA")
    source = str(flow.get("source") or "ALPACA_SIP_1MIN")
    source_kind = "ok" if source_day == str(payload.get("as_of") or "")[:10] else "warn"
    return f"""
    <div class="tape-flow-block">
      <div class="flow-header">
        <div>
          <h3 style="margin-bottom:4px">上一交易日成交额拆分估算 / SIP Turnover Estimate</h3>
          <div class="subtle">SIP 1 分钟 VWAP × 成交量只能确认真实总成交额；买卖侧拆分由分钟价格位置估算，不是交易所 aggressor side，也不是真实资金净流。</div>
          <div class="subtle">teal=买入侧估算 · coral=卖出侧估算 · 按估算差额绝对值排序</div>
        </div>
        {_badge(source + ' · ' + source_day, source_kind)}
      </div>
      <div class="tape-flow-grid">{''.join(cards)}</div>
    </div>
    """


def _render_flow_card(symbol: str, components: List[Dict[str, Any]], summary: str, fund_flow: Dict[str, Any]) -> str:
    severity_rank = {"SEVERE": 0, "ABNORMAL": 1, "WATCH": 2, "NORMAL": 3, "MISSING": 4}
    rows = []
    sorted_rows = sorted(
        components,
        key=lambda item: (
            severity_rank.get(str(item.get("severity", "MISSING")), 5),
            -_float(item.get("outflow_days_5d"), 0.0),
            _float(item.get("cmf20"), 0.0),
            _float(item.get("legacy_signed_5d"), 0.0),
            str(item.get("symbol", "")),
        ),
    )[:12]
    for row in sorted_rows:
        sev = str(row.get("severity", "MISSING"))
        signed = _float(row.get("legacy_signed_5d"), 0.0)
        money_class = "pos" if signed >= 0 else "neg"
        rows.append(
            "<tr>"
            f"<td><b>{esc(row.get('symbol'))}</b></td>"
            f"<td>{esc(row.get('outflow_days_5d', 'NA'))}</td>"
            f"{_flow_heat_cell(row.get('cmf20'), -0.25, 0.25)}"
            f"{_flow_heat_cell((_float(row.get('mfi14'), 50.0) - 50.0) if row.get('mfi14') is not None else None, -25, 25, digits=0)}"
            f"<td class='flow-money {money_class}'>{_fmt_flow_money(row.get('legacy_signed_5d'))}</td>"
            f"<td>{_badge(sev, _flow_kind(sev))}</td>"
            "</tr>"
        )
    divergence = _flow_divergence(symbol, sorted_rows, fund_flow)
    return f"""
    <div class="flow-card">
      <div class="flow-title">
        <h3 style="margin-bottom:4px">{esc(symbol)} 量价流向代理</h3>
        <div class="subtle">{summary}</div>
      </div>
      <div class="flow-body">
        <table>
          <thead><tr><th>股票</th><th>弱量价天</th><th>CMF20热格</th><th>MFI-50热格</th><th>5日方向成交额代理</th><th>判定</th></tr></thead>
          <tbody>{''.join(rows) if rows else '<tr><td colspan="6">暂无量价流向数据</td></tr>'}</tbody>
        </table>
        {divergence}
      </div>
    </div>
    """


def _render_symbol_card(symbol: str, payload: Dict[str, Any]) -> str:
    score = (payload.get("scores") or {}).get(symbol, {})
    sizing = (payload.get("sizing") or {}).get(symbol, {})
    routing = (payload.get("routing") or {}).get(symbol, {})
    intent = (payload.get("action_intents") or {}).get(symbol, {})
    layers = (payload.get("decision_layers") or {}).get(symbol, {})
    reentry = (payload.get("reentry") or {}).get(symbol, {})
    reentry_state_payload = payload.get("reentry_state") or {}
    reentry_state = (reentry_state_payload.get("states") or {}).get(symbol, {})
    execution_confirmation = (reentry_state_payload.get("execution_confirmations") or {}).get(symbol, {})
    pnl = (payload.get("posterior_pnl") or {}).get("escape", {}).get(symbol, {})
    ibkr_row = _ibkr_row(payload.get("ibkr") or {}, symbol)
    status = str(score.get("status", "NA"))
    hard = score.get("hard_valve_hits") or []
    module_scores = score.get("module_scores") or {}
    sell_fraction = score.get("sell_fraction")
    close = _snap(payload, symbol, "close")
    ma200 = _snap(payload, symbol, "ma200")
    ma220 = _snap(payload, symbol, "ma220")
    ema20 = _snap(payload, symbol, "ema20")
    chandelier = _snap(payload, symbol, "chandelier_exit")
    dist = _snap(payload, symbol, "distribution_days_25d")
    drawdown = _snap(payload, symbol, "drawdown_60d_high_pct")
    radar_symbol = "QQQ" if symbol in {"FNGU", "SOXL"} else symbol
    if symbol == "SOXL":
        radar_symbol = "SOXX"
    radar_close = _snap(payload, radar_symbol, "close")
    radar_ma200 = _snap(payload, radar_symbol, "ma200")
    top_reasons = _top_factor_rows(score, limit=5)
    target_summary = _intent_target_summary(intent)

    return f"""
      <article class="symbol-card">
        <div class="symbol-head">
          <div>
            <div class="symbol-title">
              <strong>{esc(symbol)}</strong>
              {_badge(status, _status_kind(status))}
              {_badge('Hard ' + str(len(hard)), 'danger' if hard else 'ok')}
            </div>
            <div class="subtle">sell {_fmt_pct(sell_fraction)} · target {_fmt_pct(sizing.get('target_weight'))} · route {esc(_route_label(routing))}</div>
          </div>
          <div class="score">{_fmt_num(score.get('final_score'))}<small>final score</small></div>
        </div>
        <div class="symbol-body">
          <div class="module-row">
            {''.join(_module_box(m, module_scores.get(m, 0.0)) for m in ['A','B','C','D'])}
          </div>

          <div class="warning-box" style="background:#f8fafc;border-color:#cbd5e1;color:#0f172a">
            <b>唯一处置指令：</b>{esc(_action_cn(intent.get('action')))}
            · 目标 {esc(target_summary['target'])}
            · {'金额' if intent.get('amount_authoritative') else '估算金额'} {esc(target_summary['notional'])}
            · {'股数' if intent.get('amount_authoritative') else '估算股数'} {esc(target_summary['shares'])}
            · 策略置信 {esc(intent.get('strategy_confidence_level', intent.get('confidence_level', 'NA')))} {_fmt_num(intent.get('strategy_confidence_score', intent.get('confidence_score')))}
            · 金额置信 {esc(intent.get('execution_amount_confidence_level', 'NA'))} {_fmt_num(intent.get('execution_amount_confidence_score'))}
          </div>

          <div class="facts">
            {_metric('建议处置', f"{status} / 卖出 {_fmt_pct(sell_fraction)}")}
            {_metric('风险温度', f"{_fmt_num(((layers.get('risk_temperature') or {}).get('score')))} · {esc(((layers.get('risk_temperature') or {}).get('status', 'NA')))}")}
            {_metric('硬阀门', f"{esc((layers.get('hard_valve_state') or {}).get('count', 0))} 个 · {esc(', '.join((layers.get('hard_valve_state') or {}).get('ids', []) or [])) or '未触发'}")}
            {_metric('策略置信度', f"{esc((layers.get('strategy_confidence') or layers.get('action_confidence') or {}).get('level', 'NA'))} · {_fmt_num((layers.get('strategy_confidence') or layers.get('action_confidence') or {}).get('score'))}")}
            {_metric('金额置信度', f"{esc((layers.get('execution_amount_confidence') or {}).get('level', 'NA'))} · {_fmt_num((layers.get('execution_amount_confidence') or {}).get('score'))}")}
            {_metric('实质缺项扣分', _confidence_missing_text(layers, 'scored'))}
            {_metric('占位缺项', _confidence_missing_text(layers, 'non_scoring'))}
            {_metric('理想仓位', f"{_fmt_pct(sizing.get('target_weight'))} · {_fmt_money(pnl.get('notional'))}")}
            {_metric('建议股数', f"{_fmt_num(pnl.get('shares'))} 股 @ {_fmt_money(pnl.get('current_close'))}")}
            {_metric('资金路由', _route_text(routing))}
            {_metric('优化器', f"{esc(sizing.get('binding_constraint', 'NA'))} · conf {_fmt_pct(sizing.get('optimizer_confidence'))}")}
            {_metric('IBKR 当前', _ibkr_text(ibkr_row))}
          </div>

          <div class="mini-grid">
            <div>
              <h3>斩仓线 / 风险线</h3>
              <table>
                <tbody>
                  {_tr('当前收盘', _fmt_money(close), '标的自身')}
                  {_tr('EMA20', _fmt_money(ema20), '短线风险位')}
                  {_tr('MA200', _fmt_money(ma200), '核心硬阀门')}
                  {_tr('MA220', _fmt_money(ma220), '建仓审计参考')}
                  {_tr('Chandelier', _fmt_money(chandelier), 'ATR 吊灯止损')}
                  {_tr('25日派发', _fmt_num(dist), 'distribution days')}
                </tbody>
              </table>
            </div>
            <div>
              <h3>建仓审计 / 雷达</h3>
              <table>
                <tbody>
                  {_tr('雷达标的', esc(radar_symbol), '主控趋势')}
                  {_tr('雷达收盘', _fmt_money(radar_close), '')}
                  {_tr('雷达 MA200', _fmt_money(radar_ma200), '趋势红线')}
                  {_tr('60日回撤', _fmt_pct(drawdown), '高空回撤')}
                  {_tr('再建仓', esc(reentry.get('tranche', 'NA')), esc('; '.join(reentry.get('explain', [])[:2])))}
                  {_tr('解锁状态', esc(reentry.get('eligible', False)), esc(reentry.get('locked_reason', '')))}
                  {_tr('T1/T2状态', f"T1={esc(reentry_state.get('t1_active', False))} / T2={esc(reentry_state.get('t2_active', False))}", esc(reentry_state.get('updated_at', '')))}
                  {_tr('成交确认', esc(execution_confirmation.get('tranche', '未确认')), esc(execution_confirmation.get('confirmed_at', '等待 IBKR executions 接入')))}
                  {_tr('确认入口', 'POST /api/confirm_execution', '字段: symbol / tranche / status / source；仅记录确认，不下单')}
                  {_tr('状态库', esc(Path(str(reentry_state_payload.get('db_path', ''))).name if reentry_state_payload.get('db_path') else 'NA'), '持久化建仓状态')}
                </tbody>
              </table>
            </div>
          </div>

          <details>
            <summary>裁决原因和关键触发项</summary>
            <div class="detail-body">
              {_hard_valves(hard)}
              <div class="warning-box" style="margin:8px 0;background:#eff6ff;border-color:#bfdbfe;color:#1e3a8a">
                <b>通俗解释：</b>{esc('; '.join(intent.get('top_reasons') or []) or '暂无强触发项。')}
                <br><b>失效条件：</b>{esc(intent.get('invalidation', 'NA'))}
              </div>
              <table>
                <thead><tr><th>模块</th><th>指标</th><th>得分</th><th>解释</th></tr></thead>
                <tbody>{''.join(top_reasons) or '<tr><td colspan="4">暂无高分触发项</td></tr>'}</tbody>
              </table>
            </div>
          </details>
        </div>
      </article>
    """


def _render_ibkr_section(ibkr: Dict[str, Any], history: List[Dict[str, Any]]) -> str:
    age = _fmt_age(ibkr.get("snapshot_age_seconds"))
    stale_badge = _badge(
        "STALE" if ibkr.get("snapshot_stale") else "FRESH",
        "danger" if ibkr.get("snapshot_stale") else "ok",
    )
    rows: List[str] = []
    for label, items in [
        ("策略标的", ibkr.get("trade_symbols", [])),
        ("路由腿", ibkr.get("route_legs", [])),
        ("额外持仓", ibkr.get("extra_positions", [])),
    ]:
        for item in items or []:
            rows.append(
                "<tr>"
                f"<td>{esc(label)}</td>"
                f"<td><b>{esc(item.get('symbol'))}</b></td>"
                f"<td>{_fmt_pct(item.get('ideal_weight'))}</td>"
                f"<td>{_fmt_pct(item.get('actual_weight'))}</td>"
                f"<td>{_fmt_pct(item.get('delta_weight'), signed=True)}</td>"
                f"<td>{_fmt_money(item.get('actual_notional'))}</td>"
                f"<td>{_fmt_num(item.get('actual_shares'))}</td>"
                f"<td>{_fmt_money(item.get('avg_cost'))}</td>"
                f"<td>{_badge(str(item.get('status', 'NA')), _ibkr_status_kind(str(item.get('status', 'NA'))))}</td>"
                "</tr>"
            )
    if not rows:
        note = ibkr.get("note") or ibkr.get("error") or "暂无 IBKR 对账数据"
        rows.append(f'<tr><td colspan="9">{esc(note)}</td></tr>')
    history_table = _render_ibkr_history_details(history)
    return f"""
    <section>
      <div class="ibkr-head">
        <div>
          <h2>IBKR Reconciliation / 持仓对账</h2>
          <div class="subtle">source={esc(ibkr.get('source', 'disabled'))} · clientId={esc(ibkr.get('client_id', 'NA'))} · account={esc(ibkr.get('account_id', 'NA'))} · sync={esc(str(ibkr.get('sync_time', ''))[:19])} · age={esc(age)} {stale_badge}</div>
        </div>
        <div class="ibkr-total-box">
          <div class="label">IBKR 现有总资产 / NetLiq</div>
          <div class="amount">{_fmt_money(ibkr.get('net_liq'))}</div>
          <div class="note">source={esc(ibkr.get('source', 'disabled'))} · clientId={esc(ibkr.get('client_id', 'NA'))} · age={esc(age)} · max delta {_fmt_pct(ibkr.get('max_abs_delta'))}</div>
        </div>
      </div>
      {_warning(ibkr.get('error'))}
      <table>
        <thead><tr><th>类别</th><th>标的</th><th>理想</th><th>实际</th><th>差异</th><th>市值</th><th>股数</th><th>成本</th><th>状态</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
      {history_table}
    </section>
    """


def _render_ibkr_history_details(history: List[Dict[str, Any]]) -> str:
    history_rows = []
    for row in history[:5]:
        history_rows.append(
            "<tr>"
            f"<td>{esc(row.get('id'))}</td>"
            f"<td>{esc(row.get('source', 'NA'))}</td>"
            f"<td>{esc(str(row.get('sync_time', ''))[:19])}</td>"
            f"<td>{_fmt_money(row.get('net_liq'))}</td>"
            f"<td>{'是' if row.get('snapshot_stale') else '否'}</td>"
            f"<td>{esc(row.get('client_id', 'NA'))}</td>"
            "</tr>"
        )
    return f"""
      <details style="margin-top:10px">
        <summary>最近 IBKR 快照 / snapshot history</summary>
        <div class="detail-body">
          <table>
            <thead><tr><th>ID</th><th>来源</th><th>同步时间</th><th>NetLiq</th><th>Stale</th><th>clientId</th></tr></thead>
            <tbody>{''.join(history_rows) if history_rows else '<tr><td colspan="6">暂无历史快照</td></tr>'}</tbody>
          </table>
        </div>
      </details>
    """


def _render_posterior_section(payload: Dict[str, Any], *, collapsed: bool = False) -> str:
    posterior = payload.get("posterior_pnl") or {}
    history = payload.get("calibration_history") or []
    state = payload.get("state") or {}
    rows = []
    for group, by_key in [("Escape", posterior.get("escape", {})), ("Mirror", posterior.get("mirror", {}))]:
        for key, row in sorted((by_key or {}).items()):
            rows.append(
                "<tr>"
                f"<td>{esc(group)}</td><td>{esc(key)}</td><td><b>{esc(row.get('symbol'))}</b></td>"
                f"<td>{_fmt_pct(row.get('target_weight'))}</td><td>{_fmt_money(row.get('notional'))}</td>"
                f"<td>{_fmt_num(row.get('shares'))}</td><td>{_fmt_money(row.get('pnl'))}</td><td>{_fmt_pct(row.get('return_pct'))}</td>"
                "</tr>"
            )
    history_rows = []
    for row in history[:12]:
        history_rows.append(
            "<tr>"
            f"<td>{esc(row.get('as_of'))}</td><td>{esc(row.get('system'))}</td>"
            f"<td>{esc(row.get('sleeve'))}</td><td><b>{esc(row.get('symbol'))}</b></td>"
            f"<td>{_fmt_money(row.get('notional'))}</td><td>{_fmt_money(row.get('pnl'))}</td>"
            f"<td>{_fmt_pct(row.get('return_pct'))}</td>"
            "</tr>"
        )
    body = f"""
      <div class="subtle">payload as_of={esc(payload.get('as_of', 'NA'))} · run={esc(state.get('score_run_id', 'NA'))} · input_hash={esc(str(payload.get('input_hash', 'NA'))[:12])} · portfolio value={_fmt_money(posterior.get('portfolio_value'))}</div>
      <table>
        <thead><tr><th>系统</th><th>仓位桶</th><th>标的</th><th>权重</th><th>金额</th><th>股数</th><th>浮盈亏</th><th>收益</th></tr></thead>
        <tbody>{''.join(rows) if rows else '<tr><td colspan="8">暂无后验盈亏数据</td></tr>'}</tbody>
      </table>
      <details style="margin-top:10px">
        <summary>最近模型校准记录 / calibration history</summary>
        <div class="detail-body">
          <table>
            <thead><tr><th>日期</th><th>系统</th><th>桶</th><th>标的</th><th>金额</th><th>上一交易日盈亏</th><th>收益</th></tr></thead>
            <tbody>{''.join(history_rows) if history_rows else '<tr><td colspan="7">暂无历史校准记录</td></tr>'}</tbody>
          </table>
        </div>
      </details>
    """
    if collapsed:
        return f"""
        <details style="margin-top:10px">
          <summary>理想仓位上一交易日盈亏 / Posterior Ideal P/L</summary>
          <div class="detail-body">{body}</div>
        </details>
        """
    return f"""
    <section>
      <h2>Posterior Ideal P/L / 理想仓位上一交易日盈亏</h2>
      {body}
    </section>
    """


def _render_mirror_section(payload: Dict[str, Any]) -> str:
    rows = []
    for sleeve, decision in sorted(((payload.get("mirror") or {}).get("decisions") or {}).items()):
        rows.append(
            "<tr>"
            f"<td><b>{esc(sleeve)}</b></td><td>{esc(decision.get('cycle'))}</td>"
            f"<td>{esc(decision.get('selected_symbol'))}</td><td>{_fmt_pct(decision.get('target_weight'))}</td>"
            f"<td>{esc(decision.get('reason'))}</td>"
            "</tr>"
        )
    return f"""
    <section>
      <h2>Mirror Reference / 镜像参考</h2>
      <table>
        <thead><tr><th>仓位桶</th><th>周期</th><th>选择</th><th>目标</th><th>原因</th></tr></thead>
        <tbody>{''.join(rows) if rows else '<tr><td colspan="5">暂无镜像数据</td></tr>'}</tbody>
      </table>
    </section>
    """


def _render_health_banner(health: Dict[str, Any]) -> str:
    """Top-of-page run-health banner. Loud red/amber when the daily run degraded
    (stale data, dead source, IBKR down, manifest drift, no cache); slim green
    when healthy so 'no alarm' is trustworthy. Layout-additive."""
    if not health:
        return ""
    level = str(health.get("level") or "OK")
    checks = health.get("checks") or []
    if level == "OK":
        return (
            '<section class="panel" style="border-left:4px solid var(--green);'
            'background:#ecfdf5;padding:8px 14px;margin-bottom:10px">'
            '<span style="font-weight:600;color:var(--green)">✓ 运行健康</span>'
            '<span class="subtle" style="margin-left:8px">行情新鲜 · 数据清单一致 · 数据质量达标</span>'
            '</section>'
        )
    crit = level == "CRITICAL"
    color = "var(--red)" if crit else "var(--amber)"
    bg = "#fef2f2" if crit else "#fffbeb"
    title = "🚨 运行严重降级 / CRITICAL" if crit else "⚠️ 运行降级 / DEGRADED"
    actionable_checks = [c for c in checks if c.get("level") in {"CRITICAL", "DEGRADED"}]
    refs = [_runbook_key_for_check(c) for c in actionable_checks]
    items = "".join(
        f'<li><b style="color:{"var(--red)" if c.get("level")=="CRITICAL" else "var(--amber)"}">'
        f'{esc(c.get("label"))}</b>{(" — " + esc(c.get("detail"))) if c.get("detail") else ""} '
        f'<a href="#{RUNBOOK_REFS[_runbook_key_for_check(c)][0]}">处理清单</a></li>'
        for c in actionable_checks
    )
    return (
        f'<section class="panel" style="border:2px solid {color};background:{bg};'
        f'padding:12px 16px;margin-bottom:12px">'
        f'<div style="font-weight:700;color:{color};font-size:15px">{title}</div>'
        f'<div class="subtle" style="margin:4px 0 6px">今日日报基于降级的数据/连接，请先处理以下问题再据此决策：</div>'
        f'<ul style="margin:0;padding-left:20px">{items}</ul>'
        f'{_render_runbook_refs(refs)}'
        f'</section>'
    )


def _render_preview_banner(payload: Dict[str, Any]) -> str:
    """Loud banner when the shown record is NOT the official scheduled run. An
    intraday manual_rerun / shadow preview must never be mistaken for today's
    official advice (the SOXL REDUCE->EXIT->REDUCE scare was a preview flip).
    Layout-additive: returns '' for the normal scheduled case."""
    rt = str(payload.get("run_type", "scheduled"))
    if rt == "scheduled":
        return ""
    label = {"manual_rerun": "盘中重算预览", "shadow": "影子运行"}.get(rt, rt)
    as_of = esc(str(payload.get("as_of", "")))
    return (
        '<section class="panel" style="border:2px solid var(--red);background:#fef2f2;'
        'padding:12px 16px;margin-bottom:12px">'
        f'<div style="font-weight:700;color:var(--red);font-size:15px">⚠️ 非官方 · 你在看「{label}」</div>'
        f'<div class="subtle" style="margin:4px 0 0">当前展示的是 {as_of} 的{label}，<b>不是今日官方建议</b>。'
        '官方建议来自每日 07:10 的 scheduled 运行 — '
        '<a href="/?as_of=latest">点此回到官方</a>。</div>'
        '</section>'
    )


def _run_receipt_when(run_at: str) -> str:
    """Human '今天 HH:MM' / '昨天 HH:MM' / 'N 天前' for a run-receipt timestamp."""
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(run_at)
        days = (date.today() - dt.date()).days
        hm = dt.strftime("%H:%M")
        if days <= 0:
            return f"今天 {hm}"
        if days == 1:
            return f"昨天 {hm}"
        return f"{days} 天前 ({dt.date().isoformat()} {hm})"
    except Exception:
        return (run_at or "?")[:16]


def _render_run_receipt_banner(payload: Dict[str, Any]) -> str:
    """Top banner from the daily run's end-of-run receipt: WHEN the official run
    last completed + its self-check. Green when it ran today and self-checked OK;
    loud red when the run is stale (didn't complete today) or a check failed — the
    one signal that catches 'the job silently didn't run / ran stale code' even
    when the data still looks fresh. Amber when no receipt exists yet."""
    from datetime import datetime
    receipt = payload.get("run_receipt") or {}
    if not receipt:
        return (
            '<section class="panel" style="border-left:4px solid var(--amber);background:#fffbeb;'
            'padding:8px 14px;margin-bottom:10px">'
            '<span style="font-weight:600;color:var(--amber)">⚠️ 无运行回执</span>'
            '<span class="subtle" style="margin-left:8px">无法确认每日官方 run 今天是否跑过（旧引擎或尚未生成）</span>'
            '</section>'
        )
    run_at = str(receipt.get("run_at", ""))
    when = _run_receipt_when(run_at)
    status = str(receipt.get("status") or ("OK" if receipt.get("ok") else "FAILED"))
    if status == "RUNNING":
        return (
            '<section class="panel" style="border-left:4px solid var(--amber);background:#fffbeb;'
            'padding:8px 14px;margin-bottom:10px">'
            '<span style="font-weight:600;color:var(--amber)">官方 run 正在执行</span>'
            f'<span class="subtle" style="margin-left:8px">started={esc(when)} · as_of={esc(str(receipt.get("as_of", "")))}</span>'
            '</section>'
        )
    try:
        age_h = (datetime.now().astimezone() - datetime.fromisoformat(run_at)).total_seconds() / 3600
    except Exception:
        age_h = 1e9
    # The daily fires every calendar day ~07:10, so a healthy receipt peaks at
    # ~24h between runs; >30h means a cycle was missed (job didn't fire). Using
    # an age threshold — not "ran today" — avoids a false red every morning
    # before the 07:10 run completes.
    stale = age_h > 26
    fails = [c for c in (receipt.get("checks") or []) if not c.get("ok")]
    if status == "OK" and receipt.get("ok") and not stale and not fails:
        return (
            '<section class="panel" style="border-left:4px solid var(--green);background:#ecfdf5;'
            'padding:8px 14px;margin-bottom:10px">'
            f'<span style="font-weight:600;color:var(--green)">✓ 官方 run {esc(when)}</span>'
            f'<span class="subtle" style="margin-left:8px">as_of={esc(str(receipt.get("as_of", "")))} · 自检全绿</span>'
            '</section>'
        )
    reasons = []
    if stale:
        reasons.append(f"<b>官方 run 已停摆</b>（上次 {esc(when)}）")
    if status == "FAILED":
        reasons.append(
            f"step={esc(str(receipt.get('failed_step') or 'unknown'))}: "
            f"{esc(str(receipt.get('error') or 'run failed'))}"
        )
    for c in fails:
        reasons.append(f"{esc(str(c.get('name')))}: {esc(str(c.get('detail')))}")
    body = " · ".join(reasons) or "自检未通过"
    return (
        '<section class="panel" style="border:2px solid var(--red);background:#fef2f2;'
        'padding:12px 16px;margin-bottom:12px">'
        '<div style="font-weight:700;color:var(--red);font-size:15px">🚨 每日 run 回执异常</div>'
        f'<div class="subtle" style="margin:4px 0 0">{body}</div>'
        '</section>'
    )


def _runbook_key_for_check(check: Dict[str, Any]) -> str:
    text = f"{check.get('label', '')} {check.get('detail', '')}"
    if "IBKR" in text:
        return "ibkr"
    if "PENDING" in text or "阀门" in text or "suspect" in text.lower():
        return "pending"
    if "gate" in text.lower() or "回测" in text:
        return "gate"
    if "flag" in text.lower() or "翻闸" in text:
        return "flag"
    if "launchd" in text.lower() or "watchdog" in text.lower():
        return "launchd"
    if "部署" in text or "deploy" in text.lower():
        return "deploy"
    if any(token in text for token in ["缓存", "行情", "数据", "清单", "STALE", "源"]):
        return "data"
    return "normal"


def _render_runbook_refs(keys: Iterable[str]) -> str:
    unique = []
    for key in keys:
        if key not in RUNBOOK_REFS or key in unique:
            continue
        unique.append(key)
    if not unique:
        return ""
    rows = []
    for key in unique:
        anchor, title, summary = RUNBOOK_REFS[key]
        rows.append(f"<div id='{anchor}'><b>Runbook: {esc(title)}</b> — {esc(summary)}</div>")
    return f"<div class='runbook-mini'>{''.join(rows)}</div>"


def _render_cache_hint(cache: Dict[str, Any]) -> str:
    """Friendly empty-state banner shown only when no cached score payload exists.

    A fresh checkout has no audit_log yet, so the dashboard would otherwise look
    blank/NO_CACHE with no guidance. Layout-additive: nothing renders on cache hit.
    """
    if cache.get("hit"):
        return ""
    msg = esc(cache.get("message") or "尚无评分缓存。")
    return f"""
    <section class="panel" style="border-left:4px solid var(--amber);background:#fffbeb">
      <div style="font-weight:600;color:var(--amber)">尚无评分缓存 / no cached score yet</div>
      <div class="subtle" style="margin-top:4px">{msg} 点击右上角「更新策略数据」拉取行情并评分，或在终端运行
        <code>python3 -m hermes_escape_top.scripts.run_daily_package --as-of latest</code> 生成首个缓存。</div>
    </section>
    """


def _manifest_badge(manifest_status: Dict[str, Any]) -> str:
    status = str((manifest_status or {}).get("status") or "UNKNOWN")
    kind = {"OK": "ok", "DRIFT": "danger", "MISSING": "warn", "UNKNOWN": "watch"}.get(status, "watch")
    label = {"OK": "一致", "DRIFT": "漂移", "MISSING": "缺失", "UNKNOWN": "未知"}.get(status, status)
    return _badge("数据清单 " + label, kind)


def _render_data_trust_zone(payload: Dict[str, Any]) -> str:
    rows = _data_trust_rows(payload)
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td><b>{esc(row['display_name'])}</b></td>"
            f"<td>{esc(row['as_of'])}</td>"
            f"<td>{_trust_badge(row['truth_kind'])}</td>"
            f"<td>{esc(row['source'])}</td>"
            f"<td>{esc(row['cadence'])}</td>"
            f"<td>{_trust_slo_badge(row['slo_text'], row['slo_kind'])}</td>"
            "</tr>"
        )
    body_html = "".join(body) if body else '<tr><td colspan="6">暂无软数据源信任信息</td></tr>'
    return (
        "<details class='work-card data-trust-zone' style='margin:10px 0 0'>"
        "<summary>区域 5 · 数据信任区 <span class='subtle'>每源：最新 / 真实性 / SLO 倒计时</span></summary>"
        "<div class='detail-body'>"
        "<div class='table-scroll'>"
        "<table>"
        "<thead><tr><th>源</th><th>最新数据日</th><th>性质</th><th>来源</th><th>节奏</th><th>SLO</th></tr></thead>"
        f"<tbody>{body_html}</tbody>"
        "</table>"
        "</div>"
        f"{_render_external_source_controls(payload)}"
        "</div>"
        "</details>"
    )


def _render_external_source_controls(payload: Dict[str, Any]) -> str:
    external = payload.get("external_source_status") or {}
    if not isinstance(external, dict) or not external:
        return ""
    source_ids = list(EXTERNAL_SOURCE_ORDER)
    source_ids.extend(
        sorted(str(name) for name in external.keys() if str(name) not in EXTERNAL_SOURCE_ORDER)
    )
    naaim_retired = str(
        ((external.get("naaim_exposure") or {}).get("lifecycle_status"))
        if isinstance(external.get("naaim_exposure"), dict)
        else ""
    ) == "RETIRED_PAYWALL"
    rows = []
    for source_id in source_ids:
        row = external.get(source_id) if isinstance(external.get(source_id), dict) else {}
        status = _external_attempt_status(row or {})
        latest = (
            (row or {}).get("latest_promoted_as_of")
            or (row or {}).get("latest_normalized_as_of")
            or "—"
        )
        run_time = (
            (row or {}).get("latest_attempt_finished_at")
            or (row or {}).get("finished_at")
            or (row or {}).get("latest_finished_at")
            or (row or {}).get("started_at")
            or (row or {}).get("latest_started_at")
            or "—"
        )
        note = (
            (row or {}).get("latest_attempt_error_message")
            or (row or {}).get("latest_attempt_error_type")
            or (row or {}).get("error_message")
            or (row or {}).get("message")
            or (row or {}).get("error")
            or (row or {}).get("error_type")
            or ("尚无 ledger run" if status == "MISSING" else "")
        )
        freshness = str((row or {}).get("freshness_status") or "")
        age = (row or {}).get("age_days")
        next_action = str((row or {}).get("next_action") or "")
        freshness_note = ""
        if freshness:
            freshness_note = freshness
            if age is not None:
                freshness_note += f" · {age}d"
        official_note = ""
        if (row or {}).get("official_issue_as_of") or (row or {}).get("official_file_sha256"):
            official_note = (
                f"issue={str((row or {}).get('official_issue_as_of') or '—')[:10]} "
                f"sha={str((row or {}).get('official_file_sha256') or '—')[:8]}"
            )
        publisher_note = str((row or {}).get("publisher_note") or "")
        evidence = canonical_evidence_issue(row or {})
        evidence_note = ""
        if evidence:
            evidence_note = f"{evidence}: {(row or {}).get('evidence_detail') or 'canonical evidence not verified'}"
        note_parts = [part for part in (freshness_note, official_note, evidence_note, publisher_note, str(note or ""), next_action) if part]
        safe_id = _external_source_dom_id(source_id)
        retired = str((row or {}).get("lifecycle_status") or "") == "RETIRED_PAYWALL"
        action_html = (
            "<span class='subtle'>周五自动探测</span>"
            if retired
            else (
                f"<button class='btn-muted' style='padding:3px 9px;font-size:12px;min-height:26px' "
                f"onclick=\"refreshExternalSource('{safe_id}')\" id='external-source-{safe_id}-btn'>刷新</button>"
                f" <span class='subtle' id='external-source-{safe_id}-status'></span>"
            )
        )
        rows.append(
            "<tr>"
            f"<td><b>{esc(source_id)}</b><div class='subtle'>{esc(EXTERNAL_SOURCE_LABELS.get(source_id, 'External source'))}</div>"
            f"<div class='subtle'>{esc(external_reliability_text(row or {}))}</div></td>"
            f"<td>{_external_source_status_badge(evidence or status)} {_external_migration_badge((row or {}).get('migration_status'))}</td>"
            f"<td>{esc(str(latest)[:10])}</td>"
            f"<td><span class='subtle'>{esc(str(run_time))}</span></td>"
            f"<td>{esc(' · '.join(note_parts) if note_parts else '—')}</td>"
            f"<td>{action_html}</td>"
            "</tr>"
        )
    naaim_guidance = (
        "NAAIM 公共源已付费退役：认证历史冻结，仅周五自动探测官方访问是否恢复。"
        if naaim_retired
        else (
            "<code>PYTHONPATH=. python3 -m hermes_escape_top.scripts.refresh_external "
            "--source naaim_exposure --import-file ~/.hermes/external_imports/naaim.xlsx</code>。"
        )
    )
    import_guidance_label = "AAII" if naaim_retired else "AAII/NAAIM"
    return (
        "<div class='external-source-ops' style='margin-top:12px'>"
        "<div style='display:flex;justify-content:space-between;gap:10px;align-items:center;margin-bottom:6px'>"
        "<div><b>外部源运维</b> <span class='subtle'>ExternalSourceRunner：单源刷新、ledger 状态、最新入库日</span></div>"
        "<div style='display:flex;gap:8px;align-items:center'>"
        "<button class='btn-muted' style='padding:3px 9px;font-size:12px;min-height:26px' "
        "onclick='refreshExternalSources()' id='external-sources-refresh-all-btn'>刷新全部外部源</button>"
        "<span class='subtle' id='external-source-status'></span>"
        "</div>"
        "</div>"
        "<div class='table-scroll'>"
        "<table>"
        "<thead><tr><th>源</th><th>run</th><th>最新数据日</th><th>最近刷新</th><th>备注</th><th>操作</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</div>"
        f"{_render_external_import_candidates(payload)}"
        "<div class='subtle' style='margin-top:7px'>"
        "This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis. "
        f"{import_guidance_label} 自动抓取失败时，只接受官方下载文件导入："
        "<code>PYTHONPATH=. python3 -m hermes_escape_top.scripts.refresh_external --source aaii_sentiment --import-file ~/.hermes/external_imports/sentiment.xls</code>"
        "；"
        f"{naaim_guidance}"
        "镜像源仅用于核对，不直接替代生产真值。"
        "</div>"
        "</div>"
    )


def _render_external_import_candidates(payload: Dict[str, Any]) -> str:
    candidates = [row for row in (payload.get("external_import_candidates") or []) if isinstance(row, dict)]
    if not candidates:
        return ""
    rows = []
    for row in candidates:
        source_id = str(row.get("source_id") or "")
        path = str(row.get("path") or "")
        if not source_id or not path:
            continue
        safe_id = _external_source_dom_id(source_id)
        label = str(row.get("label") or EXTERNAL_SOURCE_LABELS.get(source_id, source_id))
        rows.append(
            "<tr>"
            f"<td><b>{esc(label)}</b><div class='subtle'>{esc(source_id)}</div></td>"
            f"<td>{esc(Path(path).name)}<div class='subtle'>{esc(path)}</div></td>"
            f"<td>{esc(str(row.get('mtime') or 'NA'))}</td>"
            f"<td>{esc(_fmt_file_size(row.get('size_bytes')))}</td>"
            "<td>"
            f"<button class='btn-muted' style='padding:3px 9px;font-size:12px;min-height:26px' "
            f"onclick='refreshExternalSourceImport({_js_literal(source_id)}, {_js_literal(path)})' "
            f"id='external-import-{safe_id}-btn'>导入此文件</button>"
            f" <span class='subtle' id='external-import-{safe_id}-status'></span>"
            "</td>"
            "</tr>"
        )
    if not rows:
        return ""
    return (
        "<div class='external-import-candidates' style='margin-top:10px'>"
        "<div><b>官方文件候选</b> <span class='subtle'>只列出已下载文件；点击后仍由 ExternalSourceRunner 校验期号、字段和日期。</span></div>"
        "<div class='table-scroll' style='margin-top:6px'>"
        "<table>"
        "<thead><tr><th>源</th><th>文件</th><th>mtime</th><th>大小</th><th>操作</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</div>"
        "</div>"
    )


def _fmt_file_size(value: Any) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return "NA"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{int(size)} B"


def _js_literal(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _external_source_dom_id(source_id: Any) -> str:
    text = str(source_id or "").strip()
    safe = "".join(ch for ch in text if ch.isalnum() or ch in {"_", "-"})
    return safe or "source"


def _external_attempt_status(row: Dict[str, Any], *, default: str = "MISSING") -> str:
    return str(row.get("latest_attempt_status") or row.get("status") or default)


def _external_attempt_error(row: Dict[str, Any]) -> str:
    return str(
        row.get("latest_attempt_error_message")
        or row.get("latest_attempt_error_type")
        or row.get("error_message")
        or row.get("error")
        or row.get("error_type")
        or ""
    )


def _external_source_status_badge(status: str) -> str:
    upper = str(status or "UNKNOWN").upper()
    if upper == "OK":
        kind = "ok"
    elif upper in {"MISSING", "UNKNOWN"}:
        kind = "watch"
    elif upper in {"ERROR", "FAILED", "FAIL", "EVIDENCE_DRIFT", "MISSING_CANONICAL"}:
        kind = "danger"
    else:
        kind = "warn"
    return _badge(upper, kind)


def _external_migration_badge(status: Any) -> str:
    value = str(status or "")
    if not value or value == "STABLE":
        return ""
    kind = "danger" if value == "ACTION_REQUIRED" else "warn" if value == "MIGRATION_DUE" else "watch"
    return _badge(value, kind)


def _data_trust_rows(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    explicit = payload.get("data_trust") or payload.get("data_trust_sources")
    if isinstance(explicit, list) and explicit:
        candidates = [dict(row) for row in explicit if isinstance(row, dict)]
    else:
        candidates = _data_trust_candidates_from_payload(payload)

    by_name: Dict[str, Dict[str, Any]] = {}
    for row in candidates:
        canonical = _trust_canonical_name(row.get("name") or row.get("source_name") or row.get("id"))
        if not canonical:
            continue
        merged = dict(by_name.get(canonical) or {})
        merged.update({k: v for k, v in row.items() if v is not None})
        merged["name"] = canonical
        by_name[canonical] = merged

    order = {name: idx for idx, name in enumerate(TRUST_SOURCE_ORDER)}
    rows = []
    for canonical, row in sorted(by_name.items(), key=lambda item: (order.get(item[0], 99), _trust_display_name(item[0]))):
        rows.append(_normalize_trust_row(canonical, row, payload))
    return rows


def _data_trust_candidates_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    records = (payload.get("soft_data") or {}).get("records") or {}
    for name, record in records.items():
        if isinstance(record, dict):
            row = dict(record)
            row.setdefault("name", name)
            candidates.append(row)

    for row in (payload.get("data_quality_breakdown") or {}).get("sources") or []:
        if not isinstance(row, dict) or row.get("category") not in {"soft", "flow"}:
            continue
        copied = dict(row)
        copied.setdefault("name", row.get("name"))
        candidates.append(copied)

    for name, row in (payload.get("external_source_status") or {}).items():
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "UNKNOWN")
        if status == "MISSING":
            continue
        latest = row.get("latest_promoted_as_of") or row.get("latest_normalized_as_of")
        candidates.append({
            "name": row.get("source_id") or name,
            "status": "AVAILABLE" if status == "OK" else status,
            "data_available": status == "OK",
            "is_proxy": False,
            "latest_data_date": latest,
            "as_of": latest,
            "source": f"ExternalSourceRunner · {status}",
            "reason": row.get("message") or row.get("error") or "",
        })
    return candidates


def _trust_latest_data_date(row: Dict[str, Any]) -> Any:
    """Actual latest data date for a soft source. The record's ``as_of`` is the
    RUN date, not the data date — showing it made a stale source (e.g. dollar,
    several trading days behind) look refreshed today. Prefer an explicit
    latest_data_date; else back out as_of minus the source's latency so the column
    reflects real staleness (the SLO badge stays the precise signal)."""
    explicit = row.get("latest_data_date") or row.get("latest")
    if explicit:
        return explicit
    base = row.get("as_of") or row.get("date")
    lat = row.get("latency_days")
    if base and isinstance(lat, (int, float)) and int(lat) > 0:
        try:
            from datetime import date as _date, timedelta as _timedelta
            return (_date.fromisoformat(str(base)[:10]) - _timedelta(days=int(lat))).isoformat()
        except Exception:
            return base
    return base


def _normalize_trust_row(canonical: str, row: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, str]:
    as_of = _trust_date_text(_trust_latest_data_date(row))
    truth = row.get("truth_kind") or row.get("nature")
    reason = str(row.get("reason") or "")
    if not truth:
        available = row.get("data_available", row.get("status") not in {"MISSING", "UNAVAILABLE"})
        if "feature disabled" in reason.lower():
            truth = "未启用"
        else:
            truth = "缺失" if available is False else ("代理" if row.get("is_proxy") else "真实")
    source = str(row.get("source") or row.get("provider") or "").strip()
    if "feature disabled" in reason.lower():
        source = reason
    profile = _trust_profile(canonical)
    cadence = str(row.get("cadence") or (profile.cadence if profile else "daily"))
    slo_text, slo_kind = _trust_slo_status(canonical, row, payload)
    if "feature disabled" in reason.lower():
        # A disabled candidate factor isn't scored, so its staleness is moot — show
        # OFF (neutral), never a red SLO breach (the C "假陈旧" false alarm).
        slo_text, slo_kind = "未启用 / OFF", "watch"
    return {
        "display_name": _trust_display_name(canonical),
        "as_of": as_of,
        "truth_kind": str(truth),
        "source": source or "—",
        "cadence": cadence,
        "slo_text": slo_text,
        "slo_kind": slo_kind,
    }


def _trust_canonical_name(name: Any) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    return TRUST_SOURCE_ALIASES.get(raw, raw)


def _trust_display_name(name: str) -> str:
    return TRUST_SOURCE_LABELS.get(name, name)


def _trust_profile(name: str):
    return profile_for(TRUST_SOURCE_LABELS.get(name, name))


def _trust_date_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    return text[:10]


def _trust_slo_status(canonical: str, row: Dict[str, Any], payload: Dict[str, Any]) -> tuple[str, str]:
    raw = row.get("slo") or row.get("slo_text")
    if raw:
        return str(raw), "watch"
    remaining = row.get("slo_remaining_days", row.get("remaining_days"))
    if remaining is None:
        max_age = _trust_max_age(canonical, row, payload)
        latency = _trust_latency_days(row, payload)
        if max_age is not None and latency is not None:
            remaining = max_age - latency
    if remaining is None:
        return "—", "watch"
    try:
        days = int(round(float(remaining)))
    except (TypeError, ValueError):
        return str(remaining), "watch"
    if days < 0:
        return f"超 {-days}d", "danger"
    if days <= 1:
        return f"剩 {days}d", "warn"
    return f"剩 {days}d", "ok"


def _trust_max_age(canonical: str, row: Dict[str, Any], payload: Dict[str, Any]) -> Optional[float]:
    explicit = row.get("max_age_days")
    if explicit is not None:
        return _float_or_none(explicit)
    slo = payload.get("soft_data_slo") or {}
    max_age_map = slo.get("max_age_days") or {}
    for key in {canonical, _trust_display_name(canonical)}:
        if key in max_age_map:
            return _float_or_none(max_age_map.get(key))
    profile = _trust_profile(canonical)
    if profile is not None:
        return float(profile.max_age_days)
    default = slo.get("default_max_age_days")
    if default is not None:
        return _float_or_none(default)
    return None


def _trust_latency_days(row: Dict[str, Any], payload: Dict[str, Any]) -> Optional[float]:
    latency = _float_or_none(row.get("latency_days"))
    if latency is not None:
        return latency
    picked = _parse_iso_date(row.get("as_of") or row.get("date"))
    reference = _parse_iso_date(payload.get("as_of")) or date.today()
    if picked is None:
        return None
    return float(max(0, (reference - picked).days))


def _parse_iso_date(value: Any) -> Optional[date]:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _float_or_none(value: Any) -> Optional[float]:
    try:
        out = float(value)
        return out if out == out else None
    except (TypeError, ValueError):
        return None


def _trust_badge(label: str) -> str:
    kind = "ok"
    if label in {"代理", "proxy", "Proxy"}:
        kind = "warn"
    elif label in {"缺失", "missing", "Missing", "UNAVAILABLE"}:
        kind = "danger"
    elif label in {"未启用", "disabled", "Disabled"}:
        kind = "watch"
    return _badge(label, kind)


def _trust_slo_badge(label: str, kind: str) -> str:
    return _badge(label, kind)


def _render_quality_detail_body(payload: Dict[str, Any], manifest_status: Dict[str, Any] | None = None) -> str:
    manifest_status = manifest_status or {}
    dq = payload.get("all_source_data_quality") or payload.get("data_quality") or {}
    breakdown = payload.get("data_quality_breakdown") or {}
    components = breakdown.get("components") or {}
    upgrades = breakdown.get("upgrade_to_high") or []
    sources = breakdown.get("sources") or []
    penalties = dq.get("penalties") or []
    rows = [
        f"<tr><td>{esc(p.get('reason'))}</td><td>{esc(p.get('field'))}</td><td>{_fmt_num(p.get('penalty'))}</td></tr>"
        for p in penalties[:8]
    ]
    source_rows = [
        "<tr>"
        f"<td>{esc(row.get('category'))}</td><td><b>{esc(row.get('name'))}</b></td>"
        f"<td>{esc(row.get('status'))}</td><td>{esc(row.get('as_of'))}</td>"
        f"<td>{esc(row.get('decision_role', 'strategy'))}</td>"
        f"<td>{'是' if row.get('is_proxy') else '否'}</td><td>{_fmt_num(row.get('latency_days'))}</td>"
        "</tr>"
        for row in sources[:16]
    ]
    upgrade_rows = "".join(f"<li>{esc(item)}</li>" for item in upgrades[:8])
    frozen_at = str(manifest_status.get("frozen_at") or "NA")[:19].replace("T", " ")
    manifest_line = (
        f'<div class="subtle" style="margin-bottom:8px">{_manifest_badge(manifest_status)} '
        f'frozen_at={esc(frozen_at)} · 数据清单(sha256)与历史 CSV 校验 '
        f'<code>verify_manifest</code>，DRIFT 表示回填后未重冻结 '
        f'<button class="btn-muted" style="padding:3px 9px;font-size:12px" '
        f'onclick="refreshManifest()" id="manifest-refresh-btn">刷新数据清单</button>'
        f'<span class="subtle" id="manifest-refresh-status" style="margin-left:8px"></span></div>'
    )
    return f"""
      <h3>Audit Detail / 全源观测质量 {_badge(str(dq.get('level') or 'NA') + ' ' + _fmt_num(dq.get('overall_score')), _quality_kind(dq.get('level')))}</h3>
      <div class="mini-note" style="margin-bottom:8px">包含策略、辅助与研究源；研究/辅助源扣分只用于运维观察，不作为策略阻断项。</div>
      <div class="facts" style="margin-bottom:10px">
        {_metric('Completeness', _fmt_num(dq.get('completeness_score')))}
        {_metric('Quality', _fmt_num(dq.get('quality_score')))}
        {_metric('Latency', _fmt_num(dq.get('latency_score')))}
        {_metric('价格新鲜', '是' if components.get('price_fresh') else '否')}
        {_metric('软数据代理', esc(components.get('soft_proxy_count', 'NA')))}
        {_metric('IBKR 状态', f"{esc(components.get('ibkr_source', 'NA'))}{' / STALE' if components.get('ibkr_stale') else ''}")}
      </div>
      {manifest_line}
      <details style="margin-bottom:10px">
        <summary>为什么是 {esc(dq.get('level', 'NA'))}，如何升到 HIGH</summary>
        <div class="detail-body">
          <ol>{upgrade_rows or '<li>暂无升级建议。</li>'}</ol>
        </div>
      </details>
      <details style="margin-bottom:10px">
        <summary>数据源明细 / source freshness</summary>
        <div class="detail-body">
          <table>
            <thead><tr><th>类别</th><th>名称</th><th>状态</th><th>日期</th><th>角色</th><th>代理</th><th>延迟天</th></tr></thead>
            <tbody>{''.join(source_rows) if source_rows else '<tr><td colspan="7">暂无数据源明细</td></tr>'}</tbody>
          </table>
        </div>
      </details>
      <div class="table-scroll">
        <table>
          <thead><tr><th>类型</th><th>字段</th><th>惩罚</th></tr></thead>
          <tbody>{''.join(rows) if rows else '<tr><td colspan="3">暂无数据质量惩罚</td></tr>'}</tbody>
        </table>
      </div>
    """


def _render_quality_section(payload: Dict[str, Any], manifest_status: Dict[str, Any] | None = None) -> str:
    return f"""
    <section>
      {_render_quality_detail_body(payload, manifest_status)}
    </section>
    """


def _render_scripts(as_of: str) -> str:
    return f"""
  <script>
  function setBusy(btn, busy) {{
    if (!btn) return;
    btn.disabled = busy;
    btn.style.opacity = busy ? '0.6' : '1';
  }}
  function hermesToken() {{
    try {{
      var params = new URLSearchParams(window.location.search || '');
      var fromUrl = params.get('token') || params.get('confirm_token');
      if (fromUrl) {{
        sessionStorage.setItem('HERMES_CONFIRM_TOKEN', fromUrl);
        return fromUrl;
      }}
    }} catch (e) {{}}
    try {{
      return window.HERMES_CONFIRM_TOKEN ||
        sessionStorage.getItem('HERMES_CONFIRM_TOKEN') ||
        localStorage.getItem('HERMES_CONFIRM_TOKEN') ||
        localStorage.getItem('hermes_confirm_token') || '';
    }} catch (e) {{
      return window.HERMES_CONFIRM_TOKEN || '';
    }}
  }}
  function postJson(endpoint, payload) {{
    var headers = {{'Content-Type': 'application/json'}};
    var token = hermesToken();
    if (token) headers['X-Hermes-Token'] = token;
    return fetch(endpoint, {{
      method: 'POST',
      headers: headers,
      body: JSON.stringify(payload || {{}})
    }});
  }}
  function showResult(text) {{
    var out = document.getElementById('refresh-result');
    if (!out) return;
    out.textContent = text;
    out.style.display = 'block';
  }}
  function rememberRefresh(statusId, text, resultText) {{
    try {{
      sessionStorage.setItem('hermesLastRefresh', JSON.stringify({{statusId: statusId, text: text, resultText: resultText || text}}));
    }} catch (e) {{}}
  }}
  function restoreRefreshStatus() {{
    try {{
      var raw = sessionStorage.getItem('hermesLastRefresh');
      if (!raw) return;
      sessionStorage.removeItem('hermesLastRefresh');
      var msg = JSON.parse(raw);
      var st = document.getElementById(msg.statusId || 'refresh-score-status');
      if (st) st.textContent = msg.text || '';
      if (msg.resultText) showResult(msg.resultText);
    }} catch (e) {{}}
  }}
  window.refreshScore = function() {{
    var btn = document.getElementById('refresh-score-btn');
    var st = document.getElementById('refresh-score-status');
    setBusy(btn, true);
    st.textContent = '正在刷新新系统数据...';
    postJson('/api/refresh_score', {{as_of: 'latest', refresh_history: true}}).then(function(r) {{ return r.json(); }}).then(function(d) {{
      if (d && d.scores) {{
        var msg = '策略数据刷新完成，载入 ' + (d.as_of || 'latest');
        st.textContent = msg;
        rememberRefresh('refresh-score-status', msg, 'strategy refreshed: as_of=' + (d.as_of || 'latest'));
        setTimeout(function() {{ location.href = '/?as_of=' + encodeURIComponent(d.as_of || 'latest') + '&view=preview'; }}, 600);
      }} else {{
        st.textContent = '刷新失败: ' + (d.message || d.error || 'unknown');
        setBusy(btn, false);
      }}
    }}).catch(function(e) {{
      st.textContent = '刷新失败: ' + e;
      setBusy(btn, false);
    }});
  }};
  window.refreshPositions = function() {{
    var btn = document.getElementById('refresh-positions-btn');
    var st = document.getElementById('refresh-positions-status');
    setBusy(btn, true);
    st.textContent = '正在轻量读取 IBKR 持仓（不重抓行情、不重算官方策略）...';
    postJson('/api/refresh_positions', {{as_of: 'latest'}}).then(function(r) {{ return r.json(); }}).then(function(d) {{
      var ibkr = d.ibkr || {{}};
      if (ibkr.source === 'tws' && !ibkr.snapshot_stale) {{
        var msg = '持仓轻量刷新完成: ' + ibkr.source + ' · NetLiq ' + (ibkr.net_liq || 'NA');
        st.textContent = msg;
        rememberRefresh('refresh-positions-status', msg, 'ibkr refreshed only; no market refresh, no official rerun\\nsource=' + ibkr.source + '\\nnet_liq=' + ibkr.net_liq);
        setTimeout(function() {{ location.href = '/?as_of=' + encodeURIComponent(d.as_of || 'latest'); }}, 600);
      }} else if (ibkr.source) {{
        var staleMsg = '持仓未更新：未连接 IBKR Live，沿用 ' + ibkr.source + ' 快照';
        st.textContent = staleMsg;
        rememberRefresh('refresh-positions-status', staleMsg, ibkr.error || ('source=' + ibkr.source));
        setBusy(btn, false);
      }} else {{
        st.textContent = '持仓刷新失败: ' + (d.message || d.error || 'unknown');
        setBusy(btn, false);
      }}
    }}).catch(function(e) {{
      st.textContent = '持仓刷新失败: ' + e;
      setBusy(btn, false);
    }});
  }};
  window.refreshManifest = function() {{
    var btn = document.getElementById('manifest-refresh-btn');
    var st = document.getElementById('manifest-refresh-status');
    setBusy(btn, true);
    if (st) st.textContent = '正在重冻结数据清单...';
    postJson('/api/refresh_manifest', {{}})
      .then(function(r) {{ return r.json(); }}).then(function(d) {{
        setBusy(btn, false);
        if (st) st.textContent = d.ok ? ('已重冻结 ✓ frozen_at=' + (d.frozen_at || '')) : ('失败: ' + (d.error || d.status || 'unknown'));
        if (d.ok) setTimeout(function() {{ location.reload(); }}, 700);
      }}).catch(function(e) {{ setBusy(btn, false); if (st) st.textContent = '失败: ' + e; }});
  }};
  window.refreshExternalSource = function(sourceId) {{
    var btn = document.getElementById('external-source-quick-' + sourceId + '-btn') ||
              document.getElementById('external-source-' + sourceId + '-btn');
    var st = document.getElementById('external-source-quick-' + sourceId + '-status') ||
             document.getElementById('external-source-' + sourceId + '-status') ||
             document.getElementById('external-source-status');
    setBusy(btn, true);
    if (st) st.textContent = '正在刷新 ' + sourceId + ' 外部源...';
    postJson('/api/refresh_external_source', {{source_id: sourceId}})
      .then(function(r) {{ return r.json(); }}).then(function(d) {{
        setBusy(btn, false);
        if (d.ok) {{
          var run = d.run || {{}};
          if (st) st.textContent = sourceId + ' 已刷新 ✓ latest=' + (run.latest_promoted_as_of || run.latest_normalized_as_of || 'NA');
          setTimeout(function() {{ location.reload(); }}, 900);
        }} else {{
          if (st) st.textContent = sourceId + ' 刷新失败: ' + (d.message || d.error || d.status || 'unknown');
        }}
      }}).catch(function(e) {{ setBusy(btn, false); if (st) st.textContent = sourceId + ' 刷新失败: ' + e; }});
  }};
  window.refreshExternalSourceImport = function(sourceId, importFile) {{
    var btn = document.getElementById('external-import-' + sourceId + '-btn');
    var st = document.getElementById('external-import-' + sourceId + '-status') ||
             document.getElementById('external-source-status');
    setBusy(btn, true);
    if (st) st.textContent = '正在校验并导入 ' + sourceId + ' 官方文件...';
    postJson('/api/refresh_external_source', {{source_id: sourceId, import_file: importFile}})
      .then(function(r) {{ return r.json(); }}).then(function(d) {{
        setBusy(btn, false);
        if (d.ok) {{
          var run = d.run || {{}};
          if (st) st.textContent = sourceId + ' 官方文件导入完成 ✓ latest=' + (run.latest_promoted_as_of || run.latest_normalized_as_of || 'NA');
          setTimeout(function() {{ location.reload(); }}, 900);
        }} else {{
          if (st) st.textContent = sourceId + ' 官方文件导入失败: ' + (d.message || d.error || d.status || 'unknown');
        }}
      }}).catch(function(e) {{ setBusy(btn, false); if (st) st.textContent = sourceId + ' 官方文件导入失败: ' + e; }});
  }};
  window.refreshExternalSources = function() {{
    var btn = document.getElementById('external-sources-refresh-all-header-btn') ||
              document.getElementById('external-sources-refresh-all-btn');
    var st = document.getElementById('external-source-header-status') ||
             document.getElementById('external-source-status');
    setBusy(btn, true);
    if (st) st.textContent = '正在刷新全部外部源...';
    postJson('/api/refresh_external_sources', {{}})
      .then(function(r) {{ return r.json(); }}).then(function(d) {{
        setBusy(btn, false);
        var runs = d.runs || [];
        var failed = runs.filter(function(row) {{ return row.status !== 'OK'; }})
                         .map(function(row) {{ return row.source_id + ':' + row.status; }});
        if (st) {{
          st.textContent = '完成：OK ' + (d.ok_count || 0) + ' / 失败 ' + (d.error_count || 0) +
            (failed.length ? (' · ' + failed.join(', ')) : '');
        }}
        setTimeout(function() {{ location.reload(); }}, 1100);
      }}).catch(function(e) {{ setBusy(btn, false); if (st) st.textContent = '刷新全部外部源失败: ' + e; }});
  }};
  window.rerunExternalPrecheck = function() {{
    var btn = document.getElementById('external-precheck-rerun-btn');
    var st = document.getElementById('external-precheck-rerun-status');
    setBusy(btn, true);
    if (st) st.textContent = '正在重跑外部源预检...';
    postJson('/api/rerun_external_precheck', {{}})
      .then(function(r) {{ return r.json(); }}).then(function(d) {{
        setBusy(btn, false);
        var precheck = d.external_precheck_status || {{}};
        if (st) {{
          st.textContent = '预检完成：ready=' + (!!precheck.ready) +
            ' · stale=' + (!!precheck.stale) +
            ' · rc=' + (typeof d.returncode === 'number' ? d.returncode : 'NA');
        }}
        setTimeout(function() {{ location.reload(); }}, 900);
      }}).catch(function(e) {{
        setBusy(btn, false);
        if (st) st.textContent = '重跑外部源预检失败: ' + e;
      }});
  }};
  restoreRefreshStatus();
  </script>
    """


def _top_factor_items(score: Dict[str, Any], limit: int = 5) -> List[tuple[str, Dict[str, Any]]]:
    factors: List[tuple[float, str, Dict[str, Any]]] = []
    for module, rows in (score.get("factor_scores") or {}).items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            pts = _float(row.get("score"), 0.0)
            if pts > 0:
                factors.append((pts, str(module), row))
    factors.sort(key=lambda item: item[0], reverse=True)
    return [(module, row) for _, module, row in factors[:limit]]


def _top_factor_rows(score: Dict[str, Any], limit: int = 5) -> List[str]:
    out = []
    for module, row in _top_factor_items(score, limit=limit):
        pts = _float(row.get("score"), 0.0)
        max_score = row.get("max_score")
        score_text = f"{_fmt_num(pts)}/{_fmt_num(max_score)}" if max_score is not None else _fmt_num(pts)
        out.append(
            "<tr>"
            f"<td>{esc(module)}</td>"
            f"<td>{esc(row.get('factor_id', row.get('name', '')))}</td>"
            f"<td>{score_text}</td>"
            f"<td>{_factor_explain_cell(row)}</td>"
            "</tr>"
        )
    return out


def _valve_reason_text(score: Dict[str, Any], hits: List[Any]) -> str:
    explains = [str(item) for item in (score.get("explain") or [])]
    hit_text = [str(hit) for hit in hits]
    matched = [
        item for item in explains
        if "Hard valve" in item or any(hit and hit in item for hit in hit_text)
    ]
    if not matched:
        matched = ["触发：" + ", ".join(hit_text)]
    return "；".join(matched[:2])


def _valve_candidates_for(score: Dict[str, Any], hv_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates = score.get("valve_candidates") or hv_state.get("candidates") or []
    return [row for row in candidates if isinstance(row, dict)]


def _valve_summary_badge(candidates: List[Dict[str, Any]]) -> str:
    statuses = [str(row.get("status") or "clear").lower() for row in candidates]
    triggered = sum(1 for status in statuses if status == "triggered")
    pending = sum(1 for status in statuses if status == "pending")
    buffered = sum(1 for status in statuses if status == "buffered")
    if triggered:
        return _badge(f"已触发 {triggered}", "danger")
    if pending:
        return _badge(f"PENDING {pending}", "warn")
    if buffered:
        return _badge(f"BUFFERED {buffered}", "warn")
    return _badge("未触发", "")


def _summarize_valve_candidates(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    triggered, pending, near = [], [], []
    for candidate in candidates:
        status = str(candidate.get("status") or "clear").lower()
        if status == "triggered":
            triggered.append(candidate)
        elif status in {"pending", "buffered"}:
            pending.append(candidate)
        elif _valve_near_candidate(candidate):
            near.append(candidate)
    parts = []
    if triggered:
        parts.append("已触发：" + ", ".join(str(row.get("id", "")) for row in triggered[:3]))
    if pending:
        parts.append("待确认：" + ", ".join(str(row.get("id", "")) for row in pending[:3]))
    if near:
        parts.append("接近：" + ", ".join(str(row.get("id", "")) for row in near[:3]))
    note = "；".join(parts) if parts else "未触发硬阀门，暂无接近项。"
    return {"triggered": len(triggered), "pending": len(pending), "near": len(near), "note": note}


def _valve_near_candidate(candidate: Dict[str, Any]) -> bool:
    current = candidate.get("current") or {}
    threshold = candidate.get("threshold") or {}
    if not isinstance(current, dict) or not isinstance(threshold, dict):
        return False
    try:
        if current.get("close") is not None and current.get("ma200"):
            gap = (float(current["close"]) - float(current["ma200"])) / float(current["ma200"])
            return 0.0 <= gap <= 0.08
        if current.get("return_1d") is not None and threshold.get("return_1d") is not None:
            distance = float(current["return_1d"]) - float(threshold["return_1d"])
            return 0.0 <= distance <= 0.05
        if current.get("return_2d") is not None and threshold.get("return_2d") is not None:
            distance = float(current["return_2d"]) - float(threshold["return_2d"])
            return 0.0 <= distance <= 0.07
        if current.get("drawdown_60d") is not None and threshold.get("drawdown_60d") is not None:
            distance = float(current["drawdown_60d"]) - float(threshold["drawdown_60d"])
            return 0.0 <= distance <= 0.05
    except (TypeError, ValueError, ZeroDivisionError):
        return False
    return False


def _valve_bucket_statuses(candidates: List[Dict[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    rank = {"triggered": 0, "pending": 1, "buffered": 1, "near": 2, "clear": 3}
    for candidate in candidates:
        bucket = _valve_bucket(candidate)
        status = str(candidate.get("status") or "clear").lower()
        if status not in {"triggered", "pending", "buffered"}:
            status = "near" if _valve_near_candidate(candidate) else "clear"
        if bucket not in out or rank.get(status, 9) < rank.get(out[bucket], 9):
            out[bucket] = status
    return out


def _valve_bucket(candidate: Dict[str, Any]) -> str:
    text = " ".join(str(candidate.get(key) or "") for key in ("id", "desc", "confirm_condition")).lower()
    threshold = candidate.get("threshold") or {}
    if "chandelier" in text:
        return "Chandelier"
    if "ema50" in text:
        return "EMA50"
    if "ma200" in text or (isinstance(threshold, dict) and threshold.get("close_vs") == "ma200"):
        return "MA200"
    if "2-day" in text or "2d" in text or (isinstance(threshold, dict) and "return_2d" in threshold):
        return "2D Crash"
    if "daily" in text or "single-day" in text or "1d" in text or (isinstance(threshold, dict) and "return_1d" in threshold):
        return "1D Crash"
    if "btc" in text or "qqq" in text:
        return "BTC/QQQ"
    if "score" in text or "flow" in text or "资金" in text:
        return "Score/Flow"
    return "Score/Flow"


def _valve_matrix_cell(status: Optional[str]) -> str:
    if not status:
        return "<td class='subtle'>—</td>"
    labels = {
        "triggered": ("红", "danger"),
        "pending": ("黄", "warn"),
        "buffered": ("黄", "warn"),
        "near": ("橙", "watch"),
        "clear": ("灰", ""),
    }
    label, kind = labels.get(status, ("灰", ""))
    return f"<td>{_badge(label, kind)}</td>"


def _render_valve_candidate_grid(candidates: List[Dict[str, Any]]) -> str:
    items = []
    for candidate in candidates:
        status = str(candidate.get("status") or "clear").lower()
        cls = status if status in {"triggered", "pending", "buffered", "clear"} else "clear"
        label, kind = _valve_status_label(status)
        items.append(
            f"<div class='valve-item {cls}'>"
            "<div class='valve-title'>"
            f"<b>{esc(candidate.get('id', 'VALVE'))}</b>{_badge(label, kind)}"
            "</div>"
            f"<div class='mini-note'>{esc(candidate.get('desc', ''))}</div>"
            f"<div class='valve-metrics'><b>当前：</b>{esc(_valve_value_text(candidate.get('current')))}</div>"
            f"<div class='valve-metrics'><b>阈值：</b>{esc(_valve_value_text(candidate.get('threshold')))}</div>"
            f"<div class='valve-metrics'><b>距离：</b>{esc(_valve_distance_from_candidate(candidate))}</div>"
            f"<div class='valve-metrics'><b>确认：</b>{esc(candidate.get('confirm_condition') or 'NA')}</div>"
            "</div>"
        )
    return f"<div class='valve-grid'>{''.join(items)}</div>"


def _valve_status_label(status: str) -> tuple[str, str]:
    if status == "triggered":
        return "已触发", "danger"
    if status == "pending":
        return "PENDING", "warn"
    if status == "buffered":
        return "BUFFERED", "warn"
    return "未触发", ""


def _valve_value_text(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return "复合/持续型，无单一当前值"
    parts = []
    for key, raw in value.items():
        parts.append(f"{key}={_fmt_valve_scalar(key, raw)}")
    return " / ".join(parts)


def _fmt_valve_scalar(key: Any, value: Any) -> str:
    key_s = str(key)
    if key_s.startswith("return_") or "drawdown" in key_s:
        return _fmt_pct(value, signed=True)
    if key_s in {"close", "ma200", "ema10", "ema20", "ema50", "chandelier"}:
        return _fmt_money(value)
    return _fmt_num(value)


def _valve_distance_from_candidate(candidate: Dict[str, Any]) -> str:
    current = candidate.get("current")
    threshold = candidate.get("threshold")
    if not isinstance(current, dict) or not isinstance(threshold, dict):
        return "复合/持续型：看确认条件"

    parts: List[str] = []
    if threshold.get("close_vs") == "ma200":
        parts.extend(_relative_gap_parts(current, "close", "ma200", "MA200"))
    parts.extend(_lte_gap_parts(current, threshold, "return_1d", "日跌幅", pct=True))
    parts.extend(_lte_gap_parts(current, threshold, "return_2d", "两日跌幅", pct=True))
    parts.extend(_gte_gap_parts(current, threshold, "total_score", "总分"))
    parts.extend(_gte_gap_parts(current, threshold, "c_score", "C 分"))
    if "drawdown_60d" in threshold:
        parts.extend(_lte_gap_parts(current, threshold, "drawdown_60d", "60d 回撤", pct=True))
        parts.extend(_relative_gap_parts(current, "close", "chandelier", "Chandelier"))
    if "ema50" in current:
        parts.extend(_relative_gap_parts(current, "close", "ema50", "EMA50"))
    return "；".join(parts) if parts else "暂无可计算距离"


def _relative_gap_parts(current: Dict[str, Any], left_key: str, right_key: str, label: str) -> List[str]:
    left = _num_or_none(current.get(left_key))
    right = _num_or_none(current.get(right_key))
    if left is None or right in {None, 0}:
        return []
    gap = left / right - 1.0
    relation = "高于" if gap >= 0 else "低于"
    return [f"{left_key} {relation} {label} {_fmt_pct(abs(gap))}（{_fmt_money(left)} vs {_fmt_money(right)}）"]


def _lte_gap_parts(current: Dict[str, Any], threshold: Dict[str, Any], key: str, label: str, *, pct: bool = False) -> List[str]:
    value = _num_or_none(current.get(key))
    limit = _num_or_none(threshold.get(key))
    if value is None or limit is None:
        return []
    gap = value - limit
    if pct:
        text = f"{abs(gap) * 100.0:.1f}pct"
    else:
        text = _fmt_num(abs(gap))
    state = "已越过阈值" if value <= limit else "距触发还差"
    return [f"{label} {state} {text}"]


def _gte_gap_parts(current: Dict[str, Any], threshold: Dict[str, Any], key: str, label: str) -> List[str]:
    value = _num_or_none(current.get(key))
    limit = _num_or_none(threshold.get(key))
    if value is None or limit is None:
        return []
    gap = limit - value
    state = "已达到阈值" if value >= limit else "距触发还差"
    return [f"{label} {state} {_fmt_num(abs(gap))}"]


def _valve_distance_text(symbol: str, payload: Dict[str, Any]) -> str:
    close = _num_or_none(_snap(payload, symbol, "close"))
    if close is None:
        return "未触发；缺少当前价，无法计算距触发距离。"
    parts = []
    for label, field in [("Chandelier", "chandelier_exit"), ("MA200", "ma200"), ("EMA20", "ema20")]:
        level = _num_or_none(_snap(payload, symbol, field))
        if level is None or level == 0:
            continue
        gap = close / level - 1.0
        relation = "高于" if gap >= 0 else "低于"
        parts.append(f"{label}: 当前价{relation}触发线 {_fmt_pct(abs(gap))}（{_fmt_money(close)} vs {_fmt_money(level)}）")
    return "未触发；" + ("；".join(parts) if parts else "暂无可计算硬阀门距离。")


def _latest_daily_diff_path(as_of: str) -> Optional[Path]:
    roots = [REPO_ROOT / "reports", REPO_ROOT / "reports" / "shadow"]
    names = []
    if as_of:
        names.append(f"daily_diff_{as_of[:10]}.md")
    for name in names:
        for root in roots:
            path = root / name
            if path.exists():
                return path
    candidates: List[Path] = []
    for root in roots:
        if root.exists():
            candidates.extend(sorted(root.glob("daily_diff_*.md")))
    return sorted(candidates)[-1] if candidates else None


def _markdown_to_html(text: str) -> str:
    lines: List[str] = []
    in_list = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            if in_list:
                lines.append("</ul>")
                in_list = False
            continue
        if line.startswith("# "):
            if in_list:
                lines.append("</ul>")
                in_list = False
            lines.append(f"<h3>{esc(line[2:].strip())}</h3>")
        elif line.startswith("## "):
            if in_list:
                lines.append("</ul>")
                in_list = False
            lines.append(f"<h3>{esc(line[3:].strip())}</h3>")
        elif line.lstrip().startswith("- "):
            if not in_list:
                lines.append("<ul>")
                in_list = True
            item = line.lstrip()[2:].strip()
            lines.append(f"<li>{esc(item)}</li>")
        else:
            if in_list:
                lines.append("</ul>")
                in_list = False
            lines.append(f"<p>{esc(line)}</p>")
    if in_list:
        lines.append("</ul>")
    return "".join(lines)


def _factor_explain_cell(row: Dict[str, Any]) -> str:
    professional = row.get("professional_explain") or row.get("explain") or ""
    plain = row.get("plain_explain") or ""
    data_hint = row.get("data_hint") or ""
    parts = [f"<div>{esc(row.get('explain', ''))}</div>"]
    if professional and professional != row.get("explain"):
        parts.append(f"<div class='subtle'><b>专业：</b>{esc(professional)}</div>")
    if plain:
        parts.append(f"<div class='subtle'><b>白话：</b>{esc(plain)}</div>")
    if data_hint:
        parts.append(f"<div class='subtle'><b>数据：</b>{esc(data_hint)}</div>")
    return "".join(parts)


def _module_box(module: str, value: Any) -> str:
    score = _float(value, 0.0)
    width = max(0.0, min(100.0, score / 25.0 * 100.0))
    kind = "danger" if score >= 12 else "warn" if score >= 6 else ""
    return f"""
    <div class="module">
      <b>{esc(module)} 模块</b>
      <div class="bar"><span class="{kind}" style="width:{width:.1f}%"></span></div>
      <div class="subtle" style="margin-top:5px">{_fmt_num(score)} 分</div>
    </div>
    """


def _metric(label: str, value: str) -> str:
    return f'<div class="metric"><div class="label">{esc(label)}</div><div class="value">{value}</div></div>'


def _tr(label: str, value: str, note: str) -> str:
    return f"<tr><td>{esc(label)}</td><td><b>{value}</b></td><td class='subtle'>{note}</td></tr>"


def _hard_valves(hard: Iterable[str]) -> str:
    hard = list(hard or [])
    if not hard:
        return '<div class="warning-box" style="background:#f0fdf4;border-color:#bbf7d0;color:#166534">未触发硬阀门。</div>'
    return f'<div class="warning-box">硬阀门触发：<b>{esc(", ".join(hard))}</b></div>'


def _warning(text: Any) -> str:
    if not text:
        return ""
    return f'<div class="warning-box" style="margin:10px 0">{esc(text)}</div>'


def _route_label(route: Dict[str, Any]) -> str:
    if not route or route.get("applies") is False:
        return "NONE"
    return str(route.get("defcon") or route.get("destination") or "ROUTE")


def _route_text(route: Dict[str, Any]) -> str:
    if not route or route.get("applies") is False:
        return "不路由"
    weights = route.get("weights") or {}
    if weights:
        dest = " / ".join(f"{k} {_fmt_pct(v)}" for k, v in weights.items())
    else:
        dest = str(route.get("destination", "-"))
    return f"{esc(route.get('defcon', 'ROUTE'))} -> {esc(dest)}"


def _mini_vol_svg(before: float, after: float) -> str:
    max_v = max(before, after, 1e-9)
    before_w = max(2.0, min(96.0, before / max_v * 96.0))
    after_w = max(2.0, min(96.0, after / max_v * 96.0))
    after_color = "#dc2626" if after > before else "#047857"
    return (
        "<svg class='spark-svg' viewBox='0 0 100 44' role='img' aria-label='vol before after'>"
        "<rect x='2' y='8' width='96' height='8' rx='4' fill='#e5e7eb'/>"
        f"<rect x='2' y='8' width='{before_w:.1f}' height='8' rx='4' fill='#64748b'/>"
        "<rect x='2' y='28' width='96' height='8' rx='4' fill='#e5e7eb'/>"
        f"<rect x='2' y='28' width='{after_w:.1f}' height='8' rx='4' fill='{after_color}'/>"
        "<text x='2' y='7' font-size='6' fill='#64748b'>before</text>"
        "<text x='2' y='27' font-size='6' fill='#64748b'>after</text>"
        "</svg>"
    )


def _correlation_gauge(corr: Any, threshold: Any) -> str:
    corr_v = _num_or_none(corr)
    threshold_v = _num_or_none(threshold)
    if corr_v is None:
        threshold_text = _fmt_num(threshold_v) if threshold_v is not None else "NA"
        return f"<div class='mini-note'>BRK.B 当前相关性不可用；阈值 {threshold_text}。</div>"
    threshold_v = 0.85 if threshold_v is None else max(0.0, min(1.0, threshold_v))
    corr_v = max(0.0, min(1.0, corr_v))
    x = 4 + corr_v * 92
    tx = 4 + threshold_v * 92
    color = "#dc2626" if corr_v >= threshold_v else "#047857"
    return (
        "<svg class='spark-svg' viewBox='0 0 100 42' role='img' aria-label='BRK.B correlation gauge'>"
        "<rect x='4' y='17' width='92' height='8' rx='4' fill='#e5e7eb'/>"
        f"<rect x='4' y='17' width='{corr_v*92:.1f}' height='8' rx='4' fill='{color}'/>"
        f"<line x1='{tx:.1f}' y1='10' x2='{tx:.1f}' y2='32' stroke='#b45309' stroke-width='1.5'/>"
        f"<circle cx='{x:.1f}' cy='21' r='4' fill='{color}'/>"
        "<text x='4' y='9' font-size='6' fill='#64748b'>corr</text>"
        "<text x='62' y='39' font-size='6' fill='#64748b'>threshold</text>"
        "</svg>"
    )


def _action_cn(action: Any) -> str:
    mapping = {
        "SELL_AND_ROUTE": "清仓并路由防守资产",
        "REDUCE_AND_ROUTE": "减仓并路由防守资产",
        "HOLD_OR_MAINTAIN": "持有或维持目标仓位",
        "STAY_OUT": "继续场外观察",
    }
    return mapping.get(str(action or ""), str(action or "暂无指令"))


def _ibkr_row(ibkr: Dict[str, Any], symbol: str) -> Optional[Dict[str, Any]]:
    for bucket in ["trade_symbols", "route_legs", "extra_positions"]:
        for row in ibkr.get(bucket, []) or []:
            if row.get("symbol") == symbol:
                return row
    return None


def _ibkr_text(row: Optional[Dict[str, Any]]) -> str:
    if not row:
        return "无持仓"
    return f"{_fmt_num(row.get('actual_shares'))} 股 · {_fmt_pct(row.get('actual_weight'))} · {esc(row.get('status'))}"


def _snap(payload: Dict[str, Any], symbol: str, field: str) -> Any:
    snap = (payload.get("snapshots") or {}).get(symbol, {})
    fields = snap.get("fields") or {}
    row = fields.get(field) or {}
    return row.get("value")


def _badge(text: str, kind: str = "") -> str:
    kind = kind if kind in {"ok", "warn", "danger", "watch"} else ""
    return f'<span class="badge {kind}">{esc(text)}</span>'


def _first_score(payload: Dict[str, Any]) -> Dict[str, Any]:
    scores = payload.get("scores") or {}
    for symbol in TRADE_SYMBOLS:
        if isinstance(scores.get(symbol), dict):
            return scores[symbol]
    for score in scores.values():
        if isinstance(score, dict):
            return score
    return {}


def _short_factor_id(factor_id: Any) -> str:
    mapping = {
        "A1_QQQ_MA200_BREAK": "QQQ 跌破 MA200",
        "A1_VIX_COMPLACENCY": "VIX 低波动",
        "A2_CNN_FEAR_GREED": "恐惧贪婪",
        "A2_AAII_BULL": "AAII 情绪",
        "A2_NAAIM": "NAAIM 仓位",
        "A2_CBOE_EQUITY_PCR": "期权 PCR",
        "A3_CBOE_PCR": "期权 PCR",
        "A3_COMPONENT_BREADTH": "市场宽度",
        "A4_QQQ_STRETCH": "QQQ 乖离",
        "A4_NET_LIQUIDITY": "宏观流动性",
        "A5_NET_LIQUIDITY": "宏观流动性",
        "A5_VOL_TERM_STRUCTURE": "波动率期限",
        "A6_FUND_FLOW": "资金流",
        "A7_BTC_FUNDING": "BTC 资金费率",
        "A7_VIX_TERM_STRUCTURE": "VIX 期限结构",
        "A8_BREADTH": "市场宽度",
        "A8_QQQ_DISTRIBUTION": "QQQ 派发压力",
    }
    text = str(factor_id or "")
    return mapping.get(text, text.replace("_", " "))


def _status_kind(status: str) -> str:
    if status in {"EXIT", "DEFENSIVE_EXIT"}:
        return "danger"
    if status == "REDUCE":
        return "warn"
    if status in {"TRIM", "WATCH"}:
        return "watch"
    return "ok"


def _quality_kind(level: Any) -> str:
    level = str(level or "").upper()
    if level in {"HIGH", "GOOD"}:
        return "ok"
    if level in {"LOW", "NO_CACHE"}:
        return "danger"
    return "warn"


def _ibkr_kind(ibkr: Dict[str, Any]) -> str:
    if ibkr.get("snapshot_stale"):
        return "danger"
    src = str(ibkr.get("source", "")).lower()
    if src == "tws":
        return "ok"
    if src in {"snapshot", "disabled"}:
        return "warn"
    return "danger"


def _ibkr_status_kind(status: str) -> str:
    if status == "MATCH":
        return "ok"
    if status in {"UNDER", "MISSING"}:
        return "warn"
    if status in {"OVER", "EXTRA"}:
        return "danger"
    return "watch"


def _flow_kind(severity: str) -> str:
    severity = str(severity or "").upper()
    if severity in {"SEVERE", "ABNORMAL"}:
        return "danger"
    if severity == "WATCH":
        return "warn"
    if severity == "NORMAL":
        return "ok"
    return "watch"


def _confidence_missing_text(layers: Dict[str, Any], bucket: str) -> str:
    confidence = (layers or {}).get("strategy_confidence") or (layers or {}).get("action_confidence") or {}
    if bucket == "scored":
        weight = confidence.get("scored_missing_weight")
        fields = confidence.get("scored_missing_fields") or []
        suffix = "影响策略置信"
    else:
        weight = confidence.get("non_scoring_missing_weight")
        fields = confidence.get("non_scoring_missing_fields") or []
        suffix = "单独监控"
    names = ", ".join(str(item) for item in fields[:3])
    if len(fields) > 3:
        names += f" +{len(fields) - 3}"
    return f"{_fmt_num(weight)} · {esc(names or '无')} · {suffix}"


def _fmt_money(value: Any) -> str:
    if value is None:
        return "NA"
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return esc(value)


def _fmt_flow_money(value: Any) -> str:
    if value is None:
        return "NA"
    try:
        val = float(value)
    except (TypeError, ValueError):
        return esc(value)
    sign = "+" if val > 0 else "-" if val < 0 else ""
    abs_val = abs(val)
    for suffix, scale in [("T", 1_000_000_000_000), ("B", 1_000_000_000), ("M", 1_000_000)]:
        if abs_val >= scale:
            return f"{sign}${abs_val / scale:.2f}{suffix}"
    return f"{sign}${abs_val:,.0f}"


def _fmt_flow_gross(value: Any) -> str:
    formatted = _fmt_flow_money(value)
    return formatted[1:] if formatted.startswith("+") else formatted


def _fmt_pct(value: Any, signed: bool = False) -> str:
    if value is None:
        return "NA"
    try:
        val = float(value) * 100.0
        prefix = "+" if signed and val > 0 else ""
        return f"{prefix}{val:.1f}%"
    except (TypeError, ValueError):
        return esc(value)


def _fmt_num(value: Any) -> str:
    if value is None:
        return "NA"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return esc(value)


def _fmt_age(seconds: Any) -> str:
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "NA"
    if value < 90:
        return f"{value:.0f}s"
    minutes = value / 60.0
    if minutes < 90:
        return f"{minutes:.1f}m"
    hours = minutes / 60.0
    if hours < 48:
        return f"{hours:.1f}h"
    return f"{hours / 24.0:.1f}d"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _num_or_none(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        out = float(value)
        return out if out == out else None
    except (TypeError, ValueError):
        return None


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def esc(value: Any) -> str:
    return escape("" if value is None else str(value))


def _render_briefing(payload: Dict[str, Any], health: Dict[str, Any]) -> str:
    """[T20] First-screen briefing — six questions an operator asks daily:
    overall state / most dangerous asset / why / action / weakest confidence
    link / what needs a human. Layout-additive strip above the KPIs."""
    scores = payload.get("scores") or {}
    ops = payload.get("today_ops") or {}
    spine = payload.get("confidence_spine") or {}
    layers = payload.get("decision_layers") or {}

    worst_sym, worst = "NA", None
    for sym, s in scores.items():
        if worst is None or float(s.get("final_score") or 0) > float(worst.get("final_score") or 0):
            worst_sym, worst = sym, s

    why_bits = []
    if worst:
        valves = worst.get("hard_valve_hits") or []
        if valves:
            why_bits.append("硬阀门 " + ", ".join(str(v) for v in valves))
        movers = []
        for factors in (worst.get("factor_scores") or {}).values():
            for f in factors or []:
                score = float(f.get("score") or 0)
                if score > 0:
                    movers.append((score, str(f.get("explain") or f.get("factor_id") or "")))
        movers.sort(key=lambda m: -m[0])
        why_bits.extend(m[1] for m in movers[:2])
    why_text = " · ".join(why_bits) or "无显著风险因子"

    comps = spine.get("components") or {}
    unwired = set()
    for key in ("fragility", "disagreement"):
        if key in comps and not comps.get(key):
            unwired.add(key)
    comp_text = " · ".join(
        f"{esc(k)} {float(v):.2f}" + ("（未接线）" if k in unwired else "")
        for k, v in comps.items()
    ) or "spine 未导出（旧 payload）"

    manual = []
    if str(spine.get("mode", "")) == "DEGRADED":
        manual.append("置信度 DEGRADED：决策需人工确认")
    for sym, dl in (layers or {}).items():
        hv = (dl or {}).get("hard_valve_state") or {}
        pending = hv.get("pending_ids") or hv.get("pending") or []
        if pending:
            manual.append(f"{esc(sym)} 阀门 PENDING（{', '.join(str(x) for x in pending)}）等次日收盘确认")
    manual_text = "；".join(manual) or "无（advisory only，今日无需人工干预项）"

    statuses = " · ".join(
        f"{esc(sym)} {esc((scores.get(sym) or {}).get('status', 'NA'))}"
        for sym in TRADE_SYMBOLS if sym in scores
    )
    cells = [
        ("今天总体状态", f"health {esc(str((health or {}).get('level', 'NA')))} · {statuses or 'NA'}"),
        ("最危险资产", f"{esc(worst_sym)} score {_fmt_num((worst or {}).get('final_score'))} → {esc((worst or {}).get('status', 'NA'))} 卖 {_fmt_num((worst or {}).get('sell_fraction'))}"),
        ("为什么危险", why_text if why_bits else esc(why_text)),
        ("建议动作", esc(str(ops.get("headline", "见今日操作台")))),
        ("置信度最弱环节", f"{esc(str(spine.get('weakest_link', 'NA')))} · mode {esc(str(spine.get('mode', 'NA')))} · {comp_text}"),
        ("需人工确认", manual_text),
    ]
    cell_html = "".join(
        f"<div style='padding:10px 12px;border:1px solid rgba(255,255,255,0.08);border-radius:10px'>"
        f"<div class='subtle'>{label}</div><div style='margin-top:4px'>{value}</div></div>"
        for label, value in cells
    )
    return f"""
    <section>
      <h2>首屏六问 / Daily Briefing</h2>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px">{cell_html}</div>
    </section>
    """
