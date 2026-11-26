"""Compare live actors and public trees across seeds before a later draw is revealed."""
import json
from pathlib import Path
import sys
from time import perf_counter

from arena import CFG, PARENT, ROOT, Host, Policy, Controller, digest, load, manifest, project
from learn import restore


def check(out):
    out.mkdir(parents=True,exist_ok=False)
    start=perf_counter()
    host=Host(out,ROOT/"logs/n1bc-host",CFG)
    base=host.project
    host.project=lambda wire:project(base,wire)
    _,meta=load(PARENT)
    model=Policy(PARENT,meta["deployment"],24,0.,host.version,CFG)
    model.net,model.encoder,model.slot=restore(ROOT/"logs/n1bc-clean-wide/model.pt")
    spec=next(j[1] for j in manifest()["jobs"] if j[1]["encounter"]=="TERROR_EEL_ELITE")
    spec=spec | dict(deck=[dict(id=n,upgrade=0) for n in ["STRIKE_IRONCLAD"]*14+["DEFEND_IRONCLAD"]*4],
                     hp=80,max_hp=80)
    rows=[]
    try:
        for i in range(48):
            lane=host.lane()
            lane.open()
            seed=digest(["n1bc-fair",i])[:16].upper()
            wire=lane.request("pre0_start",spec=spec | dict(seed=seed),cap=128)["episode"]["observation"]
            root=host.project(wire)
            action=next(a for a in root["actions"] if a["kind"]=="play_card")
            index=action["index"]
            after=host.project(lane.request("i1_n2_step",index=index,position=0)["episode"]["observation"])
            c=Controller(model,host.project,lambda rows:next(model.forward([(rows,)])),None)
            c.initial_hp,c.initial_max=root["hp"],root["max_hp"]
            c.history=model.encoder.update(c.history,root,action)
            scores=c.score([(after,c.history)])[0][0]
            graph=lane.request("i1_sv1_graph",mode="tree",public_run=True,transitions=24,wall_ms=1500,
                               depth=8,memory_bytes=512*2**20)
            if graph.get("stop") in ("wall_cap","managed_memory_cap"):
                raise ValueError("Graph resource stop")
            chosen,_=c.search(after,lane,1)
            end=next(a["index"] for a in after["actions"] if a["kind"]=="end_turn")
            revealed=host.project(lane.request("i1_n2_step",index=end,position=1)["episode"]["observation"])
            rows.append(dict(seed=seed,history=digest([root,action,after]),score=digest(scores.tolist()),
                             direct=int(scores.argmax()),search=chosen,graph=digest({k:graph[k] for k in
                             ("observations","edges","boundaries","transitions","nodes","stop")}),
                             next_hand=[c["id"] for c in revealed["hand"]]))
            lane.reset()
    finally:
        host.close()
    pairs=[(a,b) for i,a in enumerate(rows) for b in rows[:i] if a["history"]==b["history"] and a["next_hand"]!=b["next_hand"]]
    passed=sum(all(a[k]==b[k] for k in ("score","direct","search","graph")) for a,b in pairs)
    result=dict(seconds=perf_counter()-start,worlds=rows,paired=len(pairs),identical=passed,recipe=spec)
    (out/"fairness.json").write_text(json.dumps(result,indent=2))
    if not pairs or passed!=len(pairs):
        raise ValueError("Private-world invariance not demonstrated")


if __name__=="__main__":
    check(Path(sys.argv[1]))
