"""Fresh paired conditional battles from turn two and ordinary unmodified-deal battles from turn one."""
from pathlib import Path
import sys
from time import perf_counter
from design import LOGS,cohort,digest,jobs,position,read,runtime,world,write
from learn_menu import ARMS,restore
from research import rollout


def scenario(lane,j,n,w,natural):
    if natural:
        spec=j["source_spec"]|dict(seed=w["seed"],hp=(55,80,100,70)[j["id"]%4],
            max_hp=(80,80,100,80)[j["id"]%4])
        st=cohort.start(lane,spec)
        return [],lane.host.project(st["observation"]),st
    return position(lane,j,n,w)


def run(out,seed):
    out.mkdir(parents=True,exist_ok=False)
    host,m=runtime(out)
    lane=host.lane()
    frozen=m.net,m.encoder,m.slot
    armnames=["G2"] if seed==0 else [f"{arm}-{seed}" for arm in ARMS]
    folder=LOGS/"n4b-finalfit"
    epoch=read(folder/"selection.json")["epoch"] if seed else None
    begin=perf_counter()
    try:
        for j in jobs()[80:]:
            for natural,n in [(True,None),*((False,n) for n in j["counts"])]:
                worlds=[]
                rejects=0
                expected=None if natural else read(next(LOGS.glob(f"n4b-finalcore-*/{j['id']:03}-{n}.json.gz")))
                for i in range(100):
                    w=world(j,"battle-natural" if natural else "battle-target",i)
                    hist,h,st=scenario(lane,j,n,w,natural)
                    lane.reset()
                    if not natural and (hist!=expected["history"] or h!=expected["h"]):
                        rejects+=1
                        continue
                    ys={}
                    for arm in armnames:
                        if arm=="G2":
                            m.net,m.encoder,m.slot=frozen
                        else:
                            if arm not in cache:
                                cache[arm]=restore(folder/f"{arm}-{epoch}.pt")
                            m.net,m.encoder,m.slot=cache[arm]
                        for budget in (0,24):
                            before,obs,st=scenario(lane,j,n,w,natural)
                            assert before==hist and obs==h
                            ys[f"{arm}/{budget}"]=rollout(lane,m,hist,h,st,[],budget,diagnostics=True)
                            lane.reset()
                    worlds.append(w|dict(outcomes=ys))
                    if len(worlds)==(1 if natural else 2):
                        break
                write(out/f"{j['id']:03}-{'natural' if natural else str(n)}.json.gz",
                    dict(id=j["id"],family=j["family"],domain="natural" if natural else "target",counter=n,
                         initial_hp=(55,80,100,70)[j["id"]%4] if natural else j["spec"]["hp"],worlds=worlds,rejects=rejects,
                         stop="complete" if len(worlds)==(1 if natural else 2) else "proposal_cap"))
    finally:
        host.close()
        write(out/"run.json",dict(seconds=perf_counter()-begin,arms=armnames,epoch=epoch,teacher=m.definition))


cache={}
if __name__=="__main__":
    run(Path(sys.argv[1]),int(sys.argv[2]))
