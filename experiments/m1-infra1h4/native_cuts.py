"""Triangulate the original 33 tensor discrepancies at native DrawInternal(fromHandDraw)."""
import gzip
import json
import os
from pathlib import Path
import sys
import time
from diagnose import ROOT,HERE
sys.path.insert(0,str(ROOT))
from engine.HotSearch.native_audit import native
from hot_produce import public_b
from models import strategic
from client import Client
from release import pack

def fields(c):
    result={"hp":c["hp"],"max_hp":c["max_hp"],"draw_count":c["draw_count"]}
    for z in ("hand","discard","exhaust"):
        cards=c["card_state"][z] if "card_state" in c else c[z]
        pairs=[(r["type"],r["cost"]) for r in cards]
        result[z]=sorted(pairs)
        # Preserve occurrence order within a type, including duplicate cost variants.
        result[z+"_order"]=pairs if z=="hand" else sorted(pairs,key=lambda pair:pair[0])
    result["living"]=sorted((e["species"],e["hp"]) for e in c["enemies"] if e["hp"]>0)
    return result

def audit(out):
    os.environ["HOTSEARCH_NATIVE_CUTS"]="1"
    out.mkdir(exist_ok=False,parents=True)
    wanted={}
    for r in json.load(gzip.open(HERE/"evidence/h3-tensors.json.gz"))["mismatches"]:
        wanted.setdefault(r["i"],set()).add(r["turn"])
    specs=json.load(gzip.open(ROOT/"experiments/m1-core5d/evidence/panel.gz"))["train"]
    old={r["i"]:r for p in (ROOT/"experiments/m1-core5d/evidence").glob("train-V2-*.gz") for r in map(json.loads,gzip.open(p))}
    hot=Client(out/"transport");evidence=[];start=time.perf_counter()
    try:
        for i,turns in wanted.items():
            game=native(out);source=old[i];spec=specs[i]["spec"];index=0;chosen=None
            stopped=None;seen=set()
            try:
                st=hot.call("open",spec=spec);ns=game.send(dict(cmd="synthetic_start",spec=spec))
                for turn,action in source["trace"]:
                    if st["status"]=="choice":
                        if chosen is None:chosen=action;continue
                        if action!=0 or ns.get("decision")!="card_select":raise ValueError("choice confirmation")
                        action=chosen;chosen=None;menu=st["options"]
                        if menu[action]=="skip":command=dict(action="skip_select",args={})
                        else:
                            opts=[r["id"].split(".")[-1]+"#"+str(int(r.get("upgraded",False))) for r in ns["cards"]]
                            if opts!=[o for o in menu if o!="skip"]:raise ValueError("native choice menu")
                            command=dict(action="select_cards",args={"indices":str(action-menu[:action].count("skip"))})
                    else:
                        if ns.get("decision")!="combat_play" or st["status"]!="active":raise ValueError("phase")
                        f=st["facts"];a=public_b(f)["actions"][action]
                        hand=[(c["id"].split(".")[-1],int(c["upgraded"])) for c in ns["hand"]]
                        if hand!=[(c["id"],c["upgrade"]) for c in f["hand"]]:raise ValueError("different hand before action")
                        args={} if a["card"] is None else dict(card_index=a["card"])
                        if a["target"] is not None:args["ally_index" if a["target_side"]=="ally" else "target_index"]=a["target"]
                        command=dict(action=a["kind"],args=args)
                    ns=game.send(dict(cmd="action",**command))
                    st=hot.call("step",index=action)
                    if st.get("observed_c"):
                        cut=st["observed_c"];actual=strategic(cut["facts"],cut["draw"])
                        prev=source["states"][index];index+=1;t=actual["turn"]
                        if t in turns:
                            rec=dict(i=i,turn=t,hot=fields(actual),frozen=fields(prev),status="native_hook_missing")
                            if ns.get("native_c"):
                                real=rec["native"]=fields(ns["native_c"]);rec["status"]="observed"
                                rec["differing_fields"]={k:("hot" if real[k]==v else "frozen" if real[k]==rec["frozen"][k] else "neither")
                                    for k,v in rec["hot"].items() if v!=rec["frozen"][k]}
                            evidence.append(rec);seen.add(t)
                    if seen==turns:break
            except (ValueError,KeyError,RuntimeError,IndexError,TimeoutError) as e:stopped=str(e)[:240]
            finally:game.close(graceful=False)
            for t in turns-seen:evidence.append(dict(i=i,turn=t,status="unreached",reason=stopped or "trace ended"))
    finally:hot.close()
    pack(out/"cuts.jsonl.gz",evidence)
    (out/"wall.json").write_text(json.dumps(time.perf_counter()-start))
if __name__=="__main__":audit(Path(sys.argv[1]))
