"""Fresh natural deals, same family/seed per arm, no conditioning or candidate filter in battle."""
import argparse
from pathlib import Path
import random
from time import perf_counter

from cohort import CFG, ROOT, Controller, checksum, digest, plan, runtime, torch, write
from learn import restore
from loop_battle import collect


def run(out,training,arms,budgets):
    out.mkdir(parents=True,exist_ok=False)
    host,model=runtime(out)
    jobs=[j for j in plan() if j[2]=="confirm"]
    manifest=dict(config=dict(action_cap=128,version="n4-natural-v1"),purpose="open_n4_confirmation",jobs=jobs)
    write(out/"manifest.json",manifest)
    frozen=model.net,model.encoder,model.slot
    times={}
    try:
        for arm in arms:
            trained=training/(arm+".pt")
            model.net,model.encoder,model.slot=frozen if arm=="G2" else restore(trained)
            for budget in budgets:
                model.budget=budget
                key=f"{arm}-{budget}"
                folder=out/key
                folder.mkdir()
                start=perf_counter()
                definition=model.definition|dict(arm=arm,trained=None if arm=="G2" else checksum(trained),budget=budget)
                for j in jobs:
                    c=Controller(model,host.project,lambda rows:next(model.forward([(rows,)])),random.Random(0))
                    result=collect(host.lane(),c,definition,manifest,j,digest([definition,j[0]]))
                    write(folder/f"{j[0]:03}.json.gz",result)
                times[key]=perf_counter()-start
                write(folder/"run.json",dict(seconds=times[key],definition=definition))
    finally:
        host.close()
        write(out/"times.json",times)


if __name__=="__main__":
    cli=argparse.ArgumentParser()
    cli.add_argument("out",type=Path)
    cli.add_argument("--training",type=Path,default=ROOT/"logs/n4-v2-fit")
    cli.add_argument("--arms",nargs="+",default=["G2","A17","B17","C17","D17"])
    cli.add_argument("--budgets",nargs="+",type=int,default=[0,24])
    a=cli.parse_args()
    torch.set_num_threads(1)
    run(a.out,a.training,a.arms,a.budgets)
