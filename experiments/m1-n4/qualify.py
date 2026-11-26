"""Offline-only native audits including order/RNG isolation, a forced trajectory and known failure."""
import argparse
from time import perf_counter

from cohort import BUILD, CFG, ROOT, Host, digest, plan, prefix, project, read, step, write
from loop_battle import Lane
from native import check


class Fixture:
    def __init__(self,lane,order):
        self.lane,self.order=lane,order

    def request(self,cmd,**args):
        if cmd in ("pre0_start","synthetic_start"):
            args["sv1_fixture"]={"n4_order":self.order}
        return self.lane.request(cmd,**args)


def audit(out):
    out.mkdir(parents=True,exist_ok=False)
    host=Host(out,BUILD,CFG)
    base=host.project
    host.project=lambda wire:project(base,wire)
    jobs=plan()
    report=[]
    t=perf_counter()
    for ordinal in (0,1,2,96,97):
        job=jobs[ordinal]
        r=read(ROOT/f"logs/n4-v2-{job[2]}/{ordinal:03}.json.gz")
        if r["stop"]!="complete":
            report.append(dict(id=ordinal,stop=r["stop"]))
            continue
        worlds=next(iter(r["blocks"].values()))
        for w in worlds[:2]:
            donor=job[1]|dict(seed=w["seed"])
            lane=Lane(host,0)
            second=Lane(host,1)
            try:
                hist,h,s=prefix(lane,donor,w["order"],ordinal%3==1)
                assert hist==r["history"] and h==r["h"]
                snap=lane.request("synthetic_snapshot")
                actual=[c.split("|")[0] for c in snap["hand"]+snap["draw"]]
                wanted=[donor["deck"][i]["id"]+"+"+str(donor["deck"][i]["upgrade"]) for i in w["order"]]
                assert actual==wanted,(actual,wanted)
                details=dict(id=ordinal,seed=w["seed"],history=r["key"],pile=digest(snap["draw"]),
                    rng=digest([snap["run_rng"],snap["player_rng"]]),same_public=True,order_verified=True)
                y=w["outcomes"][str(r["options"][-1])]
                steps=[dict(observation=o,action=o["actions"][i]) for o,i in hist]
                for i in y["actions"]:
                    o=host.project(s["observation"])
                    steps.append(dict(observation=o,action=o["actions"][i]))
                    s=step(lane,s,i)
                assert s["status"]==y["status"] and s["terminal_observation"]==y["terminal"]
                lane.reset()
                second.open()
                rr=dict(terminal=y["terminal"]|dict(gold=y["gold"]),steps=steps,status=y["status"])
                native=check(Fixture(lane,w["order"]),Fixture(second,w["order"]),[ordinal,donor],rr,base)
                report.append(details|dict(native=native))
            finally:
                lane.close()
                second.close()
    arm=ROOT/"logs/n1bc-eval-base17-0"
    result={}
    j=next(j for j in read(arm/"manifest.json")["jobs"] if j[0]==197)
    l,n=Lane(host,0),Lane(host,1)
    try:
        l.open()
        n.open()
        result=check(l,n,j,read(arm/"197.json.gz")["row"],base)
    except (RuntimeError,ValueError,AssertionError) as e:
        result=dict(issue=str(e))
    finally:
        l.close()
        n.close()
        host.close()
    write(out/"qualification.json",dict(seconds=perf_counter()-t,audits=report,known_demon=result))


if __name__=="__main__":
    from pathlib import Path
    p=argparse.ArgumentParser()
    p.add_argument("out",type=Path)
    audit(p.parse_args().out)
