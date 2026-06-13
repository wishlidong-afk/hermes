"""Operator workbench (port 8765) — four zones in decision order.

Zone 1 what-to-do · Zone 2 why · Zone 3 macro · Zone 4 fund look-through.
Read-only render of the latest audit payload; every field consumed here
already exists in the payload (no new computation). Actions stay on 8766.
"""
from __future__ import annotations

import html
from typing import Any, Dict, List, Optional

TRADE_SYMBOLS = ["MSTR", "FNGU", "SOXL"]
LADDER = [("WATCH", 20), ("TRIM", 35), ("REDUCE", 50), ("D-EXIT", 70), ("EXIT", 75)]

STATUS_COLOR = {
    "EXIT": ("#FCEBEB", "#A32D2D"), "DEFENSIVE_EXIT": ("#FCEBEB", "#A32D2D"),
    "REDUCE": ("#FAEEDA", "#854F0B"), "TRIM": ("#FAEEDA", "#854F0B"),
    "WATCH": ("#E6F1FB", "#185FA5"), "HOLD": ("#E1F5EE", "#0F6E56"),
}


def esc(value: Any) -> str:
    return html.escape(str(value))


def _f(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _badge(status: str) -> str:
    bg, fg = STATUS_COLOR.get(status, ("#F1EFE8", "#444441"))
    return (f"<span style='background:{bg};color:{fg};font-size:12px;"
            f"padding:2px 10px;border-radius:8px;font-weight:600'>{esc(status)}</span>")


def _flow_cell(value: Optional[float], lo: float, hi: float, digits: int = 2) -> str:
    """teal=inflow, coral=outflow heat cell scaled between lo..hi."""
    if value is None:
        return "<td style='text-align:center;color:#999'>—</td>"
    v = max(min(float(value), hi), lo)
    span = (hi - lo) or 1.0
    frac = (v - lo) / span  # 0 = worst outflow, 1 = best inflow
    if frac < 0.5:
        depth = 1.0 - frac * 2
        bg = "#F0997B" if depth > 0.5 else "#F5C4B3"
        fg = "#712B13"
    else:
        depth = (frac - 0.5) * 2
        bg = "#5DCAA5" if depth > 0.5 else "#9FE1CB"
        fg = "#085041"
    return f"<td style='text-align:center;background:{bg};color:{fg}'>{_f(value, digits)}</td>"


# ── Zone 1: what to do ───────────────────────────────────────────────────────

def _zone_actions(payload: Dict[str, Any]) -> str:
    scores = payload.get("scores") or {}
    routing = payload.get("routing") or {}
    ops = payload.get("today_ops") or {}
    spine = payload.get("confidence_spine") or {}
    layers = payload.get("decision_layers") or {}

    rows = []
    for sym in TRADE_SYMBOLS:
        s = scores.get(sym) or {}
        r = routing.get(sym) or {}
        weights = r.get("weights") or {}
        dest = ", ".join(f"{esc(k)} {int(round(float(v) * 100))}%" for k, v in weights.items()) \
            or esc(r.get("destination") or "持有")
        valves = ", ".join(s.get("hard_valve_hits") or [])
        driver = f"阀门 {valves}" if valves else "分数驱动"
        sell = s.get("sell_fraction")
        sell_txt = f"卖出 {int(round(float(sell) * 100))}%" if sell else "持有"
        rows.append(
            f"<div style='display:flex;gap:10px;align-items:center;padding:8px 0;"
            f"border-bottom:1px solid #eee'>{_badge(str(s.get('status', 'NA')))}"
            f"<b style='width:52px'>{esc(sym)}</b>"
            f"<span style='color:#555'>{sell_txt} · {driver}</span>"
            f"<span style='margin-left:auto;color:#555'>→ {dest}</span></div>"
        )

    manual = []
    if str(spine.get("mode", "")) == "DEGRADED":
        manual.append("置信度 DEGRADED：决策需人工确认")
    for sym, dl in (layers or {}).items():
        pend = ((dl or {}).get("hard_valve_state") or {}).get("pending_ids") or []
        if pend:
            manual.append(f"{esc(sym)} 阀门 PENDING：{', '.join(map(str, pend))}")
    mode = esc(str(spine.get("mode", "NA")))
    frag = (spine.get("components") or {}).get("fragility")
    manual_txt = "；".join(manual) or "无需人工干预项"
    return f"""
    <section class="card">
      <div class="zone-label">区域 1 · 今天怎么做</div>
      <div style="font-size:15px;font-weight:600;margin:4px 0 8px">{esc(ops.get('headline', ''))}</div>
      {''.join(rows)}
      <div style="margin-top:8px;font-size:12px;color:#854F0B">人工确认：{manual_txt} · 置信度 {mode}（fragility {_f(frag)}）</div>
    </section>"""


# ── Zone 2: why ──────────────────────────────────────────────────────────────

def _valve_dot(c: Dict[str, Any]) -> str:
    status = c.get("status")
    cur, thr = c.get("current") or {}, c.get("threshold") or {}
    color, label = "#e8e6df", "安全"
    if status == "triggered":
        color, label = "#E24B4A", "已触发"
    elif status in ("pending", "buffered"):
        color, label = "#FAC775", str(status)
    elif isinstance(cur, dict):
        near = False
        try:
            if "ma200" in cur and cur.get("close") and cur.get("ma200"):
                near = 0 < (float(cur["close"]) - float(cur["ma200"])) / float(cur["ma200"]) < 0.10
            elif "return_1d" in (thr or {}) and cur.get("return_1d") is not None:
                near = float(cur["return_1d"]) <= float(thr["return_1d"]) * 0.6
            elif "return_2d" in (thr or {}) and cur.get("return_2d") is not None:
                near = float(cur["return_2d"]) <= float(thr["return_2d"]) * 0.6
            elif "drawdown_60d" in (thr or {}) and cur.get("drawdown_60d") is not None:
                near = float(cur["drawdown_60d"]) <= float(thr["drawdown_60d"]) + 0.05
        except (TypeError, ValueError, ZeroDivisionError):
            near = False
        if near:
            color, label = "#EF9F27", "接近"
    tip = f"{c.get('id')}: {c.get('desc')} · {label} · 解除/确认: {c.get('confirm_condition')}"
    return (f"<span title='{esc(tip)}' style='display:inline-block;width:14px;height:14px;"
            f"border-radius:3px;background:{color};margin:1px'></span>")


def _zone_why(payload: Dict[str, Any]) -> str:
    scores = payload.get("scores") or {}
    layers = payload.get("decision_layers") or {}
    spine = payload.get("confidence_spine") or {}

    ticks = "".join(
        f"<span style='position:absolute;left:{v}%;top:-14px;font-size:10px;color:#888'>{name} {v}</span>"
        f"<span style='position:absolute;left:{v}%;top:0;width:1px;height:10px;background:#ccc'></span>"
        for name, v in LADDER
    )
    marks, legends = [], []
    palette = {"MSTR": "#534AB7", "FNGU": "#D85A30", "SOXL": "#BA7517"}
    for sym in TRADE_SYMBOLS:
        s = scores.get(sym) or {}
        try:
            val = max(0.0, min(100.0, float(s.get("final_score"))))
        except (TypeError, ValueError):
            continue
        color = palette.get(sym, "#555")
        marks.append(f"<span style='position:absolute;left:{val}%;top:-3px;width:3px;height:16px;background:{color}'></span>")
        legends.append(f"<span style='color:{color}'>■</span> {esc(sym)} {_f(s.get('final_score'), 1)}")

    valve_rows = []
    for sym in TRADE_SYMBOLS:
        cands = (((layers.get(sym) or {}).get("hard_valve_state") or {}).get("candidates")
                 or (scores.get(sym) or {}).get("valve_candidates") or [])
        dots = "".join(_valve_dot(c) for c in cands)
        valve_rows.append(f"<div style='display:flex;gap:8px;align-items:center'>"
                          f"<span style='width:52px;font-weight:600'>{esc(sym)}</span>{dots}</div>")

    comps = spine.get("components") or {}
    comp_txt = " · ".join(f"{esc(k)} {_f(v)}" for k, v in sorted(comps.items()))
    return f"""
    <section class="card">
      <div class="zone-label">区域 2 · 系统为什么这么想</div>
      <div style="position:relative;height:10px;background:#f1efe8;border-radius:5px;margin:22px 4px 8px">{ticks}{marks}</div>
      <div style="font-size:12px;color:#555;margin-bottom:10px">{' · '.join(legends)}（硬阀门触发时直接抬至 EXIT，无视梯子）</div>
      {''.join(valve_rows)}
      <div style="font-size:11px;color:#888;margin-top:4px">阀门点阵：红=已触发 黄=接近/待确认 灰=安全 — 悬停看当前值与解除条件</div>
      <div style="font-size:12px;color:#555;border-top:1px solid #eee;margin-top:8px;padding-top:6px">
        置信度 {_f(spine.get('decision_confidence'))} · {esc(str(spine.get('mode', 'NA')))} · 最弱环 {esc(str(spine.get('weakest_link', 'NA')))} ｜ {comp_txt}</div>
    </section>"""


# ── Zone 2.5: ideal book ─────────────────────────────────────────────────────

def _zone_target_book(payload: Dict[str, Any]) -> str:
    sizing = payload.get("sizing") or {}
    ib = payload.get("ibkr") or {}
    legs = ib.get("route_legs") or []
    rc = payload.get("risk_contributions") or {}

    trade_rows = []
    for sym in TRADE_SYMBOLS:
        sz = sizing.get(sym) or {}
        tw = sz.get("target_weight", sz.get("reference_target_weight"))
        contrib = (rc.get(sym) or {}).get("vol_contribution_pct")
        contrib_txt = f"{float(contrib) * 100:.0f}%" if contrib is not None else "—"
        trade_rows.append(
            f"<tr><td style='font-weight:600'>{esc(sym)}</td>"
            f"<td style='text-align:right'>{_f((tw or 0) * 100, 1)}%</td>"
            f"<td style='text-align:right;color:#888'>—</td><td style='text-align:right;color:#888'>—</td>"
            f"<td style='text-align:right'>{contrib_txt}</td>"
            f"<td style='color:#888'>{esc(sz.get('binding_constraint', ''))}</td></tr>"
        )

    leg_rows = []
    for leg in legs:
        status = str(leg.get("status", ""))
        color = "#A32D2D" if status == "MISSING" else ("#0F6E56" if status in ("OK", "MATCH") else "#854F0B")
        delta = leg.get("delta_weight")
        leg_rows.append(
            f"<tr><td style='font-weight:600'>{esc(leg.get('symbol'))}</td>"
            f"<td style='text-align:right'>{_f(float(leg.get('ideal_weight') or 0) * 100, 1)}%</td>"
            f"<td style='text-align:right'>{_f(float(leg.get('actual_weight') or 0) * 100, 1)}%</td>"
            f"<td style='text-align:right;color:{'#A32D2D' if (delta or 0) < -0.02 else '#555'}'>{_f(float(delta or 0) * 100, 1)}%</td>"
            f"<td style='text-align:right;color:#888'>{_f(float(leg.get('ideal_notional') or 0) / 1000, 1)}k</td>"
            f"<td style='color:{color}'>{esc(status)}</td></tr>"
        )

    port = (rc.get("_portfolio") or {}).get("forecast_vol")
    tol = ib.get("all_within_tolerance")
    tol_txt = ("✓ 全部在容差内" if tol else "✗ 有偏差腿") if tol is not None else "—"
    return f"""
    <section class="card">
      <div class="zone-label">区域 2.5 · 理想持仓（系统目标账本 vs IBKR 实际）</div>
      <table style="width:100%;font-size:12px;border-collapse:collapse;table-layout:fixed">
        <tr style="color:#888"><td style="width:64px"></td><td style="text-align:right">理想权重</td>
          <td style="text-align:right">实际权重</td><td style="text-align:right">偏差</td>
          <td style="text-align:right">理想金额/风险贡献</td><td style="width:90px">状态</td></tr>
        {''.join(trade_rows)}
        {''.join(leg_rows)}
      </table>
      <div style="font-size:12px;color:#555;border-top:1px solid #eee;margin-top:8px;padding-top:6px">
        净清算值 {_f(float(ib.get('net_liq') or 0) / 1000, 1)}k · 最大偏差 {_f(float(ib.get('max_abs_delta') or 0) * 100, 1)}% · {tol_txt}
        · 组合预测波动 {_f(port, 3)} ｜ 其余为现金/未路由</div>
    </section>"""


# ── Zone 3: macro ────────────────────────────────────────────────────────────

def _zone_macro(payload: Dict[str, Any]) -> str:
    scores = payload.get("scores") or {}
    ctx = payload.get("routing_context") or {}
    regime = payload.get("regime") or {}
    stress = payload.get("stress_scenarios") or []

    factors: List[str] = []
    a_factors = ((scores.get("FNGU") or scores.get("MSTR") or {}).get("factor_scores") or {}).get("A") or []
    for f in a_factors:
        try:
            mx = float(f.get("max_score") or 0)
            sc = float(f.get("score") or 0)
        except (TypeError, ValueError):
            continue
        if mx <= 0:
            continue
        frac = sc / mx
        color = "#E24B4A" if frac >= 0.75 else ("#EF9F27" if frac >= 0.4 else "#5DCAA5")
        name = esc(str(f.get("factor_id", "")).replace("A1_", "").replace("A2_", "")
                   .replace("A", "A", 1))
        factors.append(
            f"<div><div style='font-size:11px;color:#555'>{name} {_f(sc, 0)}/{_f(mx, 0)}</div>"
            f"<div style='height:6px;background:#f1efe8;border-radius:3px'>"
            f"<div style='width:{int(frac * 100)}%;height:6px;background:{color};border-radius:3px'></div></div></div>"
        )

    q = ctx.get("qqq") or {}
    def _line(label, key_v, key_b):
        ok = not q.get(key_b)
        mark = "✓" if ok else "✗ 破位"
        color = "#0F6E56" if ok else "#A32D2D"
        return f"{label} {_f(q.get(key_v), 0)} <span style='color:{color}'>{mark}</span>"
    qqq_txt = (f"QQQ {_f(q.get('close'), 0)} ｜ {_line('EMA20', 'ema20', 'below_ema20')} ｜ "
               f"{_line('EMA50', 'ema50', 'below_ema50')} ｜ {_line('MA200', 'ma200', 'below_ma200')}") if q else "QQQ 数据缺失"

    brkb = ctx.get("brkb_defense") or {}
    stress_txt = " · ".join(
        f"{esc(s.get('name'))}: " + (f"{_f(s.get('est_pnl_pct'))}%" if s.get('est_pnl_pct') is not None
                                     else f"vol {_f(s.get('forecast_vol_before'), 3)}→{_f(s.get('forecast_vol_after'), 3)}")
        for s in stress if isinstance(s, dict) and not s.get("_error"))
    return f"""
    <section class="card">
      <div class="zone-label">区域 3 · 宏观局势</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px 16px;margin-bottom:10px">{''.join(factors)}</div>
      <div style="font-size:12px;color:#555;border-top:1px solid #eee;padding-top:8px">
        {qqq_txt} · Regime <b>{esc(regime.get('current', 'NA'))}</b><br>
        BRK.B 防御腿：{esc(brkb.get('reason', 'NA'))}（corr {_f(brkb.get('corr_to_spy'))} / 阈值 {_f(brkb.get('threshold'))}）<br>
        压力测试：{stress_txt or '—'}</div>
    </section>"""


# ── Zone 4: fund look-through ────────────────────────────────────────────────

def _basket_table(fund: str, basket: Dict[str, Any], fund_flow: Dict[str, Any]) -> str:
    rows_data = basket.get("components") or basket.get("rows") or []
    if not rows_data and isinstance(basket, dict):
        rows_data = [v for v in basket.values() if isinstance(v, dict) and v.get("symbol")]
    rows_data = sorted(rows_data, key=lambda r: (r.get("severity") != "ABNORMAL",
                                                 -(r.get("outflow_days_5d") or 0),
                                                 r.get("cmf20") or 0))
    body = []
    for r in rows_data:
        sev = r.get("severity")
        sev_html = ("<td style='color:#A32D2D;font-weight:600'>ABNORMAL</td>" if sev == "ABNORMAL"
                    else f"<td style='color:#888'>{esc(sev or '—')}</td>")
        signed = r.get("legacy_signed_5d")
        signed_txt = f"{float(signed) / 1e9:+.1f}B" if isinstance(signed, (int, float)) else "—"
        body.append(
            f"<tr><td style='font-weight:600'>{esc(r.get('symbol'))}</td>"
            + _flow_cell(r.get("cmf20"), -0.25, 0.25)
            + _flow_cell((r.get("mfi14") or 50) - 50 if r.get("mfi14") is not None else None, -25, 25, 0)
            + f"<td style='text-align:center'>{esc(r.get('outflow_days_5d', '—'))}/5</td>"
            + f"<td style='text-align:right'>{signed_txt}</td>"
            + sev_html + "</tr>"
        )
    abnormal = basket.get("abnormal_components")
    fund_cmf = fund_flow.get("cmf20")
    worst = rows_data[0] if rows_data else {}
    diverge = ""
    try:
        if fund_cmf is not None and worst.get("cmf20") is not None and \
                float(fund_cmf) > 0 > float(worst["cmf20"]) and worst.get("severity") == "ABNORMAL":
            diverge = (f"<div style='color:#A32D2D;font-size:12px;margin-top:6px'>⚠ 背离：基金层流入 "
                       f"(CMF {_f(fund_cmf)}) 但 {esc(worst.get('symbol'))} 持续流出 — 龙头先走，历史上领先指数 3-8 个交易日</div>")
    except (TypeError, ValueError):
        pass
    return f"""
      <div style="margin-bottom:14px">
        <div style="font-size:14px;font-weight:600;margin-bottom:6px">{esc(fund)} → {len(rows_data)} 成分 ·
          基金层 CMF {_f(fund_cmf)} · 异常 {esc(abnormal if abnormal is not None else '—')} 只</div>
        <table style="width:100%;font-size:12px;border-collapse:collapse;table-layout:fixed">
          <tr style="color:#888;text-align:center"><td style="width:60px;text-align:left"></td>
            <td>CMF20</td><td>MFI−50</td><td>流出天数</td><td style="width:70px;text-align:right">5日净额</td><td style="width:90px">判定</td></tr>
          {''.join(body)}
        </table>{diverge}
      </div>"""


def _zone_lookthrough(payload: Dict[str, Any]) -> str:
    flow = payload.get("flow") or {}
    baskets = flow.get("component_baskets") or {}
    fund_flows = flow.get("symbols") or {}
    parts = [_basket_table(fund, baskets.get(fund) or {}, fund_flows.get(fund) or {})
             for fund in ("FNGU", "SOXL") if baskets.get(fund)]
    m = fund_flows.get("MSTR") or {}
    mstr_line = (f"<div style='font-size:12px;color:#555;border-top:1px solid #eee;padding-top:6px'>"
                 f"MSTR（无成分穿透）：自身 CMF {_f(m.get('cmf20'))} · MFI {_f(m.get('mfi14'), 0)} · "
                 f"流出天数 {esc(m.get('outflow_days_5d', '—'))}/5 · {esc(m.get('severity', ''))}</div>") if m else ""
    return f"""
    <section class="card">
      <div class="zone-label">区域 4 · 基金穿透 — 成分股资金流（teal=流入 coral=流出，按恶劣度排序）</div>
      {''.join(parts) or "<div style='color:#888'>flow 数据缺失</div>"}
      {mstr_line}
    </section>"""


# ── Page ─────────────────────────────────────────────────────────────────────

def _preview_banner(official: Dict[str, Any], preview: Optional[Dict[str, Any]]) -> str:
    """Disclose when a newer manual re-run exists that is NOT shown below.

    The page always shows the OFFICIAL (scheduled) run. If someone triggered an
    intraday manual re-run afterwards, we say so explicitly with the diff —
    instead of silently swapping the advice (the 2026-06-11 trust failure)."""
    if not preview:
        return ""
    diffs = []
    for sym in TRADE_SYMBOLS:
        o = (official.get("scores") or {}).get(sym, {}).get("status")
        p = (preview.get("scores") or {}).get(sym, {}).get("status")
        if o != p:
            diffs.append(f"{esc(sym)} {esc(o)}→{esc(p)}")
    diff_txt = ("预览与官方差异：" + "、".join(diffs)) if diffs else "预览与官方建议一致（仅时间戳不同）"
    return f"""
    <section class="card" style="border:1px solid #d98a2b;background:#fdf6ec">
      <div style="font-size:13px;font-weight:600;color:#8a5a1a">⚠ 存在更新的盘中重跑（非官方）</div>
      <div style="font-size:12px;color:#7a6a4a;margin-top:4px">
        下方显示的是<b>官方定时运行</b>（{esc(official.get('run_ts','')[:16])}）。另有一次盘中手动重跑
        ({esc(preview.get('run_ts','')[:16])}) 未作为今日建议采用——{diff_txt}。
        盘中重跑仅供排查，永不覆盖官方建议。</div>
    </section>"""


def render_workbench(payload: Dict[str, Any], trust: Optional[List[Dict[str, Any]]] = None,
                     preview: Optional[Dict[str, Any]] = None) -> str:
    as_of = payload.get("as_of", "NA")
    run_type = payload.get("run_type", "scheduled")
    official_tag = "官方定时运行" if run_type == "scheduled" else f"{esc(run_type)}（注意：无官方运行可用）"
    return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hermes 工作台 · {esc(as_of)}</title>
<style>
  body {{ font-family: -apple-system, "PingFang SC", sans-serif; max-width: 860px;
         margin: 0 auto; padding: 16px; background: #faf9f5; color: #2c2c2a; }}
  .card {{ background: #fff; border: 1px solid #e8e6df; border-radius: 12px;
           padding: 14px 18px; margin-bottom: 16px; }}
  .zone-label {{ font-size: 12px; color: #888; margin-bottom: 6px; }}
  .top-link {{ font-size:12px;padding:4px 12px;border:1px solid #ccc;border-radius:8px;background:#fff;
               color:#2c2c2a;text-decoration:none;white-space:nowrap }}
  td {{ padding: 3px 4px; }}
  h1 {{ font-size: 18px; font-weight: 600; margin: 0 0 2px; }}
</style></head><body>
<h1>Hermes 操作者工作台</h1>
<div style="font-size:12px;color:#888;margin-bottom:14px;display:flex;align-items:center;gap:12px">
  <span>as_of={esc(as_of)} · {official_tag} · 每次刷新读最新审计记录</span>
  <a class="top-link" style="margin-left:auto" href="http://127.0.0.1:8766/?as_of={esc(as_of)}">逃顶驾驶舱 8766</a>
  <button onclick="refreshData(this)" style="font-size:12px;padding:4px 12px;border:1px solid #ccc;border-radius:8px;background:#fff;cursor:pointer">手动更新数据</button>
  <span id="refresh-status" style="font-size:12px;color:#854F0B"></span>
</div>
<script>
function refreshData(btn) {{
  btn.disabled = true;
  document.getElementById('refresh-status').textContent = '触发中…';
  fetch('/refresh', {{method: 'POST'}}).then(r => r.text()).then(t => {{
    document.getElementById('refresh-status').textContent = t;
    btn.disabled = false;
  }}).catch(e => {{
    document.getElementById('refresh-status').textContent = '触发失败: ' + e;
    btn.disabled = false;
  }});
}}
</script>
{_preview_banner(payload, preview)}
{_zone_actions(payload)}
{_zone_why(payload)}
{_zone_target_book(payload)}
{_zone_macro(payload)}
{_zone_lookthrough(payload)}
{_zone_trust(trust)}
</body></html>"""


# ── Zone 5: data trust ───────────────────────────────────────────────────────

def _zone_trust(trust: Optional[List[Dict[str, Any]]]) -> str:
    """Per-source freshness ledger: last date / source / proxy / SLO deadline.

    `trust` rows are computed server-side (serve_workbench reads the soft CSV
    tails); rendering a payload alone (tests, offline) just omits the zone.
    """
    if not trust:
        return ""
    rows = []
    for t in sorted(trust, key=lambda x: x.get("days_left", 99)):
        days_left = t.get("days_left")
        if days_left is None:
            color, label = "#888", "—"
        elif days_left < 0:
            color, label = "#A32D2D", f"超期 {-days_left}d"
        elif days_left <= 3:
            color, label = "#854F0B", f"剩 {days_left}d"
        else:
            color, label = "#0F6E56", f"剩 {days_left}d"
        proxy = "代理" if t.get("is_proxy") else "真实"
        rows.append(
            f"<tr><td style='font-weight:600'>{esc(t.get('name'))}</td>"
            f"<td>{esc(t.get('last_date', '—'))}</td>"
            f"<td style='color:{'#854F0B' if t.get('is_proxy') else '#0F6E56'}'>{proxy}</td>"
            f"<td style='color:#888'>{esc(t.get('source', '—'))}</td>"
            f"<td>{esc(t.get('cadence', ''))}</td>"
            f"<td style='color:{color}'>{label}</td></tr>")
    return f"""
    <section class="card">
      <div class="zone-label">区域 5 · 数据信任区（每源：最新 / 真实性 / SLO 倒计时）</div>
      <table style="width:100%;font-size:12px;border-collapse:collapse;table-layout:fixed">
        <tr style="color:#888"><td style="width:120px">源</td><td>最新数据日</td><td>性质</td>
          <td>来源</td><td>节奏</td><td>SLO</td></tr>
        {''.join(rows)}
      </table>
    </section>"""
