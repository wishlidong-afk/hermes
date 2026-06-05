from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


TRADE_SYMBOLS = ["MSTR", "FNGU", "SOXL"]


def render_dashboard(payload: Dict[str, Any], shadow_status: Dict[str, Any] | None = None) -> str:
    """Render the package-engine dashboard using the new payload schema."""
    shadow_status = shadow_status or {}
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
    .subtle {{ color: var(--muted); font-size: 12px; }}
    .hero .subtle {{ color: #cbd5e1; }}
    .controls {{ display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; align-items: center; }}
    button {{
      border: 0;
      border-radius: 6px;
      padding: 8px 12px;
      font-weight: 700;
      cursor: pointer;
      color: white;
      background: var(--slate);
      font-size: 13px;
    }}
    button:disabled {{ opacity: .55; cursor: default; }}
    .btn-primary {{ background: var(--blue); }}
    .btn-position {{ background: #0f766e; }}
    .btn-live {{ background: var(--green); }}
    .btn-muted {{ background: #475569; }}
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
    .kpi, section, .symbol-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .kpi {{ padding: 12px; min-height: 86px; }}
    .kpi .label {{ color: var(--muted); font-size: 12px; margin-bottom: 8px; }}
    .kpi .value {{ font-size: 22px; font-weight: 800; line-height: 1.1; }}
    .kpi .note {{ color: var(--muted); font-size: 12px; margin-top: 6px; }}
    section {{ padding: 14px; margin-bottom: 12px; }}
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
    details {{ border: 1px solid #e5e7eb; border-radius: 6px; background: #fbfdff; }}
    summary {{ cursor: pointer; padding: 9px 10px; font-weight: 800; color: #334155; }}
    details .detail-body {{ padding: 0 10px 10px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 7px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f1f5f9; color: #334155; font-weight: 800; }}
    tr:last-child td {{ border-bottom: 0; }}
    .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
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
      .command-grid {{ grid-template-columns: 1fr; }}
      .two-col {{ grid-template-columns: 1fr; }}
      .ibkr-head {{ grid-template-columns: 1fr; }}
      .macro-summary, .macro-factors {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .flow-grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 720px) {{
      .shell {{ padding: 10px; }}
      .kpis, .facts, .mini-grid, .module-row {{ grid-template-columns: 1fr; }}
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
          {_badge('Data ' + str(data_quality.get('level', 'NA')), _quality_kind(data_quality.get('level')))}
          {_badge('Cache ' + ('hit' if cache.get('hit') else 'live/none'), 'ok' if cache.get('hit') else 'warn')}
          {_badge('IBKR ' + str(ibkr.get('source', 'disabled')), _ibkr_kind(ibkr))}
          {_badge('Regime ' + str(regime.get('current', 'NA')), 'watch')}
        </div>
      </div>
      <div>
        <div class="controls">
          <button class="btn-primary" onclick="refreshScore()" id="refresh-score-btn">更新策略数据</button>
          <button class="btn-position" onclick="refreshPositions()" id="refresh-positions-btn">更新持仓</button>
          <button class="btn-live" onclick="runIbkrLiveCheck()" id="ibkr-live-btn">IBKR Live 验收</button>
          <button class="btn-muted" onclick="location.reload()">重新载入</button>
        </div>
        <div class="subtle" id="refresh-score-status" style="margin-top:8px;text-align:right"></div>
        <div class="subtle" id="refresh-positions-status" style="margin-top:4px;text-align:right"></div>
        <div class="subtle" id="ibkr-live-status" style="margin-top:4px;text-align:right"></div>
      </div>
    </header>

    <div id="ibkr-live-result" class="toolbar-output"></div>

    {_render_kpis(payload)}

    {_render_macro_section(payload)}

    <section>
      <h2>Escape Decisions / 今日处置指令</h2>
      <div class="command-grid">
        {''.join(_render_symbol_card(symbol, payload) for symbol in TRADE_SYMBOLS)}
      </div>
      {_render_component_flow_section(payload)}
    </section>

    <div class="two-col">
      {_render_ibkr_section(ibkr)}
      {_render_posterior_section(payload)}
    </div>

    <div class="two-col">
      {_render_mirror_section(payload)}
      {_render_quality_section(payload)}
    </div>

    {_render_ops_panel(shadow_status)}
  </div>
  {_render_scripts(as_of)}
</body>
</html>
"""


def write_dashboard(payload: Dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_dashboard(payload), encoding="utf-8")
    return output_path


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
        <div class="label">数据质量</div>
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
            f"<td>{esc(row.get('explain'))}</td>"
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
            f"<div class='subtle'>{esc(row.get('explain'))}</div>"
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
    cards = []
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
        cards.append(_render_flow_card(symbol, components, summary))
    return f"""
      <div class="flow-header">
        <div>
          <h2 style="margin-bottom:4px">底层持仓资金流入/流出监控</h2>
          <div class="subtle">CMF20 / MFI14 / A-D slope / 5日估算净流。红色代表资金异常流出或弱流出。db={esc(flow.get('db_path', '未固化'))}</div>
        </div>
        {_badge('flow as_of ' + esc(flow.get('as_of', 'NA')), 'watch')}
      </div>
      <div class="flow-grid">{''.join(cards)}</div>
    """


def _render_flow_card(symbol: str, components: List[Dict[str, Any]], summary: str) -> str:
    severity_rank = {"SEVERE": 0, "ABNORMAL": 1, "WATCH": 2, "NORMAL": 3, "MISSING": 4}
    rows = []
    for row in sorted(components, key=lambda item: (severity_rank.get(str(item.get("severity", "MISSING")), 5), str(item.get("symbol", ""))))[:12]:
        sev = str(row.get("severity", "MISSING"))
        signed = _float(row.get("legacy_signed_5d"), 0.0)
        money_class = "pos" if signed >= 0 else "neg"
        rows.append(
            "<tr>"
            f"<td><b>{esc(row.get('symbol'))}</b></td>"
            f"<td>{_badge(sev, _flow_kind(sev))}</td>"
            f"<td>{_fmt_num(row.get('cmf20'))}</td>"
            f"<td>{_fmt_num(row.get('mfi14'))}</td>"
            f"<td class='flow-money {money_class}'>{_fmt_flow_money(row.get('legacy_signed_5d'))}</td>"
            f"<td>{esc(row.get('outflow_days_5d', 'NA'))}</td>"
            "</tr>"
        )
    return f"""
    <div class="flow-card">
      <div class="flow-title">
        <h3 style="margin-bottom:4px">{esc(symbol)} 资金流</h3>
        <div class="subtle">{summary}</div>
      </div>
      <div class="flow-body">
        <table>
          <thead><tr><th>持仓</th><th>状态</th><th>CMF20</th><th>MFI14</th><th>5日净流</th><th>流出天</th></tr></thead>
          <tbody>{''.join(rows) if rows else '<tr><td colspan="6">暂无资金流数据</td></tr>'}</tbody>
        </table>
      </div>
    </div>
    """


def _render_symbol_card(symbol: str, payload: Dict[str, Any]) -> str:
    score = (payload.get("scores") or {}).get(symbol, {})
    sizing = (payload.get("sizing") or {}).get(symbol, {})
    routing = (payload.get("routing") or {}).get(symbol, {})
    reentry = (payload.get("reentry") or {}).get(symbol, {})
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

          <div class="facts">
            {_metric('建议处置', f"{status} / 卖出 {_fmt_pct(sell_fraction)}")}
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
                </tbody>
              </table>
            </div>
          </div>

          <details>
            <summary>裁决原因和关键触发项</summary>
            <div class="detail-body">
              {_hard_valves(hard)}
              <table>
                <thead><tr><th>模块</th><th>指标</th><th>得分</th><th>解释</th></tr></thead>
                <tbody>{''.join(top_reasons) or '<tr><td colspan="4">暂无高分触发项</td></tr>'}</tbody>
              </table>
            </div>
          </details>
        </div>
      </article>
    """


def _render_ibkr_section(ibkr: Dict[str, Any]) -> str:
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
    return f"""
    <section>
      <div class="ibkr-head">
        <div>
          <h2>IBKR Reconciliation / 持仓对账</h2>
          <div class="subtle">source={esc(ibkr.get('source', 'disabled'))} · account={esc(ibkr.get('account_id', 'NA'))} · sync={esc(str(ibkr.get('sync_time', ''))[:19])} · age={esc(age)} {stale_badge}</div>
        </div>
        <div class="ibkr-total-box">
          <div class="label">IBKR 现有总资产 / NetLiq</div>
          <div class="amount">{_fmt_money(ibkr.get('net_liq'))}</div>
          <div class="note">source={esc(ibkr.get('source', 'disabled'))} · age={esc(age)} · max delta {_fmt_pct(ibkr.get('max_abs_delta'))}</div>
        </div>
      </div>
      {_warning(ibkr.get('error'))}
      <table>
        <thead><tr><th>类别</th><th>标的</th><th>理想</th><th>实际</th><th>差异</th><th>市值</th><th>股数</th><th>成本</th><th>状态</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </section>
    """


def _render_posterior_section(payload: Dict[str, Any]) -> str:
    posterior = payload.get("posterior_pnl") or {}
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
    return f"""
    <section>
      <h2>Posterior Ideal P/L / 理想仓位上一交易日盈亏</h2>
      <div class="subtle">portfolio value={_fmt_money(posterior.get('portfolio_value'))}</div>
      <table>
        <thead><tr><th>系统</th><th>仓位桶</th><th>标的</th><th>权重</th><th>金额</th><th>股数</th><th>浮盈亏</th><th>收益</th></tr></thead>
        <tbody>{''.join(rows) if rows else '<tr><td colspan="8">暂无后验盈亏数据</td></tr>'}</tbody>
      </table>
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


def _render_quality_section(payload: Dict[str, Any]) -> str:
    dq = payload.get("data_quality") or {}
    penalties = dq.get("penalties") or []
    rows = [
        f"<tr><td>{esc(p.get('reason'))}</td><td>{esc(p.get('field'))}</td><td>{_fmt_num(p.get('penalty'))}</td></tr>"
        for p in penalties[:8]
    ]
    return f"""
    <section>
      <h2>Audit Detail / 数据质量</h2>
      <div class="facts" style="margin-bottom:10px">
        {_metric('Completeness', _fmt_num(dq.get('completeness_score')))}
        {_metric('Quality', _fmt_num(dq.get('quality_score')))}
        {_metric('Latency', _fmt_num(dq.get('latency_score')))}
      </div>
      <table>
        <thead><tr><th>类型</th><th>字段</th><th>惩罚</th></tr></thead>
        <tbody>{''.join(rows) if rows else '<tr><td colspan="3">暂无数据质量惩罚</td></tr>'}</tbody>
      </table>
    </section>
    """


def _render_ops_panel(shadow_status: Dict[str, Any]) -> str:
    mode = shadow_status.get("run_daily_mode", "unknown")
    latest = shadow_status.get("latest_baseline_date") or ""
    dates = ", ".join((shadow_status.get("available_dates") or [])[:8])
    return f"""
    <section class="ops">
      <details>
        <summary>M4 迁移控制台 / 运维工具</summary>
        <div class="detail-body">
          <div class="facts" style="margin-bottom:10px">
            {_metric('run_daily mode', esc(mode))}
            {_metric('最新基准日', esc(latest or 'NA'))}
            {_metric('可对比日期', esc(dates or 'NA'))}
          </div>
          <div class="controls" style="justify-content:flex-start;margin-bottom:10px">
            <input id="shadow-date" type="date" value="{esc(latest)}" style="border:1px solid #cbd5e1;border-radius:6px;padding:7px 9px">
            <button class="btn-muted" onclick="runShadow()">运行影子对比</button>
            <button class="btn-muted" onclick="runBackfill()">补基准并对比</button>
          </div>
          <div id="shadow-status" class="subtle"></div>
          <div id="shadow-result" class="toolbar-output"></div>
        </div>
      </details>
    </section>
    """


def _render_scripts(as_of: str) -> str:
    as_of_js = json.dumps(str(as_of or ""))
    return f"""
  <script>
  function setBusy(btn, busy) {{
    if (!btn) return;
    btn.disabled = busy;
    btn.style.opacity = busy ? '0.6' : '1';
  }}
  window.refreshScore = function() {{
    var btn = document.getElementById('refresh-score-btn');
    var st = document.getElementById('refresh-score-status');
    setBusy(btn, true);
    st.textContent = '正在刷新新系统数据...';
    fetch('/api/refresh_score', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{as_of: 'latest', refresh_history: true}})
    }}).then(function(r) {{ return r.json(); }}).then(function(d) {{
      if (d && d.scores) {{
        st.textContent = '刷新完成，载入 ' + (d.as_of || 'latest');
        setTimeout(function() {{ location.href = '/?as_of=' + encodeURIComponent(d.as_of || 'latest'); }}, 600);
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
    st.textContent = '正在拉取 IBKR 持仓...';
    fetch('/api/refresh_positions', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{as_of: 'latest', refresh_history: true}})
    }}).then(function(r) {{ return r.json(); }}).then(function(d) {{
      var ibkr = d.ibkr || {{}};
      if (ibkr.source) {{
        st.textContent = '持仓刷新完成: ' + ibkr.source + ' · NetLiq ' + (ibkr.net_liq || 'NA');
        setTimeout(function() {{ location.href = '/?as_of=' + encodeURIComponent(d.as_of || 'latest'); }}, 600);
      }} else {{
        st.textContent = '持仓刷新失败: ' + (d.message || d.error || 'unknown');
        setBusy(btn, false);
      }}
    }}).catch(function(e) {{
      st.textContent = '持仓刷新失败: ' + e;
      setBusy(btn, false);
    }});
  }};
  window.runIbkrLiveCheck = function() {{
    var btn = document.getElementById('ibkr-live-btn');
    var st = document.getElementById('ibkr-live-status');
    var out = document.getElementById('ibkr-live-result');
    setBusy(btn, true);
    st.textContent = '正在验收 IBKR live 连接...';
    out.style.display = 'none';
    fetch('/api/ibkr_live_check', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{as_of: {as_of_js}}})
    }}).then(function(r) {{ return r.json(); }}).then(function(d) {{
      setBusy(btn, false);
      st.textContent = d.ok ? 'LIVE_OK' : (d.status || 'LIVE_FAILED');
      var lines = [];
      lines.push('status=' + (d.status || 'unknown'));
      lines.push('ok=' + !!d.ok);
      if (d.preflight) {{
        lines.push('source=' + d.preflight.source);
        lines.push('account=' + d.preflight.account_id);
        lines.push('net_liq=' + d.preflight.net_liq);
        if (d.preflight.error) lines.push('error=' + d.preflight.error);
      }}
      if (d.ibkr) {{
        lines.push('score_ibkr_source=' + d.ibkr.source);
        lines.push('max_abs_delta=' + d.ibkr.max_abs_delta);
      }}
      if (d.report_paths) {{
        lines.push('json_report=' + d.report_paths.json);
        lines.push('markdown_report=' + d.report_paths.markdown);
      }}
      if (d.message) lines.push('message=' + d.message);
      out.textContent = lines.join('\\n');
      out.style.display = 'block';
      if (d.ok) setTimeout(function() {{ location.reload(); }}, 900);
    }}).catch(function(e) {{
      setBusy(btn, false);
      st.textContent = 'Live 验收失败: ' + e;
    }});
  }};
  function m4Run(endpoint, label) {{
    var date = document.getElementById('shadow-date').value || {as_of_js};
    var st = document.getElementById('shadow-status');
    var out = document.getElementById('shadow-result');
    st.textContent = '正在运行 ' + label + '...';
    out.style.display = 'none';
    fetch(endpoint, {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{as_of: date}})
    }}).then(function(r) {{ return r.json(); }}).then(function(d) {{
      st.textContent = d.ok ? '完成' : '失败';
      out.textContent = JSON.stringify(d, null, 2);
      out.style.display = 'block';
    }}).catch(function(e) {{
      st.textContent = '失败: ' + e;
    }});
  }}
  window.runShadow = function() {{ m4Run('/api/m4_shadow', '影子对比'); }};
  window.runBackfill = function() {{ m4Run('/api/m4_backfill', '补基准并对比'); }};
  </script>
    """


def _top_factor_rows(score: Dict[str, Any], limit: int = 5) -> List[str]:
    factors = []
    for module, rows in (score.get("factor_scores") or {}).items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            pts = _float(row.get("score"), 0.0)
            if pts > 0:
                factors.append((pts, module, row))
    factors.sort(key=lambda x: x[0], reverse=True)
    out = []
    for pts, module, row in factors[:limit]:
        max_score = row.get("max_score")
        score_text = f"{_fmt_num(pts)}/{_fmt_num(max_score)}" if max_score is not None else _fmt_num(pts)
        out.append(
            "<tr>"
            f"<td>{esc(module)}</td>"
            f"<td>{esc(row.get('factor_id', row.get('name', '')))}</td>"
            f"<td>{score_text}</td>"
            f"<td>{esc(row.get('explain', ''))}</td>"
            "</tr>"
        )
    return out


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


def esc(value: Any) -> str:
    return escape("" if value is None else str(value))
