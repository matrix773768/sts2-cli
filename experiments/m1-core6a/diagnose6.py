"""Offline proposal coverage and independent same-root terminal comparisons."""
import time
from statistics import mean
import numpy as np
from common6 import *
from policy6 import Guide
from train6 import Data
from engine.HotSearch.experience import scan

def differences(t):
    return [w["outcomes"][0]["utility"]-w["outcomes"][1]["utility"] for w in t["worlds"]]

def conditional(model,clone):
    base=Models()
    held=set(read(A/"splits.json")["core5f"]["dev"])
    models={"distill":model,"behavior":clone}
    records=[]
    def compare(r,steps,root):
        t=r["trajectory"]
        h=public_b(root["facts"])
        memory=base.g2.encoder.initial_history()
        for s in steps:
            obs=s["observation"]
            h0=choice_b(obs["facts"],obs) if obs["status"]=="choice" else public_b(obs["facts"])
            memory=base.advance(memory,h0,h0["actions"][s["index"]])
        first=[p["first"] for p in t["plans"]]
        row=dict(family=r["family"],id=r["task_id"],first=first,ys=differences(t),selected={},
                 original=t["natural_pair"][0]["utility"]-t["natural_pair"][1]["utility"])
        if first[0]!=first[1]:
            rank=base.rank(h,memory,r["spec"])
            row["selected"]["g2"]=int(rank.index(first[0])>rank.index(first[1]))
            row["selected"]["v2_estimate"]=int(t["plans"][0]["value"]<t["plans"][1]["value"])
            for k,net in models.items():
                scores=net.scores(h,memory,r["spec"])
                row["selected"][k]=int((scores[first[1]],-first[1])>(scores[first[0]],-first[0]))
        records.append(row)
    src=H5/"data"
    for shard in read(src/"manifest.json")["shards"]:
        if shard["split"]!="train" or shard["kind"]!="conditional":continue
        path=src/"public"/(shard["shard"]+".gz")
        for r,v in zip(read_rows(src/shard["file"]),read_rows(path),strict=True):
            if r["eligible"] and r["family"] in held:
                assert r["task_id"]==v["task_id"]
                compare(r,v["segments"][0]["steps"],v["segments"][1]["steps"][0]["observation"])
    for r in scan(A/"main",split="dev",kind="conditional"):
        assert r["suffix_behavior_id"]==BEHAVIOR
        compare(r,r["public_prefix"]["steps"],r["public_prefix"]["root"])
    lookup={r["id"]:r for r in records}
    for r in scan(A/"repeat",split="dev",kind="reassessment"):
        lookup[r["original_task_id"]]["repeat"]=differences(r["trajectory"])
    assert len(records)==51 and len({r["family"] for r in records})==51
    summary={}
    for worlds in ("ys","repeat"):
        rows=[r for r in records if r["selected"] and worlds in r]
        summary[worlds]={}
        for arm in ("g2","v2_estimate","distill","behavior"):
            regret=[max(0,mean(r[worlds]))-mean(r[worlds])*(1-r["selected"][arm]) for r in rows]
            summary[worlds][arm]=dict(roots=len(rows),regret=mean(regret),nonzero=sum(mean(r[worlds])!=0 for r in rows)) if rows else None
    return dict(roots=records,summary=summary)

def main():
    tick=time.perf_counter()
    torch.set_num_threads(1)
    model=Guide(E/(read(E/"picked.json")["name"]+".pt"))
    clone=Guide(E/(max((f"behavior-{s}" for s in (6119,6233)),key=lambda k:read(E/(k+".json"))["score"])+".pt"))
    data=Data("dev")
    detail={}
    for key,net in [("distill",model),("behavior",clone)]:
        for g,mask in [("closed",np.isin(data.group,[1,2])),("open",data.group==3),("changed_first",(data.group==1)&(data.ref!=data.y)),("committed_same_first",(data.group==1)&(data.ref==data.y))]:
            rows=[]
            for i in np.flatnonzero(mask):
                x,c,m,v,y=data.batch(np.array([i]))
                with torch.no_grad():values=net.model(x,c,m)[0]
                rank=values.argsort(descending=True,stable=True).tolist()
                # The first four numeric action columns are the kind one-hot. Locate end by the schema suffix.
                end_col=x.shape[-1]-33+1
                end=next(j for j in range(len(rank)) if x[0,j,end_col]==1)
                extra=bool((x[0,:,end_col+11]!=0).any() or (x[0,:,end_col+7]!=0).any() or values[rank[0]]-values[rank[1]]<.55)
                kept=set(rank[:2+int(extra)])|{int(data.ref[i]),end}
                rows.append([rank.index(int(y[0]))+1,data.ref[i]==int(y[0]),int(y[0]) in kept,len(kept),len(rank)])
            a=np.array(rows)
            detail[key+"-"+g]=dict(n=len(a),top1=float((a[:,0]==1).mean()),top2=float((a[:,0]<=2).mean()),g2_top1=float(a[:,1].mean()),
                                   low_coverage=float(a[:,2].mean()),fraction_scored=float(a[:,3].sum()/a[:,4].sum()))
    save(E/"teacher-check.json",dict(coverage=detail,conditional=conditional(model,clone),seconds=time.perf_counter()-tick))
if __name__=="__main__":main()
