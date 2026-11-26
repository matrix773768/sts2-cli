"""Native verification of Nunchaku's first-action energy and terminal on one shared world."""
import sys
from pathlib import Path
from time import perf_counter
from cohort import BUILD, CFG, ROOT, Host, project, read, step, write
from loop_battle import Lane
from targeted_replay import check_one


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    host=Host(out,BUILD,CFG)
    d=read(ROOT/"logs/n4-v2-counter/relic.json.gz")
    g=d["groups"][1]
    w=g["records"][0]
    spec=d["spec"]|dict(seed=w["seed"])
    t=perf_counter()
    results=[]
    for count in (0,9):
        fx=dict(enemy_hp=g["hp"],relic_count=count,n4_order=w["order"])
        for y in w["values"][str(count)]:
            l=Lane(host,0)
            try:
                l.open()
                st=l.request("pre0_start",spec=spec,sv1_fixture=fx,cap=128)["episode"]
                steps=[]
                for a in y["actions"]:
                    h=project(host.project,st["observation"])
                    steps.append(dict(observation=h,action=h["actions"][a]))
                    st=step(l,st,a)
            finally:
                l.close()
            row=dict(steps=steps,status=y["status"],terminal=y["terminal"]|dict(gold=y["gold"]))
            results.append(dict(count=count,action=y["actions"][0],after_energy=y["energy_after_first"],
                                result=check_one(host,[0,spec],row,fx)))
    host.close()
    write(out/"counter_native.json",dict(seconds=perf_counter()-t,results=results))


if __name__=="__main__":
    run(Path(sys.argv[1]))
