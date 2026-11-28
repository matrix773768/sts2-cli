"""Rescore archived complete tactical-32 programs and the separately observed paired laws."""
import gzip,json,sys,time
from statistics import mean
from pathlib import Path
from collections import Counter
from settings import *
from search5 import Evaluator
from campaign5g import representatives
from engine.HotSearch.experience import read_rows

def identity(p):
    return digest([p["index"],p["policy"]])

def main():
    tick=time.perf_counter()
    torch.set_num_threads(1)
    actual={(r["seed"],q["turn"]):q for r in read_rows(WORK/"dev-v2-0/natural.jsonl.gz") for q in r["queries"]}
    field=["v2",*representatives()]
    evaluators={}
    for a in field:
        model=base_net()
        if a!="v2":model.load_state_dict(torch.load(OUT/(a+".pt"),weights_only=True))
        evaluators[a]=Evaluator(model.eval())
    rows=[]
    for m in read_rows(OUT/"shared-menus.gz"):
        q=actual[m["seed"],m["turn"]]
        plans=m["options"]+[m["reference"]]
        vs=[p["v2"] for p in plans[:-1]]+[q["reference_law"]["value"]]
        assert vs[:-1]==[v["value"] for v in q["options"]]
        valid=[i for i,p in enumerate(plans) if not p["gaps"]]
        ref=len(plans)-1
        programs=[identity(p) for p in plans]
        opening=m["opening"]
        def scores(ev):
            cu=ev(m["states"],opening)
            vals={}
            for i in valid:
                vals[i]=sum(prob*(cu[key] if k=="C" else utility(opening["hp"],key,opening["max_hp"],k=="Defeat"))
                            for k,key,prob in plans[i]["leaves"])
            return vals
        pre=scores(evaluators["v2"])
        assert all(abs(pre[i]-vs[i])<.002 for i in valid)
        choices=[i for i in valid if i!=ref]
        def choose(v):
            if ref not in valid:return -1,None
            if not choices:return ref,None
            top=max(choices,key=v.__getitem__)
            gap=v[top]-v[ref]
            return (top if gap>0 else ref),gap
        scores0={i:vs[i] for i in valid}
        i0,g0=choose(scores0)
        assert i0==-1 or plans[i0]["index"]==q["selected"]
        opts={}
        for a,ev in evaluators.items():
            v=scores(ev) if a!="v2" else pre
            # Anchor numerical replay to the actual producer scores and preserve all probabilities.
            corrected={i:vs[i]+(v[i]-pre[i]) for i in valid}
            idx,gap=choose(corrected)
            meaningful=[(i,j) for n,i in enumerate(valid) for j in valid[n+1:] if programs[i]!=programs[j]
                        and abs(scores0[i]-scores0[j])>1.e-4 and abs(corrected[i]-corrected[j])>1.e-4]
            flips=sum((scores0[i]-scores0[j])*(corrected[i]-corrected[j])<0 for i,j in meaningful)
            switched=idx>=0 and programs[idx]!=programs[i0]
            opts[a]=dict(selected=idx,gap=gap,delta_gap=gap-g0 if gap is not None else None,pairs=len(meaningful),flips=flips,
                         switched=switched,robust=switched and corrected[idx]-corrected[i0]>.001,
                         first_changed=idx>=0 and plans[idx]["index"]!=plans[i0]["index"])
        rows.append(dict(seed=m["seed"],turn=m["turn"],complete_reference=ref in valid,options=len(choices),models=opts))
    assert len(rows)==len(actual)
    base=read(OUT/"baseline.json")
    # Label order is the data reader's order: H5 dev first, then 2A dev.
    import pickle
    with (WORK/"corpus.pkl").open("rb") as f:_,d,_=pickle.load(f)
    truth=[p[3] for p in d.pairs]
    cond={}
    data=read(OUT/"data.json")
    parents={r["id"]:r["family"] for r in data["main"]}
    repeat={parents[r["parent"]]:mean(r["repeat"]) for r in data["repeats"] if r["part"]=="dev"}
    for a in field:
        if a=="v2":ds=base["delta"]
        else:
            run=read(OUT/(a+".json"))
            ds=next(r["delta"] for r in run["curve"] if r["step"]==run["best_step"])
        changes=[(i,v,b,y) for i,(v,b,y) in enumerate(zip(ds,base["delta"],truth)) if (v>0)!=(b>0)]
        cond[a]=dict(flips=len(changes),helped=sum((v>0)==(y>0) for i,v,b,y in changes if y!=0),
                     hurt=sum((v>0)!=(y>0) for i,v,b,y in changes if y!=0),
                     terminal_gain=sum((y if v>0 else -y) for i,v,b,y in changes)/len(truth),
                     repeat_dev_rmse=mean((v-repeat[f])**2 for f,v in zip(d.pair_ids,ds) if f in repeat)**.5,
                     changed_families=[d.pair_ids[i] for i,v,b,y in changes])
    summary={}
    for a in field:
        rr=[r["models"][a] for r in rows]
        gaps=[r["delta_gap"] for r in rr if r["delta_gap"] is not None]
        summary[a]=dict(pairs=sum(r["pairs"] for r in rr),reversed=sum(r["flips"] for r in rr),switches=sum(r["switched"] for r in rr),
                        robust=sum(r["robust"] for r in rr),first=sum(r["first_changed"] for r in rr),gaps=len(gaps),mean_gap_change=mean(gaps),mean_abs_gap_change=mean(map(abs,gaps)))
    save(OUT/"menus.json",dict(queries=len(rows),closed=sum(r["complete_reference"] for r in rows),summary=summary,conditional=cond,rows=rows,seconds=time.perf_counter()-tick))
if __name__=="__main__":main()
