from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any, Dict


def _render_ibkr_section(ibkr: Dict[str, Any]) -> str:
    """Render IBKR reconciliation section."""
    source = ibkr.get("source", "disabled")
    if source in ("disabled", "unavailable") or ibkr.get("error") and not ibkr.get("net_liq"):
        note = ibkr.get("note", ibkr.get("error", ""))
        return f'<section><h2>IBKR Reconciliation</h2><p class="meta">{escape(source)}: {escape(str(note))}</p></section>'

    nl = float(ibkr.get("net_liq", 0))
    sync = str(ibkr.get("sync_time", ""))[:19]
    max_d = float(ibkr.get("max_abs_delta", 0))
    all_ok = ibkr.get("all_within_tolerance", False)
    ok_color = "#d1fae5" if all_ok else "#fee2e2"
    ok_text = "✅ All within tolerance" if all_ok else f"⚠️ Max delta {max_d:.2%}"
    err = ibkr.get("error")

    rows = []
    for section, items in [
        ("Trade Symbol", ibkr.get("trade_symbols", [])),
        ("Route Leg", ibkr.get("route_legs", [])),
        ("Extra", ibkr.get("extra_positions", [])),
    ]:
        for d in items:
            status = d.get("status", "?")
            status_colors = {
                "MATCH": ("#d1fae5", "#065f46"),
                "MISSING": ("#fee2e2", "#991b1b"),
                "OVER": ("#fef9c3", "#854d0e"),
                "UNDER": ("#fef3c7", "#92400e"),
                "EXTRA": ("#ede9fe", "#5b21b6"),
                "ROUTE_LEG": ("#e0f2fe", "#075985"),
            }
            bg, fg = status_colors.get(status, ("#f3f4f6", "#374151"))
            rows.append(
                "<tr>"
                f"<td>{escape(section)}</td>"
                f"<td>{escape(d.get('symbol','?'))}</td>"
                f"<td>{float(d.get('ideal_weight',0)):.2%}</td>"
                f"<td>{float(d.get('actual_weight',0)):.2%}</td>"
                f"<td>{float(d.get('delta_weight',0)):+.2%}</td>"
                f"<td>${float(d.get('actual_notional',0)):,.0f}</td>"
                f"<td>{float(d.get('actual_shares',0)):.2f}</td>"
                f"<td><span style='background:{bg};color:{fg};padding:2px 6px;border-radius:4px;font-size:12px'>{escape(status)}</span></td>"
                f"<td style='font-size:12px;color:#6b7280'>{escape(d.get('note',''))}</td>"
                "</tr>"
            )

    rows_html = "".join(rows) if rows else "<tr><td colspan='9'>No position data</td></tr>"
    err_html = f'<p style="color:#dc2626;font-size:12px">Error: {escape(str(err))}</p>' if err else ""

    return f"""<section>
    <h2>IBKR Reconciliation <span style="font-size:12px;font-weight:normal;color:#6b7280">(read-only · no orders)</span></h2>
    <p>
      Account: <b>{escape(str(ibkr.get('account_id','?')))}</b>
      &nbsp;|&nbsp; NetLiq: <b>${nl:,.2f}</b>
      &nbsp;|&nbsp; Sync: {escape(sync)}
      &nbsp;|&nbsp; <span style="background:{ok_color};padding:3px 8px;border-radius:4px;font-size:13px">{ok_text}</span>
    </p>
    {err_html}
    <table>
      <thead><tr>
        <th>Type</th><th>Symbol</th><th>Ideal</th><th>Actual</th><th>Delta</th>
        <th>Notional</th><th>Shares</th><th>Status</th><th>Note</th>
      </tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </section>"""


