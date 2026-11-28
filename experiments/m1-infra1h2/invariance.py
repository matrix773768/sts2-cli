"""Keep the public wire fixed while independently changing live seed, dealt order and UID allocation."""
import hashlib
import json
from pathlib import Path
from native_h2 import ROOT,HERE,inputs,host_at,battle5d,cohort
from lane import BranchLane
from complete import Planner
def digest(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
def run():
    rows,panel=inputs();spec=panel[rows[0]["i"]]["spec"]
    out=ROOT/"logs/infra1h2/fair";out.mkdir(exist_ok=True)
    original,g2,net,_=battle5d.configure(out,"V2");original.close()
    host=host_at(out,ROOT/"logs/infra1h2/5d-batch");lane=battle5d.Lane(host,0)
    variants=[];public=None
    try:
        for seed,deck,uid in [(spec["seed"],spec["deck"],1),("324FD1CF986E4B77",list(reversed(spec["deck"])),700),
                               ("24801AD235BBCAFE",spec["deck"][1:]+spec["deck"][:1],1300)]:
            actual=cohort.start(lane,spec|dict(seed=seed,deck=deck))["observation"]
            if public is None:public=actual
            b=BranchLane(lane,public,spec,audit_uid_base=uid)
            try:
                sibling=b.rpc("advance",parent=b.node,slot=2,target=-1,inputs=[])
                first=b.rpc("advance",parent=b.node,slot=0,target=0,inputs=[])
                assert b.rpc("release",node=first["node"])["released"]
                stale=lane.request("i1_h2_branch",op="advance",parent=first["node"],slot=-1,target=-1,inputs=[])["result"]
                repeated=b.rpc("advance",parent=b.node,slot=2,target=-1,inputs=[])
                safe=stale["kind"]=="unsupported" and sibling["facts"]==repeated["facts"]
                assert safe
                graph=b.request("i1_core1r2",mode="reduced",budget=512)
                plan=Planner(net);plan.detail=True
                _,chosen,q=plan(b,host.project(public),[],net,g2,spec)
                semantics=dict(graph=graph,chosen=chosen,q=q,
                    states=plan.last.states,cache={repr(k):v for k,v in plan.last.cache.items()})
                variants.append(dict(seed=seed,uid_base=uid,actual_hand=digest(actual["hand"]),
                                     sibling_release=safe,public_root=digest(public),outputs=digest(semantics),nodes=len(graph["nodes"])))
            finally:b.close();lane.reset()
    finally:lane.close();host.close()
    ok=len({x["outputs"] for x in variants})==1 and len({x["actual_hand"] for x in variants})==3
    (HERE/"evidence/invariance.json").write_text(json.dumps(dict(equal=ok,rows=variants),indent=2))
    if not ok:raise ValueError("Public invariance failed")
if __name__=="__main__":run()
