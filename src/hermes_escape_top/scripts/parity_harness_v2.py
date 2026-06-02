"""T5-V2 — Same-input parity harness (fixture-fed both sides).

Feeds BOTH the monolith (via golden_utils sandbox) and the package
(via score_symbol) from the exact same daily_raw_data fixture, eliminating
the input-difference caveat of V1. Compares hard-valve ids, status, sell%.

Usage:
    cd <escape-top>
    PYTHONPATH=. python hermes_escape_top/scripts/parity_harness_v2.py

Writes: hermes_escape_top/reports/Parity_V2_SameInput.{json,md}
"""
from __future__ import annotations
import json, sys
from datetime import date as dt
from pathlib import Path

BASE = Path(__file__).resolve().parents[3]
GOLDEN_DIR = BASE / "tests" / "golden"
FIXTURE_DIR = GOLDEN_DIR / "fixtures"
OUT = Path(__file__).resolve().parents[1] / "reports"
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(GOLDEN_DIR))

import golden_utils as gu
from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.scoring.scorer import score_symbol
from hermes_escape_top.config import load_config

TRADE = ["MSTR","FNGU","SOXL"]
ALL_SYMS = TRADE + ["QQQ","SPY","^VIX","^VIX3M","BTC-USD","FNGS","SOXX","SMH","^NYFANG","^SOX"]
# Monolith flat market key -> package SOFT.* field name
SOFT_BRIDGE = {
    "aaii_bull":"aaii_bull","aaii_neutral":"aaii_neutral","aaii_bear":"aaii_bear",
    "cboe_equity_pcr":"equity_pcr","naaim":"naaim_exposure",
    "ndx_breadth_50dma":"aggregate_pct_above_50dma",
    "ndx_breadth_200dma":"aggregate_pct_above_200dma",
    "ndx_breadth_50dma_delta_10d":"aggregate_breadth_chg_5d",
}

def _build_snaps(ds, aod):
    snaps = {}
    for sym in ALL_SYMS:
        src = ds["symbols"].get(sym) or ds["market"].get(sym) or ds["market"].get(sym.lstrip("^"))
        if not isinstance(src, dict): continue
        flds = {}
        for k,v in src.items():
            if isinstance(v,(int,float)) and v==v: flds[k]=Field(k,float(v),"fixture",aod)
        rw=src.get("rsi14_weekly")
        if rw: flds["rsi14_weekly"]=Field("rsi14_weekly",float(rw),"fixture",aod)
        for rs,rd in (src.get("radar") or {}).items():
            if isinstance(rd,dict):
                for k,v in rd.items():
                    if isinstance(v,(int,float)) and v==v: flds[f"{rs}.{k}"]=Field(f"{rs}.{k}",float(v),"fixture",aod)
        av=src.get("estimated_avwap_20d")
        if av: flds["avwap_anchored_20d"]=Field("avwap_anchored_20d",float(av),"fixture",aod)
        sp=src.get("platform_support_level")
        if sp: flds["support_20d_low"]=Field("support_20d_low",float(sp),"fixture",aod)
        snaps[sym]=SymbolSnapshot(sym,aod,flds)
    sf = {}
    for mk,pk in SOFT_BRIDGE.items():
        v=ds["market"].get(mk)
        if isinstance(v,(int,float)) and v==v: sf[pk]=Field(pk,float(v),"fixture",aod)
    snaps["SOFT"]=SymbolSnapshot("SOFT",aod,sf)
    return snaps

def run():
    ets=gu.load_escape_module(); gu.install_fixture_environment(ets)
    state=ets.read_json(FIXTURE_DIR/"state.json",default={})
    config=load_config()
    FIELDS=["hard_ids","status","sell_pct"]
    counts={f:{"m":0,"t":0} for f in FIELDS}
    divs=[]; dates=[]
    for rp in sorted(FIXTURE_DIR.glob("daily_raw_data_*.json")):
        raw=ets.read_json(rp); ds=ets.build_dataset(raw,state)
        aod=dt.fromisoformat(str(ds["as_of"])[:10])
        dates.append(str(aod))
        am=ets.score_market(ds["market"],ds["market"]["QQQ"])
        hh=ets.hard_trigger_history_context()
        snaps=_build_snaps(ds,aod)
        for sym in TRADE:
            mr=ets.score_symbol(sym,ds,am,histories=hh)
            ht=mr.get("hard_trigger",{}) or {}
            mono={"status":mr.get("status"),"sell_pct":mr.get("sell_pct"),
                  "hard_ids":sorted((ht.get("hard_ids") or ht.get("ids") or []))}
            b=score_symbol(sym,snaps,config); r=b.result
            pkg={"status":r.status,"sell_pct":round(float(r.sell_fraction or 0)*100,2),
                 "hard_ids":sorted(r.hard_valve_hits or [])}
            for f in FIELDS:
                counts[f]["t"]+=1
                if mono[f]==pkg[f]: counts[f]["m"]+=1
                else: divs.append({"date":str(aod),"sym":sym,"field":f,"mono":mono[f],"pkg":pkg[f]})
    rates={f:counts[f]["m"]/counts[f]["t"] if counts[f]["t"] else None for f in FIELDS}
    art={"schema_version":"parity-v2-same-input","dates":dates,"match_rates":rates,"counters":counts,
         "n_divergences":len(divs),"divergences":divs}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"Parity_V2_SameInput.json").write_text(json.dumps(art,ensure_ascii=False,indent=2)+"\n")
    lines=["# Parity V2 — Same-Input (fixture-fed both sides)","",
           f"Dates: {len(dates)} ({', '.join(dates)})","",
           "| Field | Match | matched/total |","|---|---:|---:|"]
    for f,r in rates.items():
        c=counts[f]
        lines.append(f"| {f} | {'n/a' if r is None else f'{r*100:.1f}%'} | {c['m']}/{c['t']} |")
    lines.extend(["",f"Divergences: **{len(divs)}**",""])
    if divs:
        lines+=["| date | sym | field | mono | pkg |","|---|---|---|---|---|"]
        for d in divs: lines.append(f"| {d['date']} | {d['sym']} | {d['field']} | {d['mono']} | {d['pkg']} |")
    (OUT/"Parity_V2_SameInput.md").write_text("\n".join(lines)+"\n")
    return art

if __name__=="__main__":
    a=run()
    print(json.dumps({"match_rates":a["match_rates"],"n_divergences":a["n_divergences"]},ensure_ascii=False))
