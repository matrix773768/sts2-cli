"""Run independent edges first, then compare to the frozen predictor. Never use a sibling answer as input."""
from collections import Counter
import gzip
import json
import os
from time import perf_counter
from native_h2 import HERE,ROOT,inputs,battle5d,cohort
from complete import host_at
from lane import BranchLane, Unsupported
from search5 import reference, Evaluator
from semantic import encode
import numpy as np

def delta(a,b,path=""):
    if a==b:return []
    if isinstance(a,dict) and isinstance(b,dict):
        return [d for k in sorted(a.keys()|b.keys()) for d in delta(a.get(k),b.get(k),path+"/"+k)]
    if isinstance(a,(list,tuple)) and isinstance(b,(list,tuple)) and len(a)==len(b):
        return [d for i,(x,y) in enumerate(zip(a,b)) for d in delta(x,y,path+"/"+str(i))]
    return [(path,str(a)[:140],str(b)[:140])]

def run(full):
    rows,panel=inputs()
    os.environ.update(STS2_CORE5C_HOST=str(ROOT/"logs/infra1h2/5d"),INFRA1H_AUDIT_WORLD="1")
    out=ROOT/"logs/infra1h2"/("check-"+str(os.getpid()))
    out.mkdir()
    host,g2,net,_=battle5d.configure(out,"V2")
    host.close()
    host=host_at(out, ROOT/"logs/infra1h2"/("5d" if full else "5d-batch"))
    values=Evaluator(net)
    lane=battle5d.Lane(host,0); attempts=[]; checks=[]
    try:
        for ordinal,row in enumerate(rows):
            spec=panel[row["i"]]["spec"]
            if not full and spec["encounter"]!="MECHA_KNIGHT_ELITE":continue
            before=perf_counter()
            st=cohort.start(lane,spec)
            wire=st["observation"]
            if spec["encounter"]=="MECHA_KNIGHT_ELITE":
                (out/f"opening-{ordinal}.json").write_text(json.dumps(wire))
                attempt=dict(ordinal=ordinal,i=row["i"]);attempts.append(attempt)
                try:
                    b=BranchLane(lane,wire,spec)
                    for a in wire["actions"]:
                        route=[dict(action=a["index"],draws=[])]
                        rec=dict(ordinal=ordinal,route=route);checks.append(rec)
                        try:
                            hot=b.request("i1_core5_reference",route=route,complete=True)["response"]
                            old=lane.request("i1_core5_reference",route=route,complete=True)["response"]
                            candidate={k:v for k,v in hot.items() if k!="calls"}
                            baseline={k:v for k,v in old.items() if k!="calls"}
                            rec.update(kind=hot["kind"],delta=delta(candidate,baseline)[:15],equal=candidate==baseline)
                            if candidate["kind"]==baseline["kind"]=="C":
                                x,y=candidate["state"],baseline["state"]
                                rec["tensor_equal"]=all(np.array_equal(m,n) for m,n in zip(encode(x),encode(y)))
                                rec["value_equal"]=values({"x":x},spec)["x"]==values({"y":y},spec)["y"]
                            if hot["kind"]=="decision":
                                idx=len(hot["state"]["actions"])-1
                                follow=route+[dict(action=idx,draws=[])]
                                r=b.request("i1_core5_reference",route=follow,complete=True)["response"]
                                o=lane.request("i1_core5_reference",route=follow,complete=True)["response"]
                                rc={k:v for k,v in r.items() if k!="calls"}
                                oc={k:v for k,v in o.items() if k!="calls"}
                                rec.update(follow_kind=r["kind"],follow_equal=rc==oc,follow_delta=delta(rc,oc)[:8])
                            if hot["kind"]=="R":
                                children=[]
                                for name in sorted(hot["support"]):
                                    follow=[dict(action=a["index"],draws=[name])]
                                    r=b.request("i1_core5_reference",route=follow,complete=True)["response"]
                                    o=lane.request("i1_core5_reference",route=follow,complete=True)["response"]
                                    d=delta({k:v for k,v in r.items() if k!="calls"},{k:v for k,v in o.items() if k!="calls"})
                                    children.append(dict(name=name,kind=r["kind"],delta=d[:3]))
                                rec["children"]=children
                        except Unsupported as e:rec["stop"]=str(e)
                    b.close()
                    b=BranchLane(lane,wire,spec)
                    lane.request("i1_core5_reference",clear=True)
                    history=[];h=host.project(wire)
                    hs=perf_counter()
                    try:
                        hot=reference(b,h,history,g2,limit=256)
                        attempt["hot_seconds"]=perf_counter()-hs
                        old=reference(lane,h,history,g2,limit=256)
                        def semantics(result):
                            leaves,calls,first=result
                            return [first,[{k:v for k,v in l.items() if k!="calls"} for l in leaves]]
                        attempt.update(reference_equal=semantics(hot)==semantics(old),calls=[hot[1],old[1]],
                            leaves=dict(Counter(l["kind"] for l in hot[0])),strict_g2=True)
                    finally:
                        attempt["physical"]=dict(b.physical)
                        b.close()
                except Unsupported as e:attempt["stop"]=str(e)
                lane.request("i1_core5_reference",clear=True)
                attempt["seconds"]=perf_counter()-before
            if full:
                for turn,i in row["trace"]:st=cohort.step(lane,st,i)
                assert st["status"]==row["status"]
            lane.reset()
    finally:lane.close();host.close()
    evidence=HERE/"evidence"
    (evidence/"branches.json").write_text(json.dumps(dict(roots=attempts,edges=checks),indent=2))
    if full:
        events=[json.loads(line) for f in out.rglob("infra1h-private.jsonl") for line in f.read_text().splitlines()]
        (evidence/"private.json").write_text(json.dumps(events,separators=(",",":")))
    print(out,len(attempts),len(checks))
if __name__=="__main__":
    import sys
    run("--full" in sys.argv)
