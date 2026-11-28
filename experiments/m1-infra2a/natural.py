"""Isolated 2A coordinator using the unchanged H5 worker and publication contract."""
import argparse
import sys
import time
from pathlib import Path
from cohort2a import HERE, ROOT, read, save
import produce_batch as batch
from publish_views import publish

def tasks(cohort, version):
    split=cohort["protocol"]["split"]
    jobs=batch_tasks({"train":cohort[split],"open":[],"conditions":[],"bridge123":[]},version)
    if split=="dev":
        for t in jobs:
            t["split"]=split
            t["id"]=batch.digest([version,t["kind"],split,t["family"],t["spec"],0,False])
    return jobs
batch_tasks=batch.tasks

def produce(edition):
    build=ROOT/"logs/hotsearch-h5"
    runtime=batch.provenance(build)
    batch.require(runtime==read(ROOT/"experiments/m1-infra1h5/data/plan.json")["runtime"],"H5 runtime drift")
    data=HERE/edition
    work=ROOT/"logs/infra2a"/edition
    batch.tasks=tasks
    batch.run(argparse.Namespace(data=data,build=build,work=work,cohort=HERE/(edition+".gz"),
                                 size=24,workers=4,max_shards=None,retries=0))
    if (data/"public/index.json").exists():return
    start=time.perf_counter()
    publish(data,work)
    batch.write(work/"projection.json",dict(seconds=time.perf_counter()-start))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("edition",choices=["train","dev","reserve"])
    edition=p.parse_args().edition
    if edition!="reserve":
        produce(edition)
        return
    count=read(HERE/"train/manifest.json")["eligible"]
    frozen=read(HERE/"reserve.gz")
    for i in range(0,len(frozen["train"]),32):
        if count>=3151:break
        name=f"reserve-{i//32:02}"
        path=HERE/(name+".gz")
        block=dict(train=frozen["train"][i:i+32],protocol=frozen["protocol"]|dict(edition=name,parent=batch.sha(HERE/"reserve.gz"),offset=i))
        if path.exists():batch.require(read(path)==block,"reserve order")
        else:save(path,block)
        produce(name)
        count+=read(HERE/name/"manifest.json")["eligible"]
if __name__=="__main__": main()
