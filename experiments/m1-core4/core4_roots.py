import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"m1-core3"))
from experience import jobs,read,ROOT,cohort,digest,setup,finish,Lane,step,prepared
from time import perf_counter
import json,gzip

def design_panels():
    reserved={j["family"] for j in read(HERE.parent/"m1-core1/benchmark.json")["jobs"]}
    train={};dev={};held={}
    for s,j in jobs():{"train":train,"development":dev,"confirmation":held}[s].setdefault(j[3],j)
    new={}
    for j in read(ROOT/"logs/m1-dc1-formal/roots/development.json")["jobs"]:
        if j[3] not in reserved:new.setdefault(j[3],j)
    confirm=list(sorted(new.values(),key=lambda j:digest(["core4-confirm",j[3]])))
    confirm+=list(held.values())[12:12+max(0,100-len(confirm))]
    return dict(train=list(train.values()),dev=list(dev.values()),confirm=confirm)

def panels():
    frozen=HERE/"evidence/panels.json.gz"
    if frozen.exists():
        with gzip.open(frozen,"rt") as stream:return json.load(stream)
    return design_panels()

def spec_for(job,channel):
    return job[1]|dict(seed=cohort.seed(job[3],"core4-"+channel,0))

def produce(out,shard,n):
    out.mkdir(parents=True,exist_ok=False);t=perf_counter()
    host,model=setup(out);lane=Lane(host,0)
    with gzip.open(out/"rows.gz","wt",compresslevel=3) as f:
        for j in panels()["train"][shard::n]:
            for repeat in range(4):
                spec=spec_for(j,"natural"+str(repeat))
                try:
                    row=finish(lane,model,cohort.start(lane,spec));lane.reset()
                except (ValueError,RuntimeError,KeyError) as e:
                    lane.close();row=dict(error=str(e),states=[],terminal=None)
                f.write(json.dumps(dict(family=j[3],seed=spec["seed"],policy="G2",**row),separators=(",",":"))+"\n")
    lane.close();host.close();(out/"seconds.json").write_text(json.dumps(perf_counter()-t))
if __name__=="__main__":produce(Path(sys.argv[1]),int(sys.argv[2]),int(sys.argv[3]))
