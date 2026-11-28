"""One measured shard, including compressed actual public decision streams and offline readback."""
import time
PROCESS_START=time.perf_counter()
import gzip
import sys
from collections import Counter
from common6 import *
from search6 import Actor,SearchClient,portfolio,hot
from clone6 import Clone
from engine.HotSearch import experience as published
sys.modules["experience"]=published
sys.path.insert(0,str(A))
from verify2a_common import check_segment

def run(stage,arm,index,trial=""):
    tick=time.perf_counter()
    if stage=="confirm":
        assert arm in read(E/"selection.json")["arms"] or (arm=="clone" and read(E/"clone-selection.json")["panel_sha"]==sha(E/"confirm.gz"))
        jobs=json.load(gzip.open(E/"confirm.gz"))
    else:jobs=read(HERE.parent/"m1-core5g/evidence/dev-battles.json")
    jobs=jobs[index*64:(index+1)*64]
    if stage=="smoke":jobs=jobs[:3]
    if stage=="cal":jobs=jobs[:32]
    name=f"{stage}-{arm}-{index}"+trial
    root=WORK/name
    attempt=0
    while True:
        try:
            root.mkdir()
            break
        except FileExistsError:
            attempt+=1
            root=WORK/f"{name}-retry{attempt}"
    save(root/"jobs.json",jobs)
    ceiling={"same24":24,"same48":48}.get(arm,32)
    backend="g2" if arm in ("direct","clone","g2") else "tactical"
    actor=Clone() if arm=="clone" else Actor(arm)
    hot.Models=lambda:actor
    hot.Client=lambda out:SearchClient(out,True)
    hot.portfolio=portfolio
    original=hot.fight
    with gzip.open(root/"public.gz","wt",encoding="utf8",compresslevel=2) as stream:
        def record(client,spec,models,kind,limit,row,**kwargs):
            try:return original(client,spec,models,kind,limit,row,**kwargs)
            finally:
                segment=dict(origin="open",world=None,steps=client.steps)
                stream.write(json.dumps(dict(seed=spec["seed"],segment=segment),separators=(",",":"),allow_nan=False)+"\n")
        hot.fight=record
        hot.run(root/"engine",None,backend,ceiling,root/"jobs.json")
    validation=time.perf_counter()
    raw=root/"engine/natural.jsonl.gz"
    rows=[]
    for job,b,view in zip(jobs,read_rows(raw),read_rows(root/"public.gz"),strict=True):
        assert job["family"]==b["family"] and job["spec"]["seed"]==b["seed"]==view["seed"]
        if b["status"]!="failed":
            published.check_battle(b)
            check_segment(view["segment"],b)
        opts=[o for q in b["queries"] for o in q["options"]]
        queries=b["queries"]
        rows.append(dict(family=b["family"],seed=b["seed"],status=b["status"],reason=b.get("reason"),opening=b["opening_hp"],maximum=b["opening_max_hp"],
                         end=b["terminal"]["hp"] if b["terminal"] else None,steps=b["actual_steps"],C=len(b["states"]),seconds=b["seconds"],
                         queries=len(queries),closed=sum(q["reference_law"]["value"] is not None for q in queries),
                         interventions=sum(q.get("committed",False) for q in queries),candidates=len(opts),
                         complete_options=sum(o["value"] is not None for o in opts),option_steps=sum(o["steps"] for o in opts),
                         reference_steps=sum(q["reference_law"]["steps"] for q in queries),
                         learned_wins=sum(q.get("winner_style")=="learned-follow" for q in queries),
                         learned_candidates=sum(o.get("style")=="learned-follow" for o in opts)))
    ledger=read(root/"engine/ledger.json")
    receipt=dict(arm=arm,stage=stage,index=index,directory=root.name,rows=rows,metrics=actor.metrics,host=ledger["host"],model_work=ledger["model_work"],
                 policy=ledger["policy"],raw=sha(raw),public=sha(root/"public.gz"),bytes=raw.stat().st_size+(root/"public.gz").stat().st_size,
                 validation=time.perf_counter()-validation,worker=time.perf_counter()-tick,process_seconds=time.perf_counter()-PROCESS_START)
    save((WORK if stage=="smoke" else E)/(name+".json"),receipt)
if __name__=="__main__":run(*sys.argv[1:3],int(sys.argv[3]),*sys.argv[4:])
