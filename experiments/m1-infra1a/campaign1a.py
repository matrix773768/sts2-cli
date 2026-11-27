"""Run paired production workloads with one worker, immutable receipts and an exact 0B oracle."""
import argparse
import sys
from common import HERE, OLD, RUNS, E, entries, charged, json
from formal import semantic_rows
from semantic_check import compare

KINDS=("natural","pairs","initial-train","initial-dev","audit")
RESERVE=dict(zip(KINDS,(560,220,105,130,215)))

def run(kind,variant,phase,mode="baseline",smoke=False):
    tag=f"infra1a-{phase}-{kind}-{variant}"
    prior=next((r for r in entries() if r["label"]==tag),None)
    if prior:
        if not prior["success"]:raise RuntimeError(f"Previous failure: {tag}")
        return
    frozen=json.loads((OLD/"evidence/formal/campaign.json").read_bytes())
    oracle=next(r["semantics"] for r in frozen if r.get("kind")==kind and r.get("mode")=="baseline" and not r["smoke"] and r["arm"]=="V2")
    args=[sys.executable,"-B",str(OLD/"run.py"),tag,kind,"V2",mode]
    if variant!="original":args+=["--variant",variant]
    if smoke:args.append("--smoke")
    def verify():
        actual={str(k):v for k,v in semantic_rows(RUNS/tag).items()}
        if not actual or (not smoke and actual.keys()!=oracle.keys()) or any(oracle.get(k)!=v for k,v in actual.items()):
            delta={k:[oracle.get(k),v] for k,v in actual.items() if oracle.get(k)!=v}
            (RUNS/tag/"differences.json").write_text(json.dumps(delta))
            raise ValueError(f"Historical production changed: {tag}")
        result=json.loads((RUNS/tag/"result.json").read_bytes())
        return dict(kind=kind,variant=variant,mode=mode,smoke=smoke,phase=phase,matched=len(actual),
                    wall=result["production_wall_s"],worker=result["process_worker_s"],totals=result["totals"])
    charged(tag,args,50 if smoke else RESERVE[kind],verify)

def smoke_tests():
    for kind in ("natural","initial-train"):
        for variant in ("original","batch"):
            run(kind,variant,"smoke",smoke=True)
        test=compare(*(RUNS/f"infra1a-smoke-{kind}-{v}" for v in ("original","batch")))
        (E/(kind+"-semantic.json")).write_text(json.dumps(test,indent=2))
    run("natural","g2-check","scores",smoke=True)

if __name__=="__main__":
    arg=argparse.ArgumentParser()
    arg.add_argument("stage",choices=("smoke","shadow"))
    if arg.parse_args().stage=="smoke":
        smoke_tests()
    else:
        for kind in KINDS[2:]:run(kind,"shadow","reuse")
