"""Development-only shortlisting followed by one confirmation pass."""
import json,subprocess,sys,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import mean
from settings import *
import importlib.util
spec=importlib.util.spec_from_file_location("results5f",G.parent/"m1-core5f/results.py")
previous=importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
paired,complete,win,u,loss=previous.paired,previous.complete,previous.win,previous.u,previous.loss
from collections import Counter

METHODS=("conservative","tuned","long","matched","scratch","td","pair","active")
def representatives(methods=METHODS):
    selected=[]
    for method in methods:
        rows=[read(OUT/f"{method}-4096-{s}.json") for s in (5719,7213)]
        best=min(rows,key=lambda r:r["score"])
        selected.append(best["name"]+"-"+str(best["seed"]))
    return selected

def sim(job):
    stage,arm,i=job
    path=OUT/f"{stage}-{arm}-{i}.json"
    if path.exists():return
    tick=time.perf_counter()
    res=subprocess.run([sys.executable,"-B",str(G/"battle.py"),stage,arm,str(i)],cwd=INFRA,capture_output=True)
    if res.returncode:raise RuntimeError(res.stderr.decode(errors="replace")[-2200:])
    data=read(path)
    data["process_seconds"]=time.perf_counter()-tick
    save(path,data)

def panel(stage,a):
    files=[read(OUT/f"{stage}-{a}-{i}.json") for i in range(1 if stage=="dev" else 5)]
    rows=[r for f in files for r in f["rows"]]
    ok=[r for r in rows if complete(r)]
    return rows,dict(attempts=len(rows),wins=sum(map(win,rows)),complete=len(ok),utility=mean(map(u,ok)),
                     loss=mean(map(loss,ok)),severe=sum(not win(r) or loss(r)>=r["opening"]/2 for r in ok),
                     closed=sum(r["closed"] for r in rows),queries=sum(r["queries"] for r in rows),
                     interventions=sum(r["interventions"] for r in rows),failures=dict(Counter(r["reason"] for r in rows if not complete(r))),
                     seconds=sum(f.get("process_seconds",f["seconds"]) for f in files))

def main():
    models=representatives()
    with ThreadPoolExecutor(max_workers=3) as ex:list(ex.map(sim,[("dev",a,0) for a in models]))
    base,_=panel("dev","v2")
    entries={}
    for a in ["v2",*models]:
        rs,stats=panel("dev",a)
        if a=="v2":m=read(OUT/"baseline.json")
        else:
            run=read(OUT/(a+".json"))
            m=next(r for r in run["curve"] if r["step"]==run["best_step"])
        entries[a]=dict(stats=stats,paired=paired(rs,base),nll=m["natural"]["all"]["nll"],pair_rmse=m["pair_rmse"])
    # Rank each candidate against the same field. Ties receive average ranks.
    for a,row in entries.items():
        row["ranks"]=[]
        for key in [lambda v:v["nll"],lambda v:v["pair_rmse"],lambda v:-v["paired"]["delta"],
                    lambda v:-v["stats"]["wins"],lambda v:-v["stats"]["complete"]]:
            vals=[key(v) for v in entries.values()]
            row["ranks"].append(sum(x<key(row) for x in vals)+(vals.count(key(row))-1)/2)
        row["score"]=sum(x*w for x,w in zip(row["ranks"],(.25,.2,.30,.15,.1)))
    primary=min(models,key=lambda a:(entries[a]["score"],a))
    alternate=min((a for a in models if a.startswith("scratch")!=primary.startswith("scratch")),key=lambda a:entries[a]["score"])
    arms=["v2",primary,alternate]
    selection=dict(entries=entries,primary=primary,development_winner=min(entries,key=lambda a:entries[a]["score"]),confirm=arms,
                   promotion="Primary only: positive lower 95% family-bootstrap utility bound; all-attempt wins and completions at least V2.")
    save(OUT/"selection.json",selection)
    with ThreadPoolExecutor(max_workers=3) as ex:list(ex.map(sim,[("confirm",a,i) for i in range(5) for a in arms]))
    base,_=panel("confirm","v2")
    results={}
    for a in arms:
        rs,stats=panel("confirm",a)
        assert len(rs)==320
        results[a]=dict(stats=stats,paired=paired(rs,base))
    save(OUT/"results.json",results)
if __name__=="__main__":main()
