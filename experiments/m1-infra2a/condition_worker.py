"""One persistent H5 process per lane. Publish each completed task by atomic rename."""
import argparse
import tempfile
import shutil
from uuid import uuid4
from worlds import *
from experience import sha,read_rows
from produce_batch import write,provenance,SCHEMA

def run(phase,ids):
    start=time.time()
    cpu=time.process_time()
    output=HERE/phase
    plan=json.loads((output/"plan.json").read_bytes())
    require(plan["id"]==digest({k:v for k,v in plan.items() if k!="id"}),"plan hash")
    require(plan["runtime"]==provenance(ROOT/"logs/hotsearch-h5"),"runtime")
    for name,h in plan["code"].items():require(sha(HERE/name)==h,"production code drift")
    require(sha(HERE/"panel.gz")==plan["panel"],"panel hash")
    panel=json.load(gzip.open(HERE/"panel.gz"))
    folder=ROOT/"logs/infra2a"/phase/uuid4().hex
    folder.mkdir(parents=True)
    write(folder/"start.json",dict(start=start,ids=ids,phase=phase))
    m=Models()
    policy=m.identity("tactical",32)
    require(policy["id"]==POLICY,"policy")
    host=Client(folder/"transport")
    recorder=Recorder(host)
    receipts=[]
    try:
        for i in ids:
            tick=time.perf_counter()
            r=panel[i]
            dest=output/"shards"/f"slot-{i:03d}"
            task=digest([plan["id"],i,r.get("natural_task_id")])
            if dest.exists():
                meta=json.loads((dest/"receipt.json").read_bytes())
                require(meta["tasks"]==[task] and sha(dest/"rows.gz")==meta["sha256"],"resume mismatch")
                continue
            source_task=None
            if phase=="repeat":
                main=HERE/"main"/"shards"/dest.name
                receipt=json.loads((main/"receipt.json").read_bytes())
                require(sha(main/"rows.gz")==receipt["sha256"],"parent shard hash")
                source_task=next(read_rows(main/"rows.gz"))
                require(source_task["eligible"] and source_task["family"]==r["family"],"ineligible repeat")
            case=produce(recorder,m,r,phase,source_task["trajectory"] if source_task else None) if "prefix" in r else dict(status="failed",eligible=False,reason="no available public root")
            kind="conditional" if phase=="main" else "reassessment"
            row=dict(schema="sts2.hotsearch.paired.v2",kind=kind,split=r["split"],run_id=plan["id"],task_id=task,
                     slot=i,role=r["role"],act=r["act"],turn=r["turn"],family=r.get("family"),donor=r.get("donor"),spec=r.get("spec"),
                     natural_task_id=r.get("natural_task_id"),original_task_id=source_task["task_id"] if source_task else None,
                     public_prefix=r.get("prefix"),policy_id=POLICY,behavior_id=plan["protocol_id"],suffix_behavior_id=BEHAVIOR,
                     native_audit="not_run",native_receipt=None,eligible=case["eligible"],mechanisms=[],trajectory=case)
            stage=Path(tempfile.mkdtemp(dir=output/".pending"))
            with (stage/"rows.gz").open("xb") as f,gzip.GzipFile(fileobj=f,mode="wb",mtime=0,filename="",compresslevel=3) as z:
                z.write(json.dumps(row,separators=(",",":"),allow_nan=False).encode()+b"\n")
            meta=dict(shard=dest.name,file="shards/"+dest.name+"/rows.gz",tasks=[task],sha256=sha(stage/"rows.gz"),split=r["split"],kind=kind,
                      policy_id=POLICY,behavior_id=plan["protocol_id"],accepted=int(case["eligible"]),worker_seconds=time.perf_counter()-tick)
            write(stage/"receipt.json",meta)
            stage.rename(dest)
            receipts.append(i)
    finally:
        try:metrics=host.call("metrics")
        finally:host.close()
        write(folder/"end.json",dict(start=start,end=time.time(),cpu=time.process_time()-cpu,peak_rss=peak_rss(),host=metrics,committed=receipts))

if __name__=="__main__":
    run(sys.argv[1],list(map(int,sys.argv[2:])))
