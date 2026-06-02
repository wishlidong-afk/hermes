from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any, Dict


def render_dashboard(payload: Dict[str, Any]) -> str:
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
