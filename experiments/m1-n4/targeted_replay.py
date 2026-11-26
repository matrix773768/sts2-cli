"""Targeted native checks for policy disagreements and pressure interventions."""
from pathlib import Path
import sys
from time import perf_counter
from cohort import BUILD, CFG, ROOT, Host, plan, project, read, step, write
from loop_battle import Lane
from native import check


class Bound:
    def __init__(self,lane,fixture):
        self.lane,self.fixture=lane,fixture

    def request(self,command,**args):
        if command in ("pre0_start","synthetic_start"):
            args["sv1_fixture"]=self.fixture
        return self.lane.request(command,**args)


def check_one(host,job,row,fixture=None):
    left,right=Lane(host,0),Lane(host,1)
    try:
        left.open()
        right.open()
        if fixture:
            p,n=Bound(left,fixture),Bound(right,fixture)
        else:
            p,n=left,right
        return check(p,n,job,row,host.project)
    except (RuntimeError,ValueError,AssertionError,KeyError) as exc:
        return dict(error=str(exc))
    finally:
        left.close()
        right.close()


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    host=Host(out,BUILD,CFG)
    logs=ROOT/"logs"
    entries=[]
    t=perf_counter()
    for budget in (0,24):
        checked=0
        for j in plan()[116:]:
            rows=[read(logs/f"n4-v2-battle-17/{arm}17-{budget}/{j[0]:03}.json.gz")["row"] for arm in "AD"]
            if not all(r["complete"] for r in rows):
                continue
            paths=[[s["action"]["index"] for s in r["steps"]] for r in rows]
            if paths[0]==paths[1]:
                continue
            for arm,r in zip("AD",rows):
                entries.append(dict(type="battle",id=j[0],budget=budget,arm=arm,result=check_one(host,j,r)))
            checked+=1
            if checked==2:
                break
    for directory in ("n4-v2-diag2","n4-v2-pressure"):
        grid=read(logs/directory/"pressure.json.gz")
        for case in (grid["rows"][0],grid["rows"][-1]):
            w=case["records"][0]
            spec=grid["spec"]|dict(seed=w["seed"])
            fx=dict(n4_order=w["order"],enemy_hp=case["enemy_hp"])
            for y in w["outcomes"]:
                lane=Lane(host,0)
                try:
                    lane.open()
                    st=lane.request("pre0_start",spec=spec,sv1_fixture=fx,cap=128)["episode"]
                    steps=[]
                    for i in y["actions"]:
                        h=project(host.project,st["observation"])
                        steps.append(dict(observation=h,action=h["actions"][i]))
                        st=step(lane,st,i)
                finally:
                    lane.close()
                row=dict(steps=steps,status=y["status"],terminal=y["terminal"]|dict(gold=y["gold"]))
                entries.append(dict(type=directory,enemy_hp=case["enemy_hp"],action=y["actions"][0],
                                    result=check_one(host,[0,spec],row,fx)))
    host.close()
    write(out/"replay.json",dict(seconds=perf_counter()-t,entries=entries))


if __name__=="__main__":
    run(Path(sys.argv[1]))
