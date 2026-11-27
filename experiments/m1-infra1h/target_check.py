"""Direct differential for bound attack-draw and lethal finishes on ordinary generated roots."""
import json
import os
import sys
from hashlib import sha256
from campaign import E,HERE,LOG,ROOT

def run():
    sys.path.insert(0,str(HERE.parent/"m1-core5d"))
    import battle5d
    from complete import host_at
    from panel5d import cohort
    from turn_worlds import source
    base=source("rescue")["spec"]|dict(hp=150,max_hp=150,relics=[])
    decks={"draw":["POMMEL_STRIKE","STRIKE_IRONCLAD","DEFEND_IRONCLAD","BASH","STRIKE_IRONCLAD",
                   "DEFEND_IRONCLAD","STRIKE_IRONCLAD","BASH","DEFEND_IRONCLAD","STRIKE_IRONCLAD"],
           "finish":["STRIKE_IRONCLAD","STRIKE_IRONCLAD","STRIKE_IRONCLAD","TWIN_STRIKE","BASH"]*3}
    root=LOG/("target-"+str(os.getpid()))
    traces={};replies={}
    for version in ("core5c-host","infra1h-5d-kernel6"):
        out=root/version;out.mkdir(parents=True)
        host=host_at(out,ROOT/"logs"/version);lane=battle5d.Lane(host,0)
        traces[version]={};replies[version]={}
        try:
            for name,deck in decks.items():
                spec=base|dict(deck=[dict(id=c,upgrade=1) for c in deck])
                st=cohort.start(lane,spec,list(range(len(deck))))
                rows=[];kinds=[]
                while st["status"]=="active" and len(rows)<110:
                    h=host.project(st["observation"])
                    attacks=[a for a in h["actions"] if a["kind"]=="play_card" and a.get("target") is not None]
                    if name=="draw" and not rows:a=next(a for a in attacks if h["hand"][a["card"]]["id"]=="POMMEL_STRIKE")
                    else:a=next(iter(attacks),next(a for a in h["actions"] if a["kind"]=="end_turn"))
                    raw=lane.request("i1_core5_reference",complete=True,route=[dict(action=a["index"],draws=[])])["response"]
                    rows.append(sha256(json.dumps(raw,sort_keys=True,separators=(",",":")).encode()).hexdigest());kinds.append(raw["kind"])
                    st=cohort.step(lane,st,a["index"])
                    if name=="draw":break
                traces[version][name]=rows;replies[version][name]=kinds
                lane.reset()
        finally:lane.close();host.close()
    counters=json.loads(next((root/"infra1h-5d-kernel6").rglob("infra1h-engine.json")).read_bytes())
    same=traces["core5c-host"]==traces["infra1h-5d-kernel6"]
    (E/"target-check.json").write_text(json.dumps(dict(equal=same,queries=traces,kinds=replies,hot=counters),indent=2))
    if not same:raise ValueError("Bound attack changed the reference reply")
    print(same,counters["TargetDraws"],counters["HotFinishes"])
if __name__=="__main__":run()
