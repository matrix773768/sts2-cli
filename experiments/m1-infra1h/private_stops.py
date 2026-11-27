"""Resolve first private shadow divergences back to the public production move."""
from collections import Counter
import gzip
import json
import os
from pathlib import Path
import sys
from campaign import E,HERE,LOG,ROOT,RUNS

def run():
    sys.path.insert(0,str(HERE.parent/"m1-core5d"))
    import battle5d
    from panel5d import cohort
    from complete import host_at
    tag="infra1h-B-natural-h-kernel3"
    w=RUNS/tag/"worker-0";meta=json.loads((w/"worker.json").read_bytes())
    rows=list(map(json.loads,gzip.open(w/"evidence"/meta["closed"]["file"])))
    logs=list((RUNS/"infra1h-diag-natural-h-kernel4").rglob("infra1h-private.jsonl"))
    assert len(logs)==1
    events=[json.loads(s) for s in logs[0].read_text().splitlines()]
    stops=[s for s in events if s["stage"]=="stop"]
    panel=json.load(gzip.open(HERE.parent/"m1-core5d/evidence/panel.gz"))["train"]
    out=LOG/("stops-"+str(os.getpid()));out.mkdir()
    host=host_at(out,ROOT/"logs/infra1h-5d-kernel5");lane=battle5d.Lane(host,0)
    results=[]
    try:
        for stop in stops:
            r=rows[stop["root"]];spec=panel[r["i"]]["spec"]
            n=stop["steps"];st=cohort.start(lane,spec)
            for turn,i in r["trace"][:n]:
                h=host.project(st["observation"]);a=h["actions"][i]
                assert turn==h["turn"]
                st=cohort.step(lane,st,i)
            result=dict(i=r["i"],step=n,turn=turn,encounter=spec["encounter"],why=stop["detail"],action=a["kind"])
            if a["kind"]=="play_card":result["card"]=h["hand"][a["card"]]["id"]
            if st.get("observation"):
                menu=st["observation"]["decision"]
                if "candidates" in menu:result["pending"]=dict(effect=menu["effect"],ids=[c["id"]+"#"+str(c["upgrade"]) for c in menu["candidates"]])
            results.append(result);lane.reset()
    finally:lane.close();host.close()
    (E/"private-stops.json").write_text(json.dumps(results,indent=2))
    print(Counter((r["why"].split("/")[0],r.get("card",r["action"])) for r in results))
if __name__=="__main__":run()
