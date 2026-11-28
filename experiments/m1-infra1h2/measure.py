"""Paired current-runtime production experiment using the unchanged INFRA worker and gzip admission."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from time import perf_counter_ns

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OLD=HERE.parent/"m1-infra0"
sys.path.insert(0,str(OLD))
from infra_assets import sha
from world_assets import OPEN

def fingerprint(row):
    return hashlib.sha256(json.dumps({k:v for k,v in row.items() if k!="seconds"},sort_keys=True,
        separators=(",",":"),allow_nan=False).encode()).hexdigest()

def run(tag,kind,variant,size="sample"):
    frozen_path=OLD/"evidence/inputs.json"
    current=json.loads((HERE/"evidence/runtime.json").read_bytes())
    if sha(frozen_path)!=current["frozen_manifest_sha256"]:raise ValueError("Frozen identity changed")
    frozen=json.loads(frozen_path.read_bytes())
    for name,digest in frozen["files"].items():
        if sha(ROOT/name)!=digest:raise ValueError(name)
    for name,digest in current["shared"].items():
        if sha(Path(name))!=digest:raise ValueError(name)
    panel=json.loads((OLD/"panel.json").read_bytes())
    source=HERE.parent/"m1-core5d/evidence"
    for name,digest in panel["source_sha256"].items():
        if sha(source/name)!=digest:raise ValueError(name)
    ids=sorted(n for group in panel["natural"].values() for n in group)
    sample=ids if size=="full" else [ids[j*(len(ids)-1)//7] for j in range(8)]
    if kind=="audit":
        source=OPEN
        spec=json.loads((OLD/"world-panel.json").read_bytes())
        for name,digest in spec["sources"].items():
            if sha(source/name)!=digest:raise ValueError(name)
        sample=[spec["ids"][kind][0],123]
    folder=ROOT/"logs/infra1h2"/tag/"worker-0"
    (folder/"tmp").mkdir(parents=True);(folder/"evidence").mkdir()
    shutil.copyfile(source/"panel.gz",folder/"evidence/panel.gz")
    task=dict(smoke=False,kind=kind,arm="V2",mode="baseline",ids=sample,variant=variant,folder=str(folder))
    (folder/"task.json").write_text(json.dumps(task))
    env={k:v for k,v in os.environ.items() if not k.startswith(("I1_","STS2_CORE","CORE5"))}
    env.update(PYTHONDONTWRITEBYTECODE="1",PYTHONHASHSEED="0",OMP_NUM_THREADS="1",MKL_NUM_THREADS="1")
    sources={f.name:sha(f) for f in HERE.glob("*.py")}
    host=ROOT/"logs"/("infra1h-5e-base2" if kind=="audit" else "infra1h2/5d-batch" if variant=="h-state" else "infra1h-5d-base2")
    identity=json.loads((host/"build.json").read_bytes())
    start=perf_counter_ns()
    with (folder/"worker.log").open("wb") as f:
        subprocess.run([sys.executable,"-B",OLD/"worker.py",folder/"task.json"],stdout=f,stderr=subprocess.STDOUT,
                       env=env,cwd=ROOT,check=True)
    end=perf_counter_ns()
    m=json.loads((folder/"worker.json").read_bytes())
    file=folder/"evidence"/m["closed"]["file"]
    with gzip.open(file) as f:rows=list(map(json.loads,f))
    if set(sample)!={x["i"] for x in rows} or len(sample)!=len(rows):raise ValueError("Incomplete production")
    baseline=ROOT/"logs/infra0-runs"/f"infra1h-A-{kind}-h-batch"/"worker-0"
    artifact=json.loads((baseline/"worker.json").read_bytes())["closed"]["file"]
    with gzip.open(baseline/"evidence"/artifact) as f:prior={x["i"]:fingerprint(x) for x in map(json.loads,f)}
    hashes={x["i"]:fingerprint(x) for x in rows}
    records=[json.loads(s) for s in (folder/"hot-turns.jsonl").read_text().splitlines()] if (folder/"hot-turns.jsonl").exists() else []
    result=dict(kind=kind,variant=variant,ids=sample,hashes=hashes,sources=sources,host_identity=identity["artifacts"],hot_identity=identity.get("hot_artifacts"),archive_differences=[i for i in sample if prior[i]!=hashes[i]],
        process_wall=(end-start)/1e9,production_wall=(m["closed"]["at"]-start)/1e9,cold_to_import=(m["imported_ns"]-start)/1e9,
        baseline_cost=[json.loads(s) for s in (folder/"baseline-query-cost.jsonl").read_text().splitlines()] if (folder/"baseline-query-cost.jsonl").exists() else [],
        python_cpu=m["python_cpu_ns"]/1e9,host_resources=m["host_resources"],host=m["host"],
        resources=m["python_resources"],threads=m["threads"],interop=m["interop"],gzip_sha256=sha(file),
        cumulative_seconds=[(v-start)/1e9 for v in m["record_flushed_ns"]] if isinstance(m["record_flushed_ns"],list) and all(isinstance(x,int) for x in m["record_flushed_ns"]) else m["record_flushed_ns"],
        hot_turns=records,terminal=sum(bool(x.get("terminal")) for x in rows),
        queries=sum(len(x.get("queries",[])) for x in rows),admissions=[dict(i=x["i"],status=x.get("status"),
            worlds=x.get("world_count"),valid=sum(all(o.get("matched") and o.get("utility") is not None for o in w["outcomes"])
            for w in x.get("worlds",[]) if "outcomes" in w)) for x in rows])
    (HERE/"evidence"/(tag+".json")).write_text(json.dumps(result,indent=2))
    print(tag,result["archive_differences"],result["production_wall"],len(records))
if __name__=="__main__":run(*sys.argv[1:])
