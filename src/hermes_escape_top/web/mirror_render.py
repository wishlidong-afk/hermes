from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List

from .render import (
    _badge,
    _flow_kind,
    _fmt_age,
    _fmt_flow_money,
    _fmt_money,
    _fmt_num,
    _fmt_pct,
    _ibkr_kind,
    _quality_kind,
    _snap,
    esc,
)


MIRROR_ORDER = ["MSTR_QQQ", "FNGU_QQQ", "SOXL_SOXX"]
MIRROR_LABELS = {
    "MSTR_QQQ": "MSTR / QQQ 趋势切换",
    "FNGU_QQQ": "QQQ / FNGU 双轮驱动",
    "SOXL_SOXX": "SOXX / SOXL 半导体",
}
RADAR_SYMBOLS = {
    "MSTR_QQQ": ["MSTR", "BTC-USD", "QQQ", "^VIX"],
    "FNGU_QQQ": ["QQQ", "FNGU", "^VIX"],
    "SOXL_SOXX": ["SOXX", "SOXL", "SPY", "^VIX"],
}


def render_mirror_dashboard(payload: Dict[str, Any]) -> str:
    as_of = str(payload.get("as_of", ""))
    schema = str(payload.get("schema_version", ""))
    dq = payload.get("data_quality") or {}
    ibkr = payload.get("ibkr") or {}
    regime = payload.get("regime") or {}
    posterior = payload.get("posterior_pnl") or {}
    portfolio_base = _portfolio_base(payload)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hermes 镜像参考</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --panel: #ffffff;
      --line: #d9dee7;
      --text: #111827;
      --muted: #5f6b7a;
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
      font-weight: 800;
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
    .btn-escape {{ background: #7c3aed; }}
    .status-line {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
      background: #e5e7eb;
      color: #374151;
    }}
    .badge.ok {{ background: #d1fae5; color: #065f46; }}
    .badge.warn {{ background: #fef3c7; color: #92400e; }}
    .badge.danger {{ background: #fee2e2; color: #991b1b; }}
    .badge.watch {{ background: #dbeafe; color: #1e40af; }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin: 12px 0;
    }}
    .kpi, section, .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .kpi {{ padding: 12px; min-height: 86px; }}
    .kpi .label, .metric .label {{ color: var(--muted); font-size: 12px; margin-bottom: 7px; }}
    .kpi .value {{ font-size: 22px; font-weight: 900; line-height: 1.1; overflow-wrap: anywhere; }}
    .kpi .note {{ color: var(--muted); font-size: 12px; margin-top: 6px; }}
    section {{ padding: 14px; margin-bottom: 12px; }}
    .mirror-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-bottom: 12px; }}
    .card {{ overflow: hidden; }}
    .card-head {{
      padding: 14px;
      border-bottom: 1px solid var(--line);
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: start;
      background: #fbfdff;
    }}
    .card-title {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
    .card-title strong {{ font-size: 19px; }}
    .selected {{ text-align: right; font-size: 26px; font-weight: 900; line-height: 1; }}
    .selected small {{ display:block; color: var(--muted); font-size: 11px; margin-top: 4px; font-weight: 700; }}
    .card-body {{ padding: 14px; display: grid; gap: 12px; }}
    .facts {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
    .metric {{ background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 6px; padding: 9px; min-width: 0; }}
    .metric .value {{ font-size: 15px; font-weight: 850; overflow-wrap: anywhere; }}
    .route {{ font-weight: 900; }}
    .reason {{ color: var(--muted); font-size: 12px; line-height: 1.45; }}
    .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .flow-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    .flow-card {{ border: 1px solid #e5e7eb; border-radius: 8px; background: #fbfdff; overflow: hidden; }}
    .flow-title {{ padding: 10px 12px; border-bottom: 1px solid #e5e7eb; background: #f8fafc; }}
    .flow-body {{ padding: 10px; overflow-x: auto; }}
    .flow-money.pos {{ color: #047857; font-weight: 850; }}
    .flow-money.neg {{ color: #b91c1c; font-weight: 850; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 7px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f1f5f9; color: #334155; font-weight: 850; }}
    tr:last-child td {{ border-bottom: 0; }}
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
    .warning-box {{ background:#fff7ed; border:1px solid #fed7aa; border-radius:6px; padding:10px; color:#7c2d12; font-size:12px; }}
    details {{ border: 1px solid #e5e7eb; border-radius: 6px; background: #fbfdff; }}
    summary {{ cursor: pointer; padding: 9px 10px; font-weight: 850; color: #334155; }}
    .detail-body {{ padding: 0 10px 10px; }}
    ul {{ margin: 0; padding-left: 18px; color: #334155; font-size: 12px; line-height: 1.6; }}
    @media (max-width: 1100px) {{
      .hero {{ grid-template-columns: 1fr; }}
      .controls {{ justify-content: flex-start; }}
      .kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .mirror-grid, .two-col, .flow-grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 720px) {{
      .shell {{ padding: 10px; }}
      .kpis, .facts {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 22px; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <header class="hero">
      <div>
        <h1>Hermes 镜像参考</h1>
        <div class="subtle">as_of={esc(as_of)} · schema={esc(schema)} · 独立端口 8768</div>
        <div class="status-line">
          {_badge('Data ' + str(dq.get('level', 'NA')), _quality_kind(dq.get('level')))}
          {_badge('IBKR ' + str(ibkr.get('source', 'disabled')), _ibkr_kind(ibkr))}
          {_badge('Regime ' + str(regime.get('current', 'NA')), 'watch')}
          {_badge('Mirror target ' + _fmt_pct(_mirror_cap(payload)), 'ok')}
        </div>
      </div>
      <div>
        <div class="controls">
          <a class="button btn-escape" href="http://localhost:8766/">切换逃顶 8766</a>
          <button class="btn-primary" onclick="refreshScore()" id="refresh-score-btn">更新镜像数据</button>
          <button class="btn-position" onclick="refreshPositions()" id="refresh-positions-btn">更新持仓</button>
          <button class="btn-muted" onclick="location.reload()">重新载入</button>
        </div>
        <div class="subtle" id="refresh-score-status" style="margin-top:8px;text-align:right"></div>
        <div class="subtle" id="refresh-positions-status" style="margin-top:4px;text-align:right"></div>
      </div>
    </header>

    <div id="refresh-result" class="toolbar-output"></div>

    <div class="kpis">
      <div class="kpi">
        <div class="label">IBKR 总资产 / NetLiq</div>
        <div class="value">{_fmt_money(ibkr.get('net_liq'))}</div>
        <div class="note">source={esc(ibkr.get('source', 'disabled'))} · sync={esc(str(ibkr.get('sync_time', ''))[:19])}</div>
      </div>
      <div class="kpi">
        <div class="label">镜像计算基准</div>
        <div class="value">{_fmt_money(portfolio_base)}</div>
        <div class="note">优先用 IBKR NetLiq，否则用后验组合值</div>
      </div>
      <div class="kpi">
        <div class="label">镜像策略总目标仓位</div>
        <div class="value">{_fmt_pct(_mirror_cap(payload))}</div>
        <div class="note">FNGU/QQQ 桶 20% · SOXL/SOXX 桶 30%</div>
      </div>
      <div class="kpi">
        <div class="label">上一交易日理想 P/L</div>
        <div class="value">{_fmt_money(_mirror_total_pnl(posterior))}</div>
        <div class="note">按当前镜像理想仓位测算</div>
      </div>
    </div>

    <section>
      <h2>周期判断与推荐处置</h2>
      <div class="mirror-grid">
        {''.join(_render_leg_card(key, payload, portfolio_base) for key in MIRROR_ORDER)}
      </div>
    </section>

    <div class="two-col">
      {_render_ibkr_positions(payload)}
      {_render_ideal_allocations(payload, portfolio_base)}
    </div>

    <div class="two-col">
      {_render_posterior(payload)}
      {_render_regime_table(payload)}
    </div>

    {_render_flow(payload)}
  </div>
  {_render_scripts(as_of)}
</body>
</html>
"""


def write_mirror_dashboard(payload: Dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_mirror_dashboard(payload), encoding="utf-8")
    return output_path


def _render_leg_card(sleeve: str, payload: Dict[str, Any], portfolio_base: float) -> str:
    decision = ((payload.get("mirror") or {}).get("decisions") or {}).get(sleeve, {})
    pnl = ((payload.get("posterior_pnl") or {}).get("mirror") or {}).get(sleeve, {})
    selected = str(decision.get("selected_symbol", pnl.get("symbol", "NA")))
    target_weight = _float(decision.get("target_weight"), _float(pnl.get("target_weight"), 0.0))
    target_amount = portfolio_base * target_weight
    cycle = str(decision.get("cycle", "NA"))
    kind = "ok" if cycle in {"STRONG_TREND", "STRONG_BOOM"} else "watch" if cycle in {"WEAK_TREND", "WEAK_BOOM"} else "warn"
    return f"""
    <article class="card">
      <div class="card-head">
        <div>
          <div class="card-title">
            <strong>{esc(MIRROR_LABELS.get(sleeve, sleeve))}</strong>
            {_badge(cycle, kind)}
          </div>
          <div class="subtle">上限 {_fmt_pct(decision.get('sleeve_cap'))} · 风险腿 {esc(decision.get('risk_symbol', 'NA'))} · 防守腿 {esc(decision.get('base_symbol', 'NA'))}</div>
        </div>
        <div class="selected">{esc(selected)}<small>主动作</small></div>
      </div>
      <div class="card-body">
        <div class="facts">
          {_metric('建议动作', _action_text(decision))}
          {_metric('理想总资金', f"{_fmt_pct(target_weight)} · {_fmt_money(target_amount)}")}
          {_metric('策略桶上限', _fmt_pct(decision.get('sleeve_cap')))}
          {_metric('昨日理想盈亏', f"{_fmt_money(pnl.get('pnl'))} · {_fmt_pct(pnl.get('return_pct'))}")}
        </div>
        <div class="reason">{esc(decision.get('reason', '暂无原因'))}</div>
        {_render_allocation_table(decision, payload, portfolio_base)}
        {_render_radar_table(sleeve, payload)}
        {_render_rule_checks(decision)}
        {_render_stop_rules(decision)}
      </div>
    </article>
    """


def _render_radar_table(sleeve: str, payload: Dict[str, Any]) -> str:
    rows = []
    for symbol in RADAR_SYMBOLS.get(sleeve, []):
        rows.append(
            "<tr>"
            f"<td><b>{esc(symbol)}</b></td>"
            f"<td>{_fmt_money(_snap(payload, symbol, 'close'))}</td>"
            f"<td>{_fmt_money(_snap(payload, symbol, 'ema20'))}</td>"
            f"<td>{_fmt_money(_snap(payload, symbol, 'ma200'))}</td>"
            f"<td>{_fmt_money(_snap(payload, symbol, 'ma220'))}</td>"
            f"<td>{_fmt_pct(_snap(payload, symbol, 'drawdown_60d_high_pct'))}</td>"
            "</tr>"
        )
    return f"""
      <table>
        <thead><tr><th>雷达</th><th>收盘</th><th>EMA20</th><th>MA200</th><th>MA220</th><th>60日回撤</th></tr></thead>
        <tbody>{''.join(rows) if rows else '<tr><td colspan="6">暂无雷达数据</td></tr>'}</tbody>
      </table>
    """


def _render_allocation_table(decision: Dict[str, Any], payload: Dict[str, Any], portfolio_base: float) -> str:
    rows = []
    allocations = decision.get("allocations") or {}
    for symbol, weight in sorted(allocations.items(), key=lambda item: item[0]):
        amount = portfolio_base * _float(weight, 0.0)
        price = _price_for(payload, symbol, {})
        shares = amount / price if price > 0 else None
        rows.append(
            "<tr>"
            f"<td><b>{esc(symbol)}</b></td>"
            f"<td>{_fmt_pct(weight)}</td>"
            f"<td>{_fmt_money(amount)}</td>"
            f"<td>{_fmt_money(price)}</td>"
            f"<td>{_fmt_num(shares)}</td>"
            "</tr>"
        )
    return f"""
      <table>
        <thead><tr><th>目标标的</th><th>全盘比例</th><th>目标金额</th><th>参考价</th><th>建议股数</th></tr></thead>
        <tbody>{''.join(rows) if rows else '<tr><td colspan="5">暂无分配建议</td></tr>'}</tbody>
      </table>
    """


def _render_rule_checks(decision: Dict[str, Any]) -> str:
    checks = decision.get("rule_checks") or {}
    if not checks:
        return ""
    rows = []
    for name, passed in checks.items():
        rows.append(
            "<tr>"
            f"<td>{esc(name)}</td>"
            f"<td>{_rule_badge(passed)}</td>"
            "</tr>"
        )
    return f"""
      <details open>
        <summary>规则检查</summary>
        <div class="flow-body">
          <table>
            <thead><tr><th>条件</th><th>状态</th></tr></thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        </div>
      </details>
    """


def _render_stop_rules(decision: Dict[str, Any]) -> str:
    rules = decision.get("stop_rules") or []
    if not rules:
        return ""
    rows = "".join(f"<li>{esc(rule)}</li>" for rule in rules)
    return f"""
      <details>
        <summary>止损止盈与禁令</summary>
        <div class="detail-body">
          <ul>{rows}</ul>
        </div>
      </details>
    """


def _render_ibkr_positions(payload: Dict[str, Any]) -> str:
    ibkr = payload.get("ibkr") or {}
    history = payload.get("ibkr_history") or []
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
                f"<td>{_fmt_num(item.get('actual_shares'))}</td>"
                f"<td>{_fmt_money(item.get('actual_notional'))}</td>"
                f"<td>{_fmt_pct(item.get('actual_weight'))}</td>"
                f"<td>{_fmt_money(item.get('avg_cost'))}</td>"
                f"<td>{esc(item.get('status', 'NA'))}</td>"
                "</tr>"
            )
    if not rows:
        rows.append(f"<tr><td colspan='7'>{esc(ibkr.get('note') or ibkr.get('error') or '暂无 IBKR 持仓数据')}</td></tr>")
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
    <section>
      <h2>IBKR 持仓</h2>
      <div class="subtle">account={esc(ibkr.get('account_id', 'NA'))} · source={esc(ibkr.get('source', 'disabled'))} · clientId={esc(ibkr.get('client_id', 'NA'))} · NetLiq={_fmt_money(ibkr.get('net_liq'))} · sync={esc(str(ibkr.get('sync_time', ''))[:19])} · age={esc(age)} {stale_badge}</div>
      {_warning(ibkr.get('error'))}
      <table>
        <thead><tr><th>类别</th><th>标的</th><th>股数</th><th>市值</th><th>占比</th><th>成本</th><th>状态</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
      <details style="margin-top:10px">
        <summary>最近 IBKR 快照</summary>
        <div class="detail-body">
          <table>
            <thead><tr><th>ID</th><th>来源</th><th>同步时间</th><th>NetLiq</th><th>Stale</th><th>clientId</th></tr></thead>
            <tbody>{''.join(history_rows) if history_rows else '<tr><td colspan="6">暂无历史快照</td></tr>'}</tbody>
          </table>
        </div>
      </details>
    </section>
    """


def _render_ideal_allocations(payload: Dict[str, Any], portfolio_base: float) -> str:
    rows = []
    for sleeve in MIRROR_ORDER:
        decision = ((payload.get("mirror") or {}).get("decisions") or {}).get(sleeve, {})
        allocations = decision.get("allocations") or {}
        for symbol, weight in sorted(allocations.items()):
            amount = portfolio_base * _float(weight, 0.0)
            price = _price_for(payload, symbol, {})
            shares = amount / price if price > 0 else None
            rows.append(
                "<tr>"
                f"<td><b>{esc(MIRROR_LABELS.get(sleeve, sleeve))}</b></td>"
                f"<td>{esc(symbol)}</td>"
                f"<td>{_fmt_pct(weight)}</td>"
                f"<td>{_fmt_money(amount)}</td>"
                f"<td>{_fmt_money(price)}</td>"
                f"<td>{_fmt_num(shares)}</td>"
                "</tr>"
            )
    remaining = max(0.0, 1.0 - _mirror_cap(payload))
    rows.append(
        "<tr>"
        "<td><b>非镜像/现金/原组合预留</b></td>"
        "<td>保留</td>"
        f"<td>{_fmt_pct(remaining)}</td>"
        f"<td>{_fmt_money(portfolio_base * remaining)}</td>"
        "<td>-</td><td>-</td>"
        "</tr>"
    )
    return f"""
    <section>
      <h2>理想化持仓配比</h2>
      <div class="subtle">按当前 IBKR NetLiq 或后验组合值实时换算；股数按当前收盘价估算。</div>
      <table>
        <thead><tr><th>策略桶</th><th>目标标的</th><th>比例</th><th>目标金额</th><th>参考价</th><th>建议股数</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </section>
    """


def _render_posterior(payload: Dict[str, Any]) -> str:
    rows = []
    posterior = (payload.get("posterior_pnl") or {}).get("mirror") or {}
    for sleeve in MIRROR_ORDER:
        row = posterior.get(sleeve, {})
        rows.append(
            "<tr>"
            f"<td><b>{esc(MIRROR_LABELS.get(sleeve, sleeve))}</b></td>"
            f"<td>{esc(row.get('symbol', 'NA'))}</td>"
            f"<td>{_fmt_pct(row.get('target_weight'))}</td>"
            f"<td>{_fmt_money(row.get('previous_close'))}</td>"
            f"<td>{_fmt_money(row.get('current_close'))}</td>"
            f"<td>{_fmt_money(row.get('pnl'))}</td>"
            f"<td>{_fmt_pct(row.get('return_pct'))}</td>"
            "</tr>"
        )
    history_rows = []
    for row in payload.get("calibration_history") or []:
        if row.get("system") != "mirror":
            continue
        history_rows.append(
            "<tr>"
            f"<td>{esc(row.get('as_of'))}</td>"
            f"<td>{esc(row.get('sleeve'))}</td>"
            f"<td>{esc(row.get('symbol'))}</td>"
            f"<td>{_fmt_money(row.get('notional'))}</td>"
            f"<td>{_fmt_money(row.get('pnl'))}</td>"
            f"<td>{_fmt_pct(row.get('return_pct'))}</td>"
            "</tr>"
        )
    return f"""
    <section>
      <h2>模型校准 / 上一交易日理想 P/L</h2>
      <table>
        <thead><tr><th>策略桶</th><th>标的</th><th>权重</th><th>昨收</th><th>今收</th><th>浮盈亏</th><th>收益</th></tr></thead>
        <tbody>{''.join(rows) if rows else '<tr><td colspan="7">暂无校准数据</td></tr>'}</tbody>
      </table>
      <details style="margin-top:10px">
        <summary>最近镜像校准记录</summary>
        <div class="detail-body">
          <table>
            <thead><tr><th>日期</th><th>桶</th><th>标的</th><th>金额</th><th>上一交易日盈亏</th><th>收益</th></tr></thead>
            <tbody>{''.join(history_rows[:8]) if history_rows else '<tr><td colspan="6">暂无历史校准记录</td></tr>'}</tbody>
          </table>
        </div>
      </details>
    </section>
    """


def _render_regime_table(payload: Dict[str, Any]) -> str:
    regime = payload.get("regime") or {}
    inputs = regime.get("inputs") or {}
    rows = [
        ("市场状态", regime.get("current", "NA"), "新系统 MarketContext 输出"),
        ("VIX 分位", _fmt_num(regime.get("vix_percentile")), "波动率环境"),
        ("QQQ 收盘", _fmt_money(inputs.get("QQQ.close")), "科技主雷达"),
        ("QQQ MA200", _fmt_money(inputs.get("QQQ.ma200")), "大趋势红线"),
        ("组合风险", _fmt_pct((payload.get("portfolio_risk") or {}).get("forecast_portfolio_vol")), "风险预算"),
    ]
    return f"""
    <section>
      <h2>市场环境</h2>
      <table>
        <thead><tr><th>项目</th><th>读数</th><th>说明</th></tr></thead>
        <tbody>{''.join(f'<tr><td>{esc(a)}</td><td><b>{b}</b></td><td class="subtle">{esc(c)}</td></tr>' for a, b, c in rows)}</tbody>
      </table>
    </section>
    """


def _render_flow(payload: Dict[str, Any]) -> str:
    flow = payload.get("flow") or {}
    baskets = flow.get("component_baskets") or {}
    cards = []
    for symbol in ["FNGU", "SOXL"]:
        basket = baskets.get(symbol) or {}
        components = basket.get("components") or []
        summary = (
            f"severity={esc(basket.get('severity', 'NA'))} · "
            f"avg CMF {_fmt_num(basket.get('avg_cmf20'))} · "
            f"avg MFI {_fmt_num(basket.get('avg_mfi14'))} · "
            f"abnormal {esc(basket.get('abnormal_components', 0))}/{esc(basket.get('component_count', 0))}"
        )
        cards.append(_flow_card(symbol, components, summary))
    return f"""
    <section>
      <h2>主要持仓资金流入/流出</h2>
      <div class="subtle" style="margin-bottom:10px">资金流用于辅助判断镜像腿是否有内部派发压力；红色代表异常流出或弱流出。db={esc(flow.get('db_path', '未固化'))}</div>
      <div class="flow-grid">{''.join(cards)}</div>
    </section>
    """


def _flow_card(symbol: str, components: List[Dict[str, Any]], summary: str) -> str:
    rows = []
    for row in components[:10]:
        signed = _float(row.get("legacy_signed_5d"), 0.0)
        money_class = "pos" if signed >= 0 else "neg"
        severity = str(row.get("severity", "MISSING"))
        rows.append(
            "<tr>"
            f"<td><b>{esc(row.get('symbol'))}</b></td>"
            f"<td>{_badge(severity, _flow_kind(severity))}</td>"
            f"<td>{_fmt_num(row.get('cmf20'))}</td>"
            f"<td>{_fmt_num(row.get('mfi14'))}</td>"
            f"<td class='flow-money {money_class}'>{_fmt_flow_money(row.get('legacy_signed_5d'))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='5'>暂无资金流数据</td></tr>")
    return f"""
    <div class="flow-card">
      <div class="flow-title">
        <h3 style="margin-bottom:4px">{esc(symbol)}</h3>
        <div class="subtle">{summary}</div>
      </div>
      <div class="flow-body">
        <table>
          <thead><tr><th>持仓</th><th>状态</th><th>CMF20</th><th>MFI14</th><th>5日净流</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    </div>
    """


def _render_scripts(as_of: str) -> str:
    return f"""
  <script>
  function setBusy(btn, busy) {{
    if (!btn) return;
    btn.disabled = busy;
    btn.style.opacity = busy ? '0.6' : '1';
  }}
  function showResult(text) {{
    var out = document.getElementById('refresh-result');
    if (!out) return;
    out.textContent = text;
    out.style.display = 'block';
  }}
  function rememberRefresh(statusId, text, resultText) {{
    try {{
      sessionStorage.setItem('hermesMirrorLastRefresh', JSON.stringify({{statusId: statusId, text: text, resultText: resultText || text}}));
    }} catch (e) {{}}
  }}
  function restoreRefreshStatus() {{
    try {{
      var raw = sessionStorage.getItem('hermesMirrorLastRefresh');
      if (!raw) return;
      sessionStorage.removeItem('hermesMirrorLastRefresh');
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
    st.textContent = '正在刷新镜像策略数据...';
    fetch('/api/refresh_score', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{as_of: 'latest', refresh_history: true}})
    }}).then(function(r) {{ return r.json(); }}).then(function(d) {{
      if (d && d.mirror) {{
        var msg = '镜像数据刷新完成，载入 ' + (d.as_of || 'latest');
        var detail = 'mirror refreshed: ' + JSON.stringify(d.mirror.decisions || {{}}, null, 2);
        st.textContent = msg;
        showResult(detail);
        rememberRefresh('refresh-score-status', msg, detail);
        setTimeout(function() {{ location.href = '/?as_of=' + encodeURIComponent(d.as_of || 'latest'); }}, 700);
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
    st.textContent = '正在同步 IBKR 持仓...';
    fetch('/api/refresh_positions', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{as_of: 'latest', refresh_history: true}})
    }}).then(function(r) {{ return r.json(); }}).then(function(d) {{
      var ibkr = d.ibkr || {{}};
      if (ibkr.source) {{
        var msg = '持仓刷新完成: ' + ibkr.source + ' · NetLiq ' + (ibkr.net_liq || 'NA');
        var detail = 'ibkr refreshed: source=' + ibkr.source + '\\nnet_liq=' + ibkr.net_liq;
        st.textContent = msg;
        showResult(detail);
        rememberRefresh('refresh-positions-status', msg, detail);
        setTimeout(function() {{ location.href = '/?as_of=' + encodeURIComponent(d.as_of || 'latest'); }}, 700);
      }} else {{
        st.textContent = '持仓刷新失败: ' + (d.message || d.error || 'unknown');
        setBusy(btn, false);
      }}
    }}).catch(function(e) {{
      st.textContent = '持仓刷新失败: ' + e;
      setBusy(btn, false);
    }});
  }};
  restoreRefreshStatus();
  </script>
    """


def _metric(label: str, value: str) -> str:
    return f'<div class="metric"><div class="label">{esc(label)}</div><div class="value">{value}</div></div>'


def _warning(text: Any) -> str:
    if not text:
        return ""
    return f'<div class="warning-box" style="margin:10px 0">{esc(text)}</div>'


def _action_text(decision: Dict[str, Any]) -> str:
    allocations = decision.get("allocations") or {}
    risky = {
        symbol: weight
        for symbol, weight in allocations.items()
        if symbol in {str(decision.get("risk_symbol")), "FNGU", "SOXL"} and _float(weight, 0.0) > 0
    }
    cycle = str(decision.get("cycle", "NA"))
    if cycle == "CASH" or allocations.get("BOXX"):
        return "<span class='route'>转入 BOXX / 现金防守</span>"
    if cycle in {"RISK_WARNING", "DECLINE", "CHOP"} or not risky:
        return "<span class='route'>清杠杆，仅保留底层 ETF</span>"
    return "<span class='route'>按表格配置杠杆 + 底层 ETF</span>"


def _rule_badge(passed: Any) -> str:
    if passed is True:
        return _badge("通过", "ok")
    if passed is False:
        return _badge("未满足", "warn")
    return _badge("缺数据", "watch")


def _price_for(payload: Dict[str, Any], symbol: str, pnl: Dict[str, Any]) -> float:
    if str(pnl.get("symbol", "")) == symbol:
        price = _float(pnl.get("current_close"), 0.0)
        if price > 0:
            return price
    return _float(_snap(payload, symbol, "close"), 0.0)


def _portfolio_base(payload: Dict[str, Any]) -> float:
    ibkr = payload.get("ibkr") or {}
    posterior = payload.get("posterior_pnl") or {}
    for value in [ibkr.get("net_liq"), posterior.get("portfolio_value"), 100000.0]:
        base = _float(value, 0.0)
        if base > 0:
            return base
    return 100000.0


def _mirror_cap(payload: Dict[str, Any]) -> float:
    decisions = ((payload.get("mirror") or {}).get("decisions") or {})
    return sum(_float(decisions.get(sleeve, {}).get("sleeve_cap"), 0.0) for sleeve in MIRROR_ORDER)


def _mirror_total_pnl(posterior: Dict[str, Any]) -> float:
    rows = posterior.get("mirror") or {}
    return sum(_float(row.get("pnl"), 0.0) for row in rows.values())


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
