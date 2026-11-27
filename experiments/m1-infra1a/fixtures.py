"""Replay scalar reference transcripts as bounded batches before each real state change."""
from collections import Counter
import gzip
import json
import os
import sys
from common import HERE, ROOT, OLD, E, charged
from semantic_check import digest
from execution import COMMAND

def queue_contract():
    import numpy as np
    import search5
    from types import SimpleNamespace
    from unittest.mock import patch
    from execution import reference
    root=dict(actions=[dict(kind="end")])
    model=SimpleNamespace(encoder=SimpleNamespace(update=lambda hist,o,a:hist+[a["kind"]]))
    control=SimpleNamespace(history=[],score=lambda requests:[(np.array([1.]),None) for _ in requests])
    class Lane:
        host=SimpleNamespace(project=lambda o:o)
        def __init__(self):self.routes=[]
        def read(self,r):
            self.routes.append(r)
            if len(r)==1 and not r[0]["draws"]:return dict(kind="R",support={"z":1,"x":3,"y":2},calls=1)
            if len(r)==1:return dict(kind="decision",state=root,calls=1)
            return dict(kind="victory",state={"hp":1,"max_hp":2},calls=1)
        def request(self,cmd,**kw):
            if cmd==COMMAND:return dict(results=[self.read(x["route"]) for x in kw["requests"]])
            return dict(response=self.read(kw["route"]))
    cases=0
    with patch.object(search5,"prepared",lambda *args:control):
        for limit in (0,1,2,3,4,5,6,7,8,32):
            for used in (0,127):
                scalar,batch=Lane(),Lane()
                args=(root,[None]*used,model,limit)
                assert search5.reference(scalar,*args)==reference(batch,*args)
                assert scalar.routes==batch.routes and len(batch.routes)<=limit
                cases+=1
    return cases

def check():
    folder=ROOT/"logs/infra1a/fixtures"
    folder.mkdir(exist_ok=False)
    os.environ["STS2_CORE5C_HOST"]=str(ROOT/"logs/infra1a-5d-meter")
    sys.path.insert(0,str(ROOT/"experiments/m1-core5d"))
    import audit5d, mechanisms5c, battle5d
    lane_type=battle5d.Lane
    original=lane_type.request
    pending={}
    totals=Counter()
    first=True
    def flush(lane):
        items=pending.pop(lane,[])
        if not items:return
        nonlocal first
        original(lane,"i1_core5_reference",clear=True)
        if first:
            assert original(lane,COMMAND,requests=[])["results"]==[]
            totals["empty"]+=1
            first=False
        pos=0
        while pos<len(items):
            size=1 if pos==0 else min(32,len(items)-pos)
            part=items[pos:pos+size]
            responses=original(lane,COMMAND,requests=[kw for kw,_ in part])["results"]
            if [digest(r) for r in responses]!=[expected for _,expected in part]:
                raise ValueError(f"Batch replay diverged at group {totals['groups']}, position {pos}")
            pos+=size
            totals["size_"+str(size)]+=1
            totals["groups"]+=1
            totals["verified_responses"]+=size
            for response in responses:totals["response_"+response["kind"]]+=1
    def request(lane,command,**kw):
        if command=="i1_core5_reference" and "route" in kw:
            result=original(lane,command,**kw)
            pending.setdefault(lane,[]).append((kw,digest(result["response"])))
            return result
        if "clear" in kw or command in ("pre0_start","i1_n2_step","i1_n2_close","i1_release","pre0_abandon"):
            flush(lane)
        return original(lane,command,**kw)
    lane_type.request=request
    close=lane_type.close
    def close_checked(lane):
        if lane.client:flush(lane)
        close(lane)
    lane_type.close=close_checked
    mechanisms5c.E=mechanisms5c.OUT=folder
    mechanisms5c.run()
    mech=json.loads((folder/"mechanisms.json").read_bytes())["cases"]
    assert mech==json.loads((ROOT/"experiments/m1-core5c/evidence/mechanisms.json").read_bytes())["cases"]
    host,g2,net,plan=battle5d.configure(folder,"V2low")
    lane=lane_type(host,0)
    try:
        directed=dict(cases=audit5d.cases(lane,g2,net,plan),relic=audit5d.relic(lane,plan))
    finally:
        lane.close()
        host.close()
    historical=json.loads((ROOT/"experiments/m1-core5d/evidence/audit.json").read_bytes())
    historical.pop("seconds")
    assert digest(historical)==digest(directed)
    evictions=0
    for file in folder.rglob("infra-host.json"):
        evictions+=sum(v for k,v in json.loads(file.read_bytes())["values"].items() if k.endswith("/evictions"))
    assert evictions and totals["empty"] and totals["size_1"] and totals["size_32"]
    result=dict(queue_budget_cases=queue_contract(),mechanisms=list(mech),historical_mechanism_sha=digest(mech),historical_policy_sha=digest(directed),
                evictions=evictions,replay=totals)
    (E/"fixtures.json").write_text(json.dumps(result,indent=2))

if __name__=="__main__":
    if len(sys.argv)>1:check()
    else:charged("mechanism-replay",[sys.executable,"-B",__file__,"run"],160)
