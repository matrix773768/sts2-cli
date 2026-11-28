"""Summarize all attempts and account for worker time and active wall time separately."""
from collections import Counter
import gzip,json,math,random,re,statistics,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];DATA=HERE/"data";WORK=ROOT/"logs/h5-production"
sys.path.insert(0,str(ROOT/"engine/HotSearch"))
from experience import read_rows,sha
from release import score,pack
from produce_batch import write

def merged_seconds(intervals):
    total=0;end=0
    for a,b in sorted(intervals):
        total+=max(0,b-max(a,end));end=max(end,b)
    return total

def performance(rows):
    complete=[r for r in rows if r.get("terminal")]
    return dict(attempts=len(rows),complete=len(complete),wins=sum(r["status"] in ("Victory","predicted_win") for r in complete),
        utility=statistics.mean(map(score,complete)),hp_loss=statistics.mean(r.get("opening_hp",r.get("hp"))-r["terminal"]["hp"] for r in complete),
        C=sum(len(r["states"]) for r in complete))

def physical(out):
    search=steps=0;pattern=re.compile(rb'\{"index":\d+,"steps":(\d+),"chances":')
    for path in (out/"transport").glob("*/stdout.log"):
        with path.open("rb") as f:
            for line in f:
                if line.startswith(b'{"type":"hot","ok":true,"result":['):search+=sum(map(int,pattern.findall(line)))
        with (path.parent/"commands.jsonl").open("rb") as f:steps+=sum(json.loads(line)["op"]=="step" for line in f)
    return search,steps

def summary(out):
    out.mkdir(exist_ok=False)
    m=json.loads((DATA/"manifest.json").read_bytes())
    result=dict(dataset=m["id"],plan=m["plan_id"],panels={})
    windows=[];open_rows=[]
    for split,kind in [("train","natural"),("open","natural"),("train","conditional"),("bridge","conditional")]:
        parts=[s for s in m["shards"] if (s["split"],s["kind"])==(split,kind)]
        timing=[];rows=[];search=steps=0
        for s in parts:
            done,=(WORK/s["shard"]).glob("*/finished.json");attempt=done.parent
            start=json.loads((attempt/"attempt.json").read_bytes())["started"]
            timing.append((start,start+s["worker_seconds"]))
            a,b=physical(attempt/"production");search+=a;steps+=b
            rows+=list(read_rows(DATA/s["file"]))
        failures=Counter();partial=0
        for r in rows:
            if r["eligible"]:continue
            raw=r["trajectory"];why=raw.get("reason") or raw.get("admission_error")
            if not why and kind=="conditional":
                why=" | ".join(sorted({side.get("reason","intervention outside law") for p in [raw["natural_pair"],*[w["outcomes"] for w in raw["worlds"]]] for side in p if not side.get("public_matched") or not side.get("matched")}))
            failures[why or raw["status"]]+=1
            partial+=len(raw["states"])
        good=[r["trajectory"] for r in rows if r["eligible"]]
        panel=result["panels"][split+"-"+kind]=dict(attempts=len(rows),eligible=len(good),families=len({r["family"] for r in rows}),
            encounters=len({r["spec"]["encounter"] for r in rows}),failures=failures,shards=len(parts),
            worker=sum(s["worker_seconds"] for s in parts),wall_active=merged_seconds(timing),python_cpu=sum(s["ledger"]["python_cpu"] for s in parts),
            hot_cpu=sum(s["ledger"]["host"]["cpu"] for s in parts),python_rss=max(s["ledger"]["python_peak_rss"] for s in parts),
            hot_rss=max(s["ledger"]["host"]["peak_rss"] for s in parts),physical_search_calls=search,real_step_requests=steps,
            model_work={k:sum(s["ledger"]["model_work"].get(k,0) for s in parts) for k in ("g2_rows","v2_rows","v2_inferred")},
            restarts=sum(s["ledger"]["host"].get("restarts",0) for s in parts))
        windows.extend(timing)
        if kind=="natural":
            panel.update(performance([r["trajectory"] for r in rows]),C_failed=partial)
            if split=="open":open_rows=rows
        else:
            panel.update(world_pairs=sum(len(r["worlds"]) for r in good),natural_pairs=len(good),
                planned_world_pairs=sum(r["trajectory"]["world_count"] for r in rows),
                actual_attempted_world_pairs=sum(len(r["trajectory"]["worlds"]) for r in rows),
                conditional_suffix_C=sum(len(s["trajectory"]["states"]) for r in good for w in r["worlds"] for s in w["outcomes"]),
                natural_suffix_C=sum(len(s["trajectory"]["states"]) for r in good for s in r["natural_pair"]))
    ref=ROOT/"logs/h5-reference";old=list(read_rows(ref/"evidence/train-V2-0.gz"))
    pack(out/"reference-open.jsonl.gz",old)
    w=json.loads((ref/"worker.json").read_bytes())
    result["reference"]=performance(old)|dict(worker=json.loads((ref/"wall.json").read_bytes()),python_cpu=w["python_cpu_ns"]/1e9,
        hot_cpu=sum(x["cpu_s"] for x in w["host_resources"]),python_rss=w["python_resources"]["peak_rss"],host_rss=max(x["peak_rss"] for x in w["host_resources"]))
    by={r["family"]:r for r in old};paired=[]
    for r in open_rows:
        s=by[r["family"]];assert s["seed"]==r["seed"]
        if r["eligible"] and s.get("terminal"):paired.append((r["trajectory"],s))
    diffs=[score(a)-score(b) for a,b in paired]
    rng=random.Random("H5 descriptive bootstrap");boot=sorted(statistics.mean(rng.choices(diffs,k=len(diffs))) for _ in range(4000))
    result["paired_open"]=dict(n=len(paired),missing=len(old)-len(paired),utility_delta=statistics.mean(diffs),bootstrap95=[boot[100],boot[3899]],
        gained=sum(a["status"]=="Victory" and b["status"]=="death" for a,b in paired),lost=sum(a["status"]=="Defeat" and b["status"]=="predicted_win" for a,b in paired))
    result["sessions"]=[json.loads(p.read_bytes()) for p in sorted(WORK.glob("session-*.json"))]
    result["active_wall_all"]=merged_seconds(windows)
    result["recovery"]=json.loads((ROOT/"logs/h5-recovery/result.json").read_bytes())
    reg=ROOT/"logs/h5-regression"
    regrows=[r for n in ("open","budget") for r in read_rows(reg/n/"natural.jsonl.gz")];pack(out/"mechanisms.jsonl.gz",regrows)
    result["regression_internal_seconds"]=sum(json.loads((reg/k/"ledger.json").read_bytes())["wall"] for k in ("open","budget"))
    result["worker_seconds"]=sum(p["worker"] for p in result["panels"].values())+result["reference"]["worker"]+result["recovery"]["wall"]+result["regression_internal_seconds"]
    write(out/"ledger.json",result)
if __name__=="__main__":summary(Path(sys.argv[1]))
