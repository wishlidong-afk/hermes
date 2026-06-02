"""T5 — Monolith vs package decision-parity harness (V1).

Quantifies how far apart the production v25 monolith and the hermes_escape_top
package are TODAY, per trading day and symbol, on the safety/decision-critical
fields:
  - hard-valve ids (MUST reach 100% for the M4 go-live gate)
  - status
  - sell %
  - capital-route destination / protocol step

Monolith side: read from the v25 golden (tests/golden/fixtures/
v25_score_projection_golden.json), which holds the monolith's sandboxed-fixture
decisions per date/symbol. Package side: run score_pipeline(as_of) for the same
dates and extract the equivalent fields.

CAVEAT (V1): inputs are each system's own loader (monolith = frozen fixtures;
package = live store). For recent dates these are near-identical, so divergences
are predominantly code-level. A byte-identical input bridge is migration work
(tickets T1-T4 in review/A_MIGRATION_PLAN_PARITY.md). The signal-journal is
backed up and restored so this never pollutes live state.

Usage:
    PYTHONPATH=<escape-top> python -m hermes_escape_top.scripts.parity_harness
Writes: hermes_escape_top/reports/Parity_Monolith_vs_Package.{json,md}
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

from hermes_escape_top import pipeline
from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.store import LocalStore

HERMES_ROOT = Path(__file__).resolve().parents[1]
GOLDEN = HERMES_ROOT.parent / "tests" / "golden" / "fixtures" / "v25_score_projection_golden.json"
OUT_DIR = HERMES_ROOT / "reports"


def _norm_dest(value: Any) -> Any:
    """Normalize the 'no destination' sentinel across systems (None/''/'-'/'NONE')."""
    if value in (None, "", "-", "NONE", "None"):
        return None
    return value


def _monolith_decisions() -> Dict[str, Dict[str, Dict[str, Any]]]:
    g = json.loads(GOLDEN.read_text(encoding="utf-8"))
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for date, syms in g.get("results", {}).items():
        out[date] = {}
        for sym, r in syms.items():
            ht = r.get("hard_trigger", {}) or {}
            cr = r.get("capital_route", {}) or {}
            dest = _norm_dest(cr.get("destination") or cr.get("destination_symbol"))
            out[date][sym] = {
                "status": r.get("status"),
                "sell_pct": r.get("sell_pct"),
                "hard_ids": sorted(ht.get("hard_ids", ht.get("ids", [])) or []),
                "destination": dest,
                "routed": dest is not None,
            }
    return out


def _package_decisions_for(date: str) -> Dict[str, Dict[str, Any]]:
    payload = pipeline.score_pipeline(date)
    scores = payload.get("scores", {})
    routing = payload.get("routing", {})
    out: Dict[str, Dict[str, Any]] = {}
    for sym, s in scores.items():
        if sym == "SOFT":
            continue
        r = routing.get(sym, {}) or {}
        sell = s.get("sell_fraction")
        dest = _norm_dest(r.get("destination") or r.get("destination_symbol"))
        out[sym] = {
            "status": s.get("status"),
            "sell_pct": round(float(sell) * 100, 4) if sell is not None else None,
            "hard_ids": sorted(s.get("hard_valve_hits", s.get("hard_valves", [])) or []),
            "destination": dest,
            "routed": dest is not None,
        }
    return out


def run() -> Dict[str, Any]:
    mono = _monolith_decisions()
    store = LocalStore(load_config())
    journal = Path(store.archive_dir) / "signal_journal.jsonl"
    backup = journal.read_bytes() if journal.exists() else None

    fields = ["hard_ids", "status", "sell_pct", "destination", "routed"]
    counters = {f: {"match": 0, "total": 0} for f in fields}
    divergences: List[Dict[str, Any]] = []
    dates_compared: List[str] = []
    try:
        for date in sorted(mono):
            try:
                pkg = _package_decisions_for(date)
            except Exception as exc:  # noqa: BLE001 - harness must not abort on one date
                divergences.append({"date": date, "error": str(exc)})
                continue
            dates_compared.append(date)
            for sym, m in mono[date].items():
                p = pkg.get(sym)
                if p is None:
                    divergences.append({"date": date, "symbol": sym, "note": "missing in package"})
                    continue
                for f in fields:
                    counters[f]["total"] += 1
                    if m.get(f) == p.get(f):
                        counters[f]["match"] += 1
                    else:
                        divergences.append({
                            "date": date, "symbol": sym, "field": f,
                            "monolith": m.get(f), "package": p.get(f),
                        })
    finally:
        if backup is not None:
            journal.write_bytes(backup)

    rates = {f: (counters[f]["match"] / counters[f]["total"] if counters[f]["total"] else None)
             for f in fields}
    artifact = {
        "schema_version": "parity-monolith-vs-package-v1",
        "dates_compared": dates_compared,
        "match_rates": rates,
        "counters": counters,
        "n_divergences": len([d for d in divergences if "field" in d]),
        "divergences": divergences,
        "caveat": "V1: inputs from each system's own loader; byte-identical bridge is T1-T4.",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "Parity_Monolith_vs_Package.json").write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_md(artifact, OUT_DIR / "Parity_Monolith_vs_Package.md")
    return artifact


def _write_md(a: Dict[str, Any], path: Path) -> None:
    lines = ["# Parity — Monolith vs Package (T5 V1)", ""]
    lines.append(f"Dates compared: {len(a['dates_compared'])} ({', '.join(a['dates_compared'])})")
    lines.append("")
    lines.append("| Field | Match rate | matched/total |")
    lines.append("|---|---:|---:|")
    for f, r in a["match_rates"].items():
        c = a["counters"][f]
        rate = "n/a" if r is None else f"{r*100:.1f}%"
        lines.append(f"| {f} | {rate} | {c['match']}/{c['total']} |")
    lines.append("")
    lines.append(f"Total field divergences: **{a['n_divergences']}**")
    lines.append("")
    lines.append(f"> {a['caveat']}")
    diffs = [d for d in a["divergences"] if "field" in d]
    if diffs:
        lines.append("")
        lines.append("## Divergences (first 40)")
        lines.append("| date | symbol | field | monolith | package |")
        lines.append("|---|---|---|---|---|")
        for d in diffs[:40]:
            lines.append(f"| {d['date']} | {d['symbol']} | {d['field']} | {d['monolith']} | {d['package']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    art = run()
    print(json.dumps({"match_rates": art["match_rates"], "n_divergences": art["n_divergences"],
                      "dates": len(art["dates_compared"])}, ensure_ascii=False))
