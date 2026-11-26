"""Append-only scope by workload; repeated arms are visits, never independent roots."""
from collections import Counter
import json
from pathlib import Path
import re
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
LOGS=ROOT/"logs"


def read(path):
    return json.loads(path.read_bytes())


def main(out):
    rows=[]
    for name,file in [("pilot",None),("development","summary.json"),("policy","summary.json"),
                      ("final","summary.json"),("resident","summary.json"),("pressure","summary.json"),
                      ("transfer","summary.json"),("world8","summary.json"),("isolation","isolation.json"),
                      ("compare","compare.json"),("release-smoke","summary.json"),("release-compare","compare.json")]:
        directory=LOGS/("core1-"+name)
        data=read(directory/file) if file else {}
        commands=Counter()
        for p in (directory/"engine").glob("*/commands.jsonl"):
            with p.open("rb") as stream:
                commands.update(json.loads(line)["cmd"] for line in stream)
        rows.append(dict(stage=name,seconds=data.get("seconds"),python_cpu=data.get("python_cpu_seconds"),
                         host_cpu=data.get("host_cpu_seconds"),commands=commands))
    for stage in ("core1-exact-build","core1-exact-v2","core1-build-final","core1-release-build"):
        log=(LOGS/stage/"build.log").read_text(encoding="utf8",errors="replace")
        durations=re.findall(r"(?:已用时间|Time Elapsed) (\d\d):(\d\d):([\d.]+)",log)
        rows.append(dict(stage=stage,seconds=sum(int(h)*3600+int(m)*60+float(s) for h,m,s in durations),
                         scope="SDK-reported elapsed per project; extraction and hashing unmetered"))
    for stage in ("core1-cases","core1-cases-v2","core1-exact-final","core1-release-cases",
                  "core1-hotdraw-regression","core1-pilot"):
        folder=LOGS/stage
        # Use artifact timestamps only where a process-level timer was unavailable.
        end=max(p.stat().st_mtime for p in folder.rglob("*") if p.is_file())
        begin=folder.stat().st_ctime
        rows.append(dict(stage=stage,seconds=max(0,end-begin),scope="approximate local output creation-to-last-write"))
    n4c=read(ROOT/"experiments/m1-n4c/evidence/manifest.json")
    historical=[
        dict(stage="SV4A D/S generation",source="docs/m1-sv4a-search-value-loop.md",
             completed_episodes=14709,capped=11,updates_per_generation=960,presentations_per_generation=491520),
        dict(stage="DC2B G0/G1/G2",source="docs/inf3-dc2b-recovery.md",
             updates=[4096,1600,1600],g1_g2_completed_experience=[10000,10000],
             presentations=[None,819200,819200],training_wall_seconds=[271.,450.3,466.1],
             direct_search_collection_seconds=[[3104.9,1157.9],[2353.2,1141.3]]),
        dict(stage="N4",source="docs/m1-n4-counterfactual-value.md",conditional_rollouts=8438,
             main_seconds=1590.2,estimated_inclusive_seconds=2100),
        dict(stage="N4B",source="experiments/m1-n4b/evidence/summary.json",
             measured_seconds=read(ROOT/"experiments/m1-n4b/evidence/summary.json")["measured_seconds_sum"]),
        dict(stage="N4C",source="experiments/m1-n4c/evidence/manifest.json",
             main_families=64,main_root_worlds=160,main_episodes=1920,main_transitions=146696,
             measured_seconds=n4c["measured_seconds_sum"],per_job=n4c["usage"])]
    result=dict(schema=1,scope="Measured stage sums, including repeated and concurrent jobs. Missing fields are unmeasured.",
                historical=historical,core1=rows,total_core1_measured_or_estimated_job_seconds=sum(r["seconds"] or 0 for r in rows),
                core1_training_presentations=0,core1_training_updates=0,core1_gpu_inference_or_training_seconds=0,
                deployment_and_conditional_world_counts="evidence/summary.json",historical_full_cpu_gpu=None,
                distinct_lifetime_families_or_battles=None)
    out.write_text(json.dumps(result,indent=2)+"\n")


if __name__=="__main__":
    main(Path(sys.argv[1]))
