"""Re-evaluate every selected closed tactical program from physical host replies and seal its leaves."""
from collections import defaultdict
import json
from math import isclose
from pathlib import Path
from diagnose import ROOT
from models import Models,boundary_key,strategic
from release import pack,rows

def audit():
    folder=ROOT/"logs/hotsearch-h4/post-fix96";out=folder.parent/"closed-laws-batches"
    out.mkdir(exist_ok=False)
    source=rows(folder/"natural.jsonl.gz")
    wanted=defaultdict(list);done={};states={}
    for r in source:
        for q in r["queries"]:
            if "policy" in q:
                root,=[e for e in q["policy"] if not e["parent"]]
                wanted[root["view"],root["index"]].append((r,q))
    models=Models()
    for f in sorted((folder/"transport").glob("*/stdout.log")):
        with f.open("rb") as lines,(f.parent/"commands.jsonl").open("rb") as cmds:
            requests=(c for c in map(json.loads,cmds) if c["op"]!="g2")
            for cmd,line in zip(requests,(s for s in lines if s.startswith(b'{"type":"hot"'))):
                if cmd["op"]=="open":
                    opening={k:cmd["spec"][k] for k in ("hp","max_hp")}
                if cmd["op"]!="search":continue
                graphs=json.loads(line)["result"]
                values=models.backup(graphs,opening,annotate=True)
                for graph,result in zip(graphs,values):
                    edges=graph["policy"]
                    if not edges or graph["gaps"]:continue
                    first=edges[0]
                    for r,q in wanted.get((first["view"],first["index"]),[]):
                        ident=(r["i"],q["turn"])
                        if ident in done or q["policy"]!=edges:continue
                        if q["committed"] and q["winner_style"]!=cmd.get("style"):continue
                        if not q["committed"] and not cmd.get("g2"):continue
                        ends=[];mass=defaultdict(float)
                        for leaf in graph["leaves"]:
                            kind=leaf["kind"]
                            state=strategic(leaf["facts"],leaf["draw"]) if kind=="C" else {k:leaf[k] for k in ("hp","max_hp","gold")}
                            key=boundary_key(kind,state)
                            mass[key]+=leaf["mass"];ends.append(key)
                            states[key]=dict(key=key,kind=kind,state=state)
                        if dict(mass)!=q["law"]:continue
                        target=max(o["value"] for o in q["options"] if o["value"] is not None) if q["committed"] else q["reference_law"]["value"]
                        if result["value"]!=target:raise ValueError(("frozen valuation",ident,result["value"],target))
                        done[ident]=dict(i=r["i"],turn=q["turn"],value=result["value"],evaluated_value=target,
                            leaves=[dict(key=k,mass=l["mass"],cursor=l["cursor"],value=l["evaluated"]) for k,l in zip(ends,graph["leaves"])])
    if len(done)!=sum(map(len,wanted.values())):raise ValueError(("missing selected law",len(done),sum(map(len,wanted.values()))))
    pack(out/"laws.jsonl.gz",done.values())
    pack(out/"states.jsonl.gz",states.values())
    print(len(done),len(states))
if __name__=="__main__":audit()
