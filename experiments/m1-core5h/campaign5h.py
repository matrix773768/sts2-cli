import subprocess,sys,time
from concurrent.futures import ThreadPoolExecutor
from statistics import mean
from pathlib import Path
from paths5h import *
sys.path.insert(0,str(G))
from campaign5g import paired,complete,win,u,loss
from collections import Counter

def simulate(job):
    stage,a,i=job
    out=E/f"{stage}-{a}-{i}.json"
    if out.exists():return
    tick=time.perf_counter()
    p=subprocess.run([sys.executable,"-B",str(H/"fight5h.py"),stage,a,str(i)],cwd=INFRA,capture_output=True)
    if p.returncode:raise RuntimeError(p.stderr.decode(errors="replace")[-2500:])
    data=read(out)
    data["worker_seconds"]=time.perf_counter()-tick
    save(out,data)

def stats(stage,a):
    files=[read(E/f"{stage}-{a}-{i}.json") for i in range(4 if stage=="confirm" else 1)]
    rows=[r for f in files for r in f["rows"]]
    ok=[r for r in rows if complete(r)]
    return rows,dict(attempts=len(rows),complete=len(ok),wins=sum(map(win,rows)),utility=mean(map(u,ok)),loss=mean(map(loss,ok)),
                     severe=sum(not win(r) or loss(r)>=r["opening"]/2 for r in ok),failures=Counter(r["reason"] for r in rows if not complete(r)),
                     queries=sum(r["queries"] for r in rows),closed=sum(r["closed"] for r in rows),interventions=sum(r["interventions"] for r in rows),
                     worker_seconds=sum(f["worker_seconds"] for f in files),forward_seconds=sum(f["forward"]["seconds"] for f in files),
                     forward_rows=sum(f["forward"]["rows"] for f in files),forward_batches=sum(f["forward"]["batches"] for f in files))

def main():
    groups={}
    for kind in ("pool","local","interact"):
        for method in ("active","control"):
            ids=[f"{kind}-{method}-{s}" for s in (5719,7213)]
            groups[f"{kind}-{method}"]=ids if method=="active" and kind!="local" else [min(ids,key=lambda a:read(E/(a+".json"))["best"]["score"])]
    candidates=[a for group in groups.values() for a in group]
    with ThreadPoolExecutor(4) as pool:list(pool.map(simulate,[("dev",a,0) for a in ["v2","long",*candidates]]))
    base,_=stats("dev","v2")
    entries={}
    for a in candidates:
        r=read(E/(a+".json"))["best"]
        rows,s=stats("dev",a)
        entries[a]=dict(nll=r["natural"]["nll"],conditional=r["old_pair_rmse"],regret=r["active"]["regret"],panel=s,paired=paired(rows,base))
    for a,r in entries.items():
        metrics=[lambda v:v["nll"],lambda v:v["conditional"],lambda v:v["regret"],lambda v:-v["paired"]["delta"],
                 lambda v:-v["panel"]["wins"],lambda v:-v["panel"]["complete"]]
        ranks=[]
        for f in metrics:
            vals=[f(v) for v in entries.values()]
            ranks.append(sum(x<f(r) for x in vals)+(vals.count(f(r))-1)/2)
        r["score"]=sum(x*w for x,w in zip(ranks,[.2,.1,.25,.25,.1,.1]))
    def best(ids):return min(ids,key=lambda a:(entries[a]["score"],a))
    reps={k:best(v) for k,v in groups.items()}
    primary=best([reps["pool-active"],reps["interact-active"]])
    spend=sum(read(E/f"scans-{i}.json")["seconds"] for i in range(4))
    spend+=sum(read(E/f"fit-worker-{s}.json")["seconds"] for s in (5719,7213))
    spend+=sum(stats("dev",a)[1]["worker_seconds"] for a in ["v2","long",*candidates])
    spend+=read(E/"source.json")["seconds"]+read(E/"network-checks.json")["seconds"]+180
    arms=["v2","long",reps["pool-active"],reps["interact-active"]]
    def estimate(a):return 4*stats("dev",a)[1]["worker_seconds"]
    forecast=spend+sum(estimate(a) for a in arms)
    for k in ("pool-control","interact-control","local-active"):
        a=reps[k]
        if forecast+estimate(a)<=7200:
            arms.append(a)
            forecast+=estimate(a)
    save(E/"selection.json",dict(primary=primary,arms=arms,reps=reps,entries=entries,forecast_seconds=forecast,spent_and_reserve=spend))
    with ThreadPoolExecutor(4) as pool:list(pool.map(simulate,[("confirm",a,i) for i in range(4) for a in arms]))
    base,_=stats("confirm","v2")
    results={}
    for a in arms:
        rows,s=stats("confirm",a)
        results[a]=dict(stats=s,vs_v2=paired(rows,base))
    comparisons={}
    for a,b in [("pool-active","pool-control"),("interact-active","interact-control"),("interact-active","pool-active"),("interact-active","local-active")]:
        if reps[a] in arms and reps[b] in arms:
            comparisons[a+" minus "+b]=paired(stats("confirm",reps[a])[0],stats("confirm",reps[b])[0])
    save(E/"results.json",dict(arms=results,comparisons=comparisons))
if __name__=="__main__":main()
