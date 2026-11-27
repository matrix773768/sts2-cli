"""Compare the frozen C encoding on public fields translated from independent Hot turns."""
from collections import Counter,defaultdict,deque
from copy import deepcopy
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from campaign import E,HERE,LOG,ROOT,RUNS

def overlay(core,hot):
    c=deepcopy(core)
    if hot is None:return None,"missing_hook"
    for key in ("turn","hp","max_hp","block","energy","stars","draw_count"):c[key]=hot[key]
    c["setup"]["draw"]=hot["draw"]
    for name in ("hand","discard","exhaust"):
        by_type=defaultdict(deque)
        for row in core[name]:by_type[row["id"]+"#"+str(row["upgrade"])].append(row)
        tokens=hot[name]
        if Counter(tokens)!=Counter({k:len(v) for k,v in by_type.items()}):return None,"zone/"+name
        # CORE C canonicalizes non-hand zones. Preserve metadata for equal visible copies.
        if name!="hand":tokens=[row["id"]+"#"+str(row["upgrade"]) for row in core[name]]
        c[name]=[by_type[k].popleft()|dict(index=i) for i,k in enumerate(tokens)]
    def powers(public,raw):
        # The CORE visibility list is the whitelist. Unpublished Hot listeners stay in the audit.
        available=defaultdict(deque)
        for p in raw:available[p["id"]].append(p["amount"])
        result=[]
        for p in public:
            if not available[p["id"]]:raise KeyError(p["id"])
            result.append(p|dict(amount=available[p["id"]].popleft()))
        return result
    try:
        c["powers"]=powers(core["powers"],hot["powers"])
        if len(c["enemies"])!=len(hot["enemies"]):return None,"enemy_roster"
        for enemy,src in zip(c["enemies"],hot["enemies"],strict=True):
            if (enemy["slot"],enemy["species"])!=(src["slot"],src["species"]):return None,"enemy_identity"
            for k in ("hp","max_hp","block"):enemy[k]=src[k]
            enemy["powers"]=powers(enemy["powers"],src["powers"])
            if src["move"] is None and enemy.get("move") is not None:return None,"move_unavailable"
            enemy["move"]=src["move"]
            if enemy.get("phase"):enemy["phase"]["node"]=src["move"]
    except KeyError as e:return None,"power/"+str(e.args[0])
    return c,None

def run(tag,version="kernel5"):
    import numpy as np
    os.environ.update(INFRA1H_AUDIT_WORLD="1",INFRA1H_C_RECEIPTS="1",STS2_CORE5C_HOST=str(ROOT/"logs"/("infra1h-5d-"+version)))
    sys.path.insert(0,str(HERE.parent/"m1-core5d"))
    import battle5d
    from panel5d import cohort
    from semantic import encode
    from search5 import Evaluator
    worker=RUNS/tag/"worker-0"
    assert json.loads((worker/"verification.json").read_bytes())["equal"]
    meta=json.loads((worker/"worker.json").read_bytes())
    rows=list(map(json.loads,gzip.open(worker/"evidence"/meta["closed"]["file"])))
    panel=json.load(gzip.open(HERE.parent/"m1-core5d/evidence/panel.gz"))["train"]
    out=LOG/("c-model-"+str(os.getpid()));out.mkdir()
    host,_,net,_=battle5d.configure(out,"V2")
    lane=battle5d.Lane(host,0)
    try:
        for row in rows:
            st=cohort.start(lane,panel[row["i"]]["spec"])
            for turn,i in row["trace"]:
                assert st["observation"]["turn"]==turn
                st=cohort.step(lane,st,i)
            assert st["status"]==row["status"]
            lane.reset()
    finally:lane.close();host.close()
    # This lane is one process. Assert root index directly against the production C payload.
    files=list(out.rglob("infra1h-c.jsonl"))
    if len(files)!=1:raise ValueError(("expected one Hot C stream",files))
    values=Evaluator(net)
    records=[];stats=Counter();coverage=Counter()
    for line in files[0].read_text().splitlines():
        log=json.loads(line);row=rows[log["root"]];core=log["core"];hot=log["hot"]
        if core not in row["states"]:raise ValueError(("C is absent from deployed experience",row["i"]))
        c,reason=overlay(core,hot)
        rec=dict(i=row["i"],step=log["steps"],turn=core["turn"],hot=hot,reason=reason)
        if reason:coverage[reason]+=1
        else:
            opening=panel[row["i"]]["spec"]
            a,b=encode(core),encode(c)
            def hashes(x):return [sha256(v.tobytes()).hexdigest() for v in x]
            shape_equal=all(x.shape==y.shape for x,y in zip(a,b))
            equal=shape_equal and all(np.array_equal(x,y) for x,y in zip(a,b))
            left=values({"c":core},opening)["c"]
            right=values({"c":c},opening)["c"]
            rec.update(reference=hashes(a),candidate=hashes(b),equal=equal,reference_value=left,candidate_value=right)
            stats["compared"]+=1;stats["exact_tensor"]+=equal;stats["exact_value"]+=left==right
            if not equal:rec["changed_fields"]=[k for k in core if core[k]!=c[k]]
        records.append(rec)
    if not records:raise ValueError("No C receipts")
    with gzip.open(E/("c-model.json.gz" if version=="kernel5" else "c-model-"+version+".json.gz"),"wt",encoding="utf8") as f:
        json.dump(dict(source=tag,roots=len(rows),production_C=sum(len(x["states"]) for x in rows),stats=stats,abstained=coverage,rows=records),f)
    events=[json.loads(line) for f in out.rglob("infra1h-private.jsonl") for line in f.read_text().splitlines()]
    if version!="kernel5":(E/("private-"+version+".json")).write_text(json.dumps(events))
    print("C hook",len(records),dict(stats),dict(coverage))
if __name__=="__main__":run(*sys.argv[1:])
