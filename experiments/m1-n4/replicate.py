"""Higher-precision independent confirmation after model freeze. No choice by margin or prediction."""
import argparse
from pathlib import Path
from time import perf_counter
from cohort import ROOT, checksum, one, plan, read, runtime, torch, write


def run(out,lo,hi,k):
    out.mkdir(parents=True,exist_ok=False)
    ckpts=sorted((ROOT/"logs/n4-v2-fit").glob("*.pt"))
    if len(ckpts)!=8:
        raise ValueError("Freeze all primary checkpoints before replication")
    frozen={p.stem:checksum(p) for p in ckpts}
    jobs=plan()[lo:hi]
    write(out/"manifest.json",dict(jobs=jobs,frozen=frozen,k=k,cap=512,domain="repeat-v1"))
    host,model=runtime(out)
    begin=perf_counter()
    try:
        for j in jobs:
            first=read(ROOT/f"logs/n4-v2-confirm/{j[0]:03}.json.gz")
            if first["stop"]!="complete":
                row=dict(ordinal=j[0],split=j[2],family=j[3],stop="outside_primary_qualified_set")
            else:
                row=one(host.lane(),model,j,k,512,domain="repeat-v1")
                assert row["key"]==first["key"] and row["options"]==first["options"]
            write(out/f"{j[0]:03}.json.gz",row)
    finally:
        host.close()
        write(out/"run.json",dict(seconds=perf_counter()-begin))


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("out",type=Path)
    p.add_argument("lo",type=int)
    p.add_argument("hi",type=int)
    p.add_argument("--k",type=int,default=24)
    a=p.parse_args()
    torch.set_num_threads(1)
    run(a.out,a.lo,a.hi,a.k)