def _render_m4_panel(shadow_status: Dict[str, Any]) -> str:
    """M4 migration control panel with shadow-run and go-live buttons."""
    mode = shadow_status.get("run_daily_mode", "unknown")
    mode_color = {"monolith": "#fef9c3", "package": "#d1fae5", "unknown": "#f3f4f6"}.get(mode, "#f3f4f6")
    mode_text_color = {"monolith": "#854d0e", "package": "#065f46", "unknown": "#374151"}.get(mode, "#374151")
    mode_label = {"monolith": "🔶 单体引擎（生产）", "package": "✅ 包引擎（已上线）", "unknown": "❓ 未知"}.get(mode, mode)

    # Shadow log table
    log_entries = shadow_status.get("log_entries", [])
    log_rows = []
    for e in reversed(log_entries[-5:]):
        mr = e.get("match_rate", 0)
        divs = e.get("divergences", [])
        ok_badge = (
            '<span style="background:#d1fae5;color:#065f46;padding:2px 6px;border-radius:4px">✅</span>'
            if mr == 100 else
            f'<span style="background:#fee2e2;color:#991b1b;padding:2px 6px;border-radius:4px">⚠️ {mr}%</span>'
        )
        divs_text = "; ".join(divs) if divs else "—"
        log_rows.append(
            f"<tr><td>{escape(str(e.get('date','?')))}</td>"
            f"<td>{ok_badge}</td>"
            f"<td>{e.get('matches',0)}/{e.get('total',0)}</td>"
            f"<td style='font-size:11px;color:#6b7280'>{escape(divs_text)}</td></tr>"
        )
    log_table = (
        "<table><thead><tr><th>日期</th><th>状态</th><th>匹配</th><th>差异</th></tr></thead>"
        f"<tbody>{''.join(log_rows) if log_rows else '<tr><td colspan=4>尚无记录，先运行 M4-2</td></tr>'}</tbody></table>"
    )

    # Latest shadow precheck summary
    shadow_pc = shadow_status.get("shadow_precheck")
    shadow_summary_rows = []
    if shadow_pc:
        for sym in ["MSTR", "FNGU", "SOXL"]:
            r = shadow_pc.get("results", {}).get(sym, {})
            ht = r.get("hard_trigger", {}) or {}
            hard_str = (",".join(ht.get("ids", [])) or "—") if ht.get("triggered") else "—"
            shadow_summary_rows.append(
                f"<tr><td>{escape(sym)}</td>"
                f"<td><b>{escape(str(r.get('status','?')))}</b></td>"
                f"<td>{r.get('sell_pct',0)}%</td>"
                f"<td>{r.get('total_score',0)}</td>"
                f"<td style='color:#dc2626'>{escape(hard_str)}</td></tr>"
            )
        shadow_as_of = shadow_pc.get("as_of", "?")
        shadow_schema = shadow_pc.get("schema_version", "")
        shadow_header = f'<p style="font-size:12px;color:#4b5563">最新影子预检: <b>{escape(shadow_as_of)}</b> · schema: {escape(shadow_schema)}</p>'
    else:
        shadow_header = '<p style="font-size:12px;color:#9ca3af">尚无影子预检文件（先运行 M4-2）</p>'

    shadow_table = (
        f"{shadow_header}"
        "<table><thead><tr><th>标的</th><th>状态</th><th>卖出%</th><th>分数</th><th>硬触发</th></tr></thead>"
        f"<tbody>{''.join(shadow_summary_rows) if shadow_summary_rows else '<tr><td colspan=5>—</td></tr>'}</tbody></table>"
    ) if shadow_pc else shadow_header

    golive_warn = "" if mode == "monolith" else (
        '<p style="background:#d1fae5;color:#065f46;padding:8px;border-radius:6px;font-size:13px">'
        '✅ 已切换到包引擎。M4-3 按钮不需要再点。</p>'
    )

    return f"""<section style="border:2px solid #7c3aed;background:#fdf4ff">
  <h2 style="color:#6d28d9">🚀 M4 迁移控制台</h2>
  <p style="font-size:13px;color:#4b5563">
    当前 run_daily.py 引擎：
    <span style="background:{mode_color};color:{mode_text_color};padding:3px 10px;border-radius:6px;font-weight:700">
      {mode_label}
    </span>
  </p>

  <div style="display:flex;gap:12px;flex-wrap:wrap;margin:12px 0">
    <!-- M4-2 shadow button -->
    <div style="flex:1;min-width:280px;background:#fffbeb;border:1px solid #f59e0b;border-radius:8px;padding:14px">
      <h3 style="margin:0 0 6px;color:#92400e;font-size:14px">M4-2 · 今日影子对比</h3>
      <p style="font-size:12px;color:#6b7280;margin:0 0 10px">
        用包引擎跑今天的日期（跳过 OHLCV 刷新，速度快），写入 data/shadow/，对比单体输出。
        <b>不影响任何生产文件。</b>
      </p>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <input id="shadow-date" type="date" style="border:1px solid #d1d5db;border-radius:4px;padding:4px 8px;font-size:13px">
        <button onclick="runShadow()"
          style="background:#d97706;color:white;border:none;padding:8px 18px;border-radius:6px;cursor:pointer;font-weight:700;font-size:13px">
          ▶ 运行影子对比
        </button>
        <span id="shadow-status" style="font-size:12px;color:#6b7280"></span>
      </div>
      <div id="shadow-result" style="margin-top:10px;font-size:12px;font-family:monospace;white-space:pre-wrap;max-height:200px;overflow:auto;background:#fffaf0;padding:6px;border-radius:4px;display:none"></div>
    </div>

    <!-- M4-3 go-live button -->
    <div style="flex:1;min-width:280px;background:#fef2f2;border:1px solid #ef4444;border-radius:8px;padding:14px">
      <h3 style="margin:0 0 6px;color:#991b1b;font-size:14px">M4-3 · 切换到包引擎（上线）</h3>
      <p style="font-size:12px;color:#6b7280;margin:0 0 10px">
        将 run_daily.py 改为调用包引擎（原版自动备份为 run_daily.py.monolith_backup）。
        <b>此操作影响生产——确认影子期通过后再点。</b>
      </p>
      {golive_warn}
      <div style="display:flex;gap:8px;align-items:center">
        <input type="checkbox" id="golive-confirm" style="width:16px;height:16px">
        <label for="golive-confirm" style="font-size:12px;color:#374151">我已确认影子期通过，授权上线</label>
      </div>
      <button onclick="goLive()" id="golive-btn"
        style="margin-top:10px;background:#dc2626;color:white;border:none;padding:8px 18px;border-radius:6px;cursor:pointer;font-weight:700;font-size:13px">
        ⚡ 上线切换
      </button>
      <span id="golive-status" style="display:block;margin-top:8px;font-size:13px"></span>
    </div>
  </div>

  <h3 style="font-size:13px;color:#374151;margin:12px 0 6px">影子运行历史（最近 5 次）</h3>
  {log_table}

  <h3 style="font-size:13px;color:#374151;margin:12px 0 6px">最新影子预检结果</h3>
  {shadow_table}

  <script>
  (function(){{
    // Set default date to today
    var d = document.getElementById('shadow-date');
    if(d) d.value = new Date().toISOString().slice(0,10);

    window.runShadow = function(){{
      var asOf = document.getElementById('shadow-date').value || new Date().toISOString().slice(0,10);
      var el = document.getElementById('shadow-status');
      var res = document.getElementById('shadow-result');
      var btn = document.querySelector('button[onclick="runShadow()"]');

      // Disable button to prevent double-click
      btn.disabled = true;
      btn.style.opacity = '0.6';
      btn.textContent = '⏳ 运行中…';

      // Show animated progress so user knows it's working
      var dots = 0;
      var progress = setInterval(function(){{
        dots = (dots + 1) % 4;
        el.textContent = '⏳ 正在运行(' + asOf + ')' + '.'.repeat(dots+1) + ' 约30–90秒，请耐心等待';
      }}, 800);

      res.style.display='none';

      fetch('/api/m4_shadow', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{as_of: asOf}})
      }})
      .then(function(r){{ return r.json(); }})
      .then(function(d){{
        clearInterval(progress);
        btn.disabled = false;
        btn.style.opacity = '1';
        btn.textContent = '▶ 运行影子对比';
        el.textContent = d.ok ? '✅ 完成' : '❌ 失败';

        var out = '';
        if(d.diff){{
          out += '=== 对比结果(' + asOf + ') ===\n';
          out += '匹配率: ' + d.diff.match_rate + '% (' + d.diff.matches + '/' + d.diff.total + ')\n';
          if(d.diff.divergences && d.diff.divergences.length)
            out += '差异:\n  ' + d.diff.divergences.join('\n  ') + '\n';
          else
            out += '✅ 全部一致 — 安全门通过\n';
          out += '\n';
        }}
        // Filter out noisy IBKR lines from output
        var lines = (d.output || '').split('\n').filter(function(l){{
          return l.indexOf('API connection failed') === -1 &&
                 l.indexOf('Make sure API port') === -1 &&
                 l.trim() !== '';
        }});
        out += lines.join('\n');
        res.textContent = out;
        res.style.display = 'block';
        if(d.ok) setTimeout(function(){{ location.reload(); }}, 1500);
      }})
      .catch(function(e){{
        clearInterval(progress);
        btn.disabled = false;
        btn.style.opacity = '1';
        btn.textContent = '▶ 运行影子对比';
        el.textContent = '❌ 网络错误: ' + e;
      }});
    }};

    window.goLive = function(){{
      if(!document.getElementById('golive-confirm').checked){{
        alert('请先勾选确认复选框'); return;
      }}
      if(!confirm('⚠️ 确认将 run_daily.py 切换到包引擎？这将影响每日生产运行。'))
        return;
      var st = document.getElementById('golive-status');
      st.textContent = '⏳ 切换中…';
      fetch('/api/m4_golive', {{
        method:'POST',
        headers:{{'Content-Type':'application/json'}},
        body: JSON.stringify({{confirmed: true}})
      }}).then(r=>r.json()).then(d=>{{
        st.style.color = d.ok ? '#16a34a' : '#dc2626';
        st.textContent = d.message || (d.ok ? '✅ 成功' : '❌ 失败');
        if(d.ok) setTimeout(()=>location.reload(), 1500);
      }}).catch(e=>{{ st.textContent='❌ 网络错误: '+e; }});
    }};
  }})();
  </script>
</section>"""


