"""Within-family control: keep opening, enemy, HP, counter and forced history; sample turn-two hand by slot."""
from pathlib import Path
import random
import sys
from time import perf_counter
from design import digest,jobs,runtime,write
from research import one


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    host,m=runtime(out)
    plan=[]
    t=perf_counter()
    try:
        for j in jobs()[80:]:
            n=j["counts"][0] if len(j["counts"])==1 else j["counts"][j["id"]%2]
            tail=j["spec"]["deck"][5:].copy()
            random.Random(digest(["n4b-control-hand",j["family"]])).shuffle(tail)
            other=j|dict(spec=j["spec"]|dict(deck=j["spec"]["deck"][:5]+tail))
            plan.append(other|dict(selected_count=n))
            s=perf_counter()
            r=one(host.lane(),m,other,n,4,8,[0])
            write(out/f"{j['id']:03}.json.gz",r|dict(split="random_hand",seconds=perf_counter()-s))
    finally:
        host.close()
        write(out/"manifest.json",dict(jobs=plan))
        write(out/"run.json",dict(seconds=perf_counter()-t))


if __name__=="__main__":
    run(Path(sys.argv[1]))
