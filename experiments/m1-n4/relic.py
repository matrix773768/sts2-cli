"""Same observed network input, manipulated public Nunchaku counter, matched hidden-world keys."""
from pathlib import Path
import random
import sys
from time import perf_counter
from cohort import finish, plan, runtime, seed, step, write


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    host,model=runtime(out)
    lane=host.lane()
    spec=plan()[96][1]|dict(schema=2,relics=["NUNCHAKU"],hp=8,max_hp=80)
    cards=["UPPERCUT","BLOOD_WALL","DEMON_FORM","DEMON_FORM","DEMON_FORM",
           "BLUDGEON","STRIKE_IRONCLAD","DEFEND_IRONCLAD","BASH","UPPERCUT"] + ["STRIKE_IRONCLAD"]*3
    spec["deck"]=[dict(id=x,upgrade=0) for x in cards]
    t=perf_counter()
    groups=[]
    for hp in (13,22,35,50):
        group=dict(hp=hp,records=[],rejected=0)
        groups.append(group)
        for j in range(96):
            donor=spec|dict(seed=seed("counter","native",j))
            tail=list(range(5,len(cards)))
            random.Random(seed("counter","pile",j)).shuffle(tail)
            order=list(range(5))+tail
            record=dict(order=order,seed=donor["seed"],values={})
            for count in (0,9):
                fx=dict(n4_order=order,enemy_hp=hp,relic_count=count)
                def reset():
                    lane.open()
                    return lane.request("pre0_start",spec=donor,sv1_fixture=fx,cap=128)["episode"]
                state=reset()
                h=host.project(state["observation"])
                if "h" not in group:
                    group["h"]=h
                    group["options"]=[next(a["index"] for a in h["actions"] if a["kind"]=="play_card" and
                        h["hand"][a["card"]]["id"]==c) for c in cards[:2]]
                if h!=group["h"]:
                    if count==9:
                        raise ValueError("Counter changes the projected network input")
                    group["rejected"]+=1
                    lane.reset()
                    break
                vals=[]
                for action in group["options"]:
                    after=step(lane,state,action)
                    energy=host.project(after["observation"])["energy"] if after["status"]=="active" else None
                    lane.reset()
                    state=reset()
                    y=finish(lane,model,state,h,[],action)
                    vals.append(y|dict(energy_after_first=energy))
                    lane.reset()
                    if action!=group["options"][-1]:
                        state=reset()
                record["values"][str(count)]=vals
            if len(record["values"])==2:
                group["records"].append(record)
            if len(group["records"])==12:
                break
    host.close()
    write(out/"relic.json.gz",dict(spec=spec,groups=groups,seconds=perf_counter()-t))


if __name__=="__main__":
    run(Path(sys.argv[1]))
