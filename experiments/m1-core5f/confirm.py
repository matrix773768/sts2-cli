"""Frozen HotSearch production path with a versioned, hash-bound research evaluator."""
import gzip
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE=Path(__file__).resolve().parent
E=HERE/"evidence"
ROOT=HERE.parents[1]
INFRA=Path(os.environ.get("CORE5F_INFRA",ROOT.parent/"sts2-infra")).resolve()
OUT=ROOT/"logs/core5f-confirm"
POLICY="25740c4a3b29a5f378f6bd5723d3b594be6547a77e16b891e461bbf2bfcdcda7"

def worker(arm,part):
    os.environ["HOTSEARCH_BUILD"]=str(INFRA/"logs/hotsearch-h5")
    sys.path.insert(0,str(INFRA/"engine/HotSearch"))
    import hot_produce
    from models import Models,Evaluator,Value,torch
    sys.path.insert(0,str(INFRA))
    from engine.HotSearch.experience import digest,sha,check_battle,read_rows
    selection=json.loads((E/"fit.json").read_bytes())
    assert "selected" in selection
    class ExperimentModels(Models):
        def __init__(self):
            super().__init__()
            path=E/(arm+".pt")
            self.weight=sha(path)
            assert self.weight==selection["arms"][arm]["sha256"]
            net=Value()
            net.load_state_dict(torch.load(path,weights_only=True))
            self.evaluate=Evaluator(net.eval())

        def identity(self,*args):
            parent=super().identity(*args)
            assert parent["id"]==POLICY
            policy=dict(schema="sts2.core5f.hotsearch.v1",frozen_search=parent["id"],
                        value_sha256=self.weight,entry_sha256=sha(Path(__file__)))
            return policy|dict(id=digest(policy))

    panel=json.loads((E/"panel.json").read_bytes())[part*48:(part+1)*48]
    dest=OUT/f"{arm}-{part}"
    spec=dest.with_suffix(".json")
    spec.write_text(json.dumps(panel))
    assert Models().identity("tactical",32)["id"]==POLICY
    if arm!="v2":hot_produce.Models=ExperimentModels
    hot_produce.run(dest,None,"tactical",32,spec)
    rows=[]
    for spec,r in zip(panel,read_rows(dest/"natural.jsonl.gz"),strict=True):
        assert r["seed"]==spec["spec"]["seed"] and r["family"]==spec["family"]
        t=r["terminal"]
        if r["status"]!="failed":check_battle(r)
        q=r["queries"]
        rows.append(dict(family=r["family"],seed=r["seed"],status=r["status"],reason=r.get("reason"),
                         opening=r["opening_hp"],maximum=r["opening_max_hp"],end=t["hp"] if t else None,
                         queries=len(q),closed=sum(v["reference_law"]["value"] is not None for v in q),
                         interventions=sum(v.get("committed",False) for v in q),seconds=r["seconds"]))
    return rows

def launch(job):
    arm,part=job
    result=E/f"confirm-{arm}-{part}.json"
    if result.exists():return
    tick=time.perf_counter()
    proc=subprocess.run([sys.executable,"-B",str(__file__),arm,str(part)],cwd=INFRA,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    if proc.returncode:raise RuntimeError(proc.stdout.decode(errors="replace")[-4000:])
    dest=OUT/f"{arm}-{part}"
    evidence=dict(worker_seconds=time.perf_counter()-tick,ledger=json.loads((dest/"ledger.json").read_bytes()),
                  trajectory_sha256=hashlib.sha256((dest/"natural.jsonl.gz").read_bytes()).hexdigest(),
                  rows=json.loads((dest/"summary.json").read_bytes()))
    result.write_text(json.dumps(evidence,separators=(",",":")))
    print(arm,part,flush=True)

if __name__=="__main__":
    OUT.mkdir(parents=True,exist_ok=True)
    if len(sys.argv)==3:
        arm,part=sys.argv[1:]
        rows=worker(arm,int(part))
        (OUT/f"{arm}-{part}"/"summary.json").write_text(json.dumps(rows))
    else:
        fit=json.loads((E/"fit.json").read_bytes())
        assert "selected" in fit
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(launch,[(a,i) for i in range(4) for a in ["v2",*fit["arms"]]]))