def render_dashboard(payload: Dict[str, Any], shadow_status: Dict[str, Any] | None = None) -> str:
    if shadow_status is None:
        shadow_status = {}
    rows = []
    detail_rows = []
    optimizer_rows = []
    factor_rows = []

    for symbol, score in sorted(payload.get("scores", {}).items()):
        sizing = payload.get("sizing", {}).get(symbol, {})
        routing = payload.get("routing", {}).get(symbol, {})
        reentry = payload.get("reentry", {}).get(symbol, {})
        modules = score.get("module_scores", {})

        # Optimizer fields (new in P12)
        binding = sizing.get("binding_constraint", "-")
        opt_conf = sizing.get("optimizer_confidence")
        sizing_engine = sizing.get("sizing_engine", "legacy")
        exec_mode = sizing.get("execution_mode", "-")
        engine_badge = (
            f'<span style="background:#d1fae5;color:#065f46;padding:2px 6px;border-radius:4px;font-size:12px">'
            f'{escape(sizing_engine)}</span>'
            if sizing_engine == "optimize_targets_v1"
            else f'<span style="background:#fef9c3;color:#854d0e;padding:2px 6px;border-radius:4px;font-size:12px">'
                 f'{escape(sizing_engine)}</span>'
        )

        rows.append(
            "<tr>"
            f"<td>{escape(symbol)}</td>"
            f"<td>{escape(str(score.get('status')))}</td>"
            f"<td>{float(score.get('final_score', 0.0)):.2f}</td>"
            f"<td>A {float(modules.get('A', 0.0)):.1f} / B {float(modules.get('B', 0.0)):.1f}"
            f" / C {float(modules.get('C', 0.0)):.1f} / D {float(modules.get('D', 0.0)):.1f}</td>"
            f"<td>{float(score.get('sell_fraction', 0.0)):.2%}</td>"
            f"<td><b>{float(sizing.get('target_weight', 0.0)):.2%}</b></td>"
            f"<td>{float(sizing.get('vol_scaler', 1.0)):.3f}</td>"
            f"<td>{escape(str(routing.get('defcon', 'NONE')))} / {escape(str(routing.get('destination', '-')))}</td>"
            f"<td>{escape(str(reentry.get('tranche', '-')))}</td>"
            f"<td>{escape(','.join(score.get('hard_valve_hits', [])) or '-')}</td>"
            "</tr>"
        )
        detail_rows.append(
            "<tr>"
            f"<td>{escape(symbol)}</td>"
            f"<td>{float(score.get('missing_weight', 0.0)):.1f}</td>"
            f"<td>{escape(str(score.get('blind_spot', False)))}</td>"
            f"<td>{float(score.get('data_quality', 0.0)):.1f}</td>"
            f"<td>{escape(str(routing.get('reason', '-')))}</td>"
            f"<td>{escape(' | '.join(score.get('explain', [])[:5]))}</td>"
            "</tr>"
        )
        # Optimizer detail panel (new)
        optimizer_rows.append(
            "<tr>"
            f"<td>{escape(symbol)}</td>"
            f"<td>{float(sizing.get('target_weight', 0.0)):.2%}</td>"
            f"<td>{float(sizing.get('reference_target_weight', 0.0)):.2%}</td>"
            f"<td>{float(sizing.get('gross_scaler', 1.0)):.3f}</td>"
            f"<td>{escape(str(binding))}</td>"
            f"<td>{_fmt_pct(opt_conf)}</td>"
            f"<td>{escape(exec_mode)}</td>"
            f"<td>{engine_badge}</td>"
            "</tr>"
        )
        # Factor IC panel (from Factor_Health if available, else module scores)
        factor_scores = score.get("factor_scores", {})
        for module, factors in factor_scores.items():
            if not isinstance(factors, list):
                continue
            for f in factors[:3]:  # top 3 per module to keep UI compact
                s = float(f.get("score", 0.0))
                mx = float(f.get("max_score", 0.0))
                pct = (s / mx * 100) if mx > 0 else 0.0
                bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
                factor_rows.append(
                    "<tr>"
                    f"<td>{escape(symbol)}</td>"
                    f"<td>{escape(module)}</td>"
                    f"<td style='font-size:12px'>{escape(f.get('factor_id','?'))}</td>"
                    f"<td>{s:.1f}/{mx:.1f}</td>"
                    f"<td style='font-family:monospace;color:#6b7280'>{bar}</td>"
                    f"<td style='font-size:11px;color:#9ca3af'>{escape(f.get('explain','')[:60])}</td>"
                    "</tr>"
                )

    risk = payload.get("portfolio_risk", {})
    regime = payload.get("regime", {})

    # Confidence / Gate 4 info
    sizing_first = next(iter(payload.get("sizing", {}).values()), {})
    opt_conf_global = sizing_first.get("optimizer_confidence")
    conf_mode = "NORMAL" if (opt_conf_global or 1.0) >= 0.80 else (
        "CAUTION" if (opt_conf_global or 1.0) >= 0.55 else "DEGRADED"
    )
    conf_color = {"NORMAL": "#d1fae5", "CAUTION": "#fef9c3", "DEGRADED": "#fee2e2"}.get(conf_mode, "#f3f4f6")
    conf_text_color = {"NORMAL": "#065f46", "CAUTION": "#854d0e", "DEGRADED": "#991b1b"}.get(conf_mode, "#374151")

    mirror_rows = []
    for sleeve, decision in sorted(payload.get("mirror", {}).get("decisions", {}).items()):
        mirror_rows.append(
            "<tr>"
            f"<td>{escape(sleeve)}</td>"
            f"<td>{escape(str(decision.get('cycle')))}</td>"
            f"<td>{escape(str(decision.get('selected_symbol')))}</td>"
            f"<td>{float(decision.get('target_weight', 0.0)):.2%}</td>"
            f"<td>{escape(str(decision.get('reason')))}</td>"
            "</tr>"
        )
    pnl_rows = []
    posterior = payload.get("posterior_pnl", {})
    for group_name, rows_by_key in [
        ("Escape", posterior.get("escape", {})),
        ("Mirror", posterior.get("mirror", {})),
    ]:
        for key, row in sorted(rows_by_key.items()):
            pnl_rows.append(
                "<tr>"
                f"<td>{escape(group_name)}</td>"
                f"<td>{escape(key)}</td>"
                f"<td>{escape(str(row.get('symbol')))}</td>"
                f"<td>{float(row.get('target_weight', 0.0)):.2%}</td>"
                f"<td>${float(row.get('notional', 0.0)):,.2f}</td>"
                f"<td>${float(row.get('pnl', 0.0)):,.2f}</td>"
                f"<td>{_fmt_pct(row.get('return_pct'))}</td>"
                f"<td>{escape(str(row.get('reason', '')))}</td>"
                "</tr>"
            )

    optimizer_rows_html = "".join(optimizer_rows) if optimizer_rows else "<tr><td colspan='8'>No optimizer data</td></tr>"
    factor_rows_html = "".join(factor_rows) if factor_rows else "<tr><td colspan='6'>No factor data</td></tr>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hermes Escape Top</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; background: #f7f8fa; color: #111827; }}
    h1, h2 {{ margin: 0 0 12px; }}
    section {{ background: white; border: 1px solid #d8dee8; border-radius: 8px; padding: 16px; margin-bottom: 16px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 7px 8px; text-align: left; }}
    th {{ color: #374151; background: #f3f4f6; font-weight: 600; }}
    .meta {{ color: #4b5563; font-size: 13px; }}
    .pill {{ display: inline-block; padding: 4px 10px; border-radius: 999px; font-weight: 700; font-size: 13px; }}
    .conf-badge {{ display: inline-block; padding: 3px 10px; border-radius: 6px; font-weight: 700; font-size: 13px;
                   background: {conf_color}; color: {conf_text_color}; }}
    .gate-ok {{ color: #16a34a; font-weight: 700; }}
    .gate-warn {{ color: #d97706; font-weight: 700; }}
  </style>
</head>
<body>
  <h1>Hermes Escape Top</h1>
  <p class="meta">as_of={escape(str(payload.get('as_of')))} &nbsp;|&nbsp; schema={escape(str(payload.get('schema_version')))}</p>

  {_render_m4_panel(shadow_status)}

  <section>
    <h2>System Health</h2>
    <p>
      Regime: <span class="pill" style="background:#e0f2fe;color:#075985">{escape(str(regime.get('current', 'UNKNOWN')))}</span>
      &nbsp;|&nbsp;
      Confidence: <span class="conf-badge">{conf_mode} ({_fmt_pct(opt_conf_global)})</span>
      &nbsp;|&nbsp;
      VIX pct: {_fmt_num(regime.get('vix_percentile'))} &nbsp;|&nbsp; VIX/VIX3M: {_fmt_num(regime.get('vix_term_ratio'))}
    </p>
    <p style="font-size:12px;color:#6b7280;margin-top:8px">
      Risk binding: {escape(str(risk.get('binding_constraint', risk.get('binding', 'NONE'))))}
      &nbsp;|&nbsp; gross_scaler: {float(risk.get('gross_scaler', risk.get('effective_gross_scaler', 1.0))):.3f}
      &nbsp;|&nbsp; corr_regime: {escape(str(risk.get('corr_regime', '-')))}
    </p>
  </section>

  <section>
    <h2>Escape Decisions</h2>
    <table>
      <thead><tr>
        <th>Symbol</th><th>Status</th><th>Score</th><th>Modules (A/B/C/D)</th>
        <th>Sell%</th><th>Target</th><th>Vol Scaler</th>
        <th>Route</th><th>Reentry</th><th>Hard Valve</th>
      </tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </section>

  <section>
    <h2>Optimizer Detail <span style="font-size:12px;font-weight:normal;color:#6b7280">(Gate 2: single sizing entry)</span></h2>
    <table>
      <thead><tr>
        <th>Symbol</th><th>Target Weight</th><th>Rule Ref</th><th>Gross Scaler</th>
        <th>Binding</th><th>Confidence</th><th>Exec Mode</th><th>Engine</th>
      </tr></thead>
      <tbody>{optimizer_rows_html}</tbody>
    </table>
  </section>

  <section>
    <h2>Factor Scores <span style="font-size:12px;font-weight:normal;color:#6b7280">(top factors per module)</span></h2>
    <table>
      <thead><tr>
        <th>Symbol</th><th>Module</th><th>Factor</th><th>Score</th><th>Bar</th><th>Explain</th>
      </tr></thead>
      <tbody>{factor_rows_html}</tbody>
    </table>
  </section>

  <section>
    <h2>Audit Detail</h2>
    <table>
      <thead><tr>
        <th>Symbol</th><th>Missing Weight</th><th>Blind Spot</th>
        <th>Data Quality</th><th>Route Explain</th><th>Top Reasons</th>
      </tr></thead>
      <tbody>{''.join(detail_rows)}</tbody>
    </table>
  </section>

  <section>
    <h2>Portfolio Risk</h2>
    <p>
      legs_used={escape(str(risk.get('legs_used')))}
      &nbsp;|&nbsp; forecast_vol={float(risk.get('forecast_portfolio_vol') or 0):.2%}
      &nbsp;|&nbsp; gross={float(risk.get('gross_scaler', risk.get('effective_gross_scaler', 1.0))):.3f}
      &nbsp;|&nbsp; binding={escape(str(risk.get('binding_constraint', risk.get('binding','?'))))}
      &nbsp;|&nbsp; corr_regime={escape(str(risk.get('corr_regime', '-')))}
    </p>
  </section>

  <section>
    <h2>Mirror Reference</h2>
    <table>
      <thead><tr><th>Sleeve</th><th>Cycle</th><th>Selected</th><th>Target</th><th>Reason</th></tr></thead>
      <tbody>{''.join(mirror_rows)}</tbody>
    </table>
  </section>

  <section>
    <h2>Posterior Ideal P/L</h2>
    <p class="meta">Assumes ${float(posterior.get('portfolio_value', 100000.0)):,.0f} portfolio.</p>
    <table>
      <thead><tr>
        <th>System</th><th>Sleeve</th><th>Symbol</th><th>Weight</th>
        <th>Notional</th><th>P/L</th><th>Return</th><th>Note</th>
      </tr></thead>
      <tbody>{''.join(pnl_rows)}</tbody>
    </table>
  </section>

  {_render_ibkr_section(payload.get("ibkr") or {"source": "disabled"})}

</body>
</html>
"""


def write_dashboard(payload: Dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_dashboard(payload), encoding="utf-8")
    return output_path


def _fmt_pct(value: object) -> str:
    if value is None:
        return "NA"
    try:
        return f"{float(value):.2%}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_num(value: object) -> str:
    if value is None:
        return "NA"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)
