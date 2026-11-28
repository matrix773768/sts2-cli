"""Register slots and extract only the public prefix available at the specified turn."""
import gzip
import json
import random
import sys
import time
from collections import Counter
from functools import lru_cache
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/"engine/HotSearch"))
from experience import digest,read_rows,require,sha
from produce_batch import write

def slots():
    result=[]
    dev_turns=Counter()
    turn_targets={1:5,2:5,3:9,4:9,5:8,6:7,7:5}
    for block in range(4):
        chunk=[]
        for act,count in enumerate((12,18,18),1):
            representative=(3,4+(block%2),5-(block%2))[act-1]
            for j in range(count):
                role="representative" if j<representative else "difference"
                dev=False
                turn=(3,4,5,6)[(j+block)%4] if (j+block)%3!=0 else (1,2,7)[(j//3+block)%3]
                chunk.append(dict(act=act,role=role,split="dev" if dev else "train",turn=turn,j=j))
        for act,n in enumerate((3,4+block%2,5-block%2),1):
            group=[x for x in chunk if x["act"]==act]
            rep_n=(1 if (act!=1 or block!=3) else 0) + int(act==3 and block==2)
            for role,num in (("representative",rep_n),("difference",n-rep_n)):
                g=sorted((x for x in group if x["role"]==role),key=lambda x:digest(["dev-strata",block,x]))
                for _ in range(num):
                    x=min(g,key=lambda s:dev_turns[s["turn"]]/turn_targets[s["turn"]])
                    g.remove(x)
                    x["split"]="dev"
                    dev_turns[x["turn"]]+=1
        result.extend(sorted(chunk,key=lambda x:digest(["schedule",block,x])))
    return [s|dict(slot=i,repeat_rank=digest(["2a-repeat-order",i])) for i,s in enumerate(result)]

class PublicPool:
    def __init__(self,edition):
        self.data=HERE/edition
        manifest=json.loads((self.data/"manifest.json").read_bytes())
        self.index=json.loads((self.data/"public/index.json").read_bytes())
        require(self.index["dataset"]==manifest["id"],"public parent")
        cohort=json.load(gzip.open(HERE/(edition+".gz")))[edition]
        ids=[(t,s["shard"]) for s in manifest["shards"] for t in s["tasks"]]
        self.shards={s["shard"]:s for s in manifest["shards"]}
        self.rows=[r|dict(natural_task_id=t,shard=sh) for r,(t,sh) in zip(cohort,ids,strict=True)]
    @lru_cache(maxsize=3)
    def shard(self,name):
        path=self.data/"public"/(name+".gz")
        require(sha(path)==self.index["files"][name],"public shard hash")
        return {r["task_id"]:r["segments"][0]["steps"] for r in read_rows(path)}
    @lru_cache(maxsize=16)
    def forecasts(self,name):
        # Export only the budget-32 forecasts formed before the action at each turn.
        part=self.shards[name]
        path=self.data/part["file"]
        require(sha(path)==part["sha256"],"forecast shard hash")
        return {row["task_id"]:{q["turn"]:[(o["index"],o["value"],o["leaves"]) for o in q["options"] if o["value"] is not None] for q in row["trajectory"]["queries"]} for row in read_rows(path)}
    def prefix(self,r,turn,priority):
        steps=[]
        for step in self.shard(r["shard"])[r["natural_task_id"]]:
            obs=step["observation"]
            f=obs["facts"]
            if f["turn"]==turn and obs["status"]=="active":
                law=f["belief"]
                if law["top"] or law["bottom"] or len(law["counts"])<2:return None,"pile"
                if priority:
                    signatures=set()
                    for a in f["actions"]:
                        if a["kind"]=="PlayCard":
                            c=f["hand"][a["card"]]
                            signatures.add((bool(c["damage"]),bool(c["block"]),c["cost"],tuple(sorted(c["vars"]))))
                    if len(signatures)<2:return None,"menu"
                    options=self.forecasts(r["shard"])[r["natural_task_id"]].get(turn,[])
                    if len({o[0] for o in options})<2 or len({o[1:] for o in options})<2:return None,"closed forecast diversity"
                return dict(steps=steps,root=obs),"selected"
            if f["turn"]>=turn:break
            steps.append(step)
        return None,"no public decision at turn"

def freeze():
    pools={s:PublicPool(s) for s in ("train","dev")}
    used=set()
    panel=[]
    for slot in slots():
        tick=time.perf_counter()
        pool=pools[slot["split"]]
        rows=[r for r in pool.rows if r["spec"]["act"]==slot["act"] and r["family"] not in used]
        scans=[]
        out=dict(slot)
        for r in sorted(rows,key=lambda r:digest(["2a-root",slot["slot"],r["family"]])):
            pre,reason=pool.prefix(r,slot["turn"],slot["role"]=="difference")
            scans.append([r["natural_task_id"],reason])
            if pre:
                out.update(r,prefix=pre)
                used.add(r["family"])
                break
        out.update(scans=scans,scan_seconds=time.perf_counter()-tick)
        panel.append(out)
    path=HERE/"panel.gz"
    from uuid import uuid4
    stage=path.with_name("panel-"+uuid4().hex+".tmp")
    with stage.open("xb") as f,gzip.GzipFile(fileobj=f,mode="wb",mtime=0,filename="") as g:
        g.write(json.dumps(panel,separators=(",",":")).encode())
    stage.rename(path)
if __name__=="__main__":freeze()
