"""Compute jointly observed training costs across the two separately frozen production editions."""
from pathlib import Path
import json
from collections import Counter
from results import HERE,ROOT,merged_seconds,physical
from experience import read_rows,sha
from produce_batch import write

def account():
    data=HERE/"capacity";work=ROOT/"logs/h5-capacity";m=json.loads((data/"manifest.json").read_bytes())
    initial=json.loads((HERE/"results/ledger.json").read_bytes());base=initial["panels"]["train-natural"]
    windows=[];worker=p_cpu=h_cpu=search=steps=0;accepted=C=attempts=win=0;fail=Counter()
    for s in m["shards"]:
        job,=(work/s["shard"]).glob("*/finished.json");start=json.loads((job.parent/"attempt.json").read_bytes())["started"]
        windows.append((start,start+s["worker_seconds"]));worker+=s["worker_seconds"]
        p_cpu+=s["ledger"]["python_cpu"];h_cpu+=s["ledger"]["host"]["cpu"]
        a,b=physical(job.parent/"production");search+=a;steps+=b
        for r in read_rows(data/s["file"]):
            attempts+=1
            if r["eligible"]:
                accepted+=1;C+=len(r["trajectory"]["states"]);win+=r["trajectory"]["status"]=="Victory"
            else:fail[r["trajectory"].get("reason",r["trajectory"].get("admission_error"))]+=1
    snap=lambda start,end:(ROOT/end).stat().st_mtime-(ROOT/start).stat().st_ctime
    side=[snap("logs/h5-views.log","experiments/m1-infra1h5/data/public/index.json"),
          snap("logs/h5-capacity-views.log","experiments/m1-infra1h5/capacity/public/index.json")]
    extra=dict(dataset=m["id"],attempts=attempts,eligible=accepted,C=C,wins=win,failures=fail,worker=worker,
        wall_active=merged_seconds(windows),python_cpu=p_cpu,hot_cpu=h_cpu,search=search,step_requests=steps,
        python_peak_rss=max(s["ledger"]["python_peak_rss"] for s in m["shards"]),hot_peak_rss=max(s["ledger"]["host"]["peak_rss"] for s in m["shards"]))
    valid=base["eligible"]+accepted
    combined=dict(attempts=base["attempts"]+attempts,eligible=valid,C=base["C"]+C,worker=base["worker"]+worker,
        wall_active=base["wall_active"]+extra["wall_active"],cpu=base["python_cpu"]+base["hot_cpu"]+p_cpu+h_cpu)
    combined["per1000"]={k:v*1000/valid for k,v in combined.items() if k!="eligible"}
    result=dict(capacity=extra,training_combined=combined,public_export_wall=side,
        build_wall=snap("logs/h5-build.log","logs/hotsearch-h5/identity.json"),
        regression_gross=snap("logs/h5-regression.log","logs/h5-regression/budget/ledger.json"),
        primary_worker_seconds=initial["worker_seconds"],capacity_worker_seconds=worker)
    result["accounted_seconds"]=initial["worker_seconds"]-initial["regression_internal_seconds"]+result["regression_gross"]+worker+sum(side)+result["build_wall"]
    write(HERE/"results/capacity.json",result)
if __name__=="__main__":account()
