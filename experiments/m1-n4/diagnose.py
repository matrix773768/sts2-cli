"""Different continuation identities and an artificial lethal/block pressure grid, never training labels."""
from pathlib import Path
import sys
from time import perf_counter
from cohort import ROOT, finish, plan, prefix, read, runtime, seed, start, torch, write


class PressureLane:
    def __init__(self,lane,hp):
        self.lane,self.hp,self.host=lane,hp,lane.host

    def open(self):
        self.lane.open()

    def request(self,cmd,**args):
        if cmd=="pre0_start":
            args["sv1_fixture"]=args.get("sv1_fixture",{})|{"enemy_hp":self.hp}
        return self.lane.request(cmd,**args)


def pressure(out,host,model,defense="FLAME_BARRIER"):
    # All cells use this identical archetype and the same donor keys; HP is public.
    spec=plan()[96][1].copy()
    front=["BLUDGEON",defense,"DEMON_FORM","DEMON_FORM","DEMON_FORM"]
    deck=front+["STRIKE_IRONCLAD","BASH","DEFEND_IRONCLAD","BLUDGEON","UPPERCUT"]*2
    spec.update(deck=[dict(id=c,upgrade=0) for c in deck],hp=8,max_hp=80)
    import random
    rows=[]
    domain="pressure" if defense=="FLAME_BARRIER" else "pressure-"+defense
    for hp in (6,18,26,45):
        lane=PressureLane(host.lane(),hp)
        h=None
        for j in range(96):
            order=list(range(5,len(deck)))
            random.Random(seed(domain,"pile",j)).shuffle(order)
            order=list(range(5))+order
            donor=spec|dict(seed=seed(domain,"native",j))
            state=start(lane,donor,order)
            obs=host.project(state["observation"])
            if h is None:
                h=obs
                opts=[next(a["index"] for a in h["actions"] if a["kind"]=="play_card" and
                           h["hand"][a["card"]]["id"]==c) for c in front[:2]]
                r=dict(enemy_hp=hp,h=h,opts=opts,records=[],rejected=0)
                rows.append(r)
            if obs!=h:
                r["rejected"]+=1
                host.lane().reset()
                continue
            record=dict(seed=donor["seed"],order=order,outcomes=[])
            for i,action in enumerate(opts):
                if i:
                    state=start(lane,donor,order)
                record["outcomes"].append(finish(lane,model,state,h,[],action))
                host.lane().reset()
            r["records"].append(record)
            if len(r["records"])==12:
                break
    write(out/"pressure.json.gz",dict(spec=spec,rows=rows))


def continuations(out,host,model):
    rows=[]
    model.budget=24
    for j in plan()[96:100]:
        r=read(ROOT/f"logs/n4-v2-dev/{j[0]:03}.json.gz")
        if r["stop"]!="complete":
            rows.append(dict(id=j[0],stop=r["stop"]))
            continue
        for w in r["blocks"]["selection"]:
            record=dict(id=j[0],seed=w["seed"],Q0=[],Q24=[])
            for a in r["options"][:2]:
                lane=host.lane()
                hist,h,state=prefix(lane,j[1]|dict(seed=w["seed"]),w["order"],j[0]%3==1)
                assert h==r["h"] and hist==r["history"]
                record["Q0"].append(w["outcomes"][str(a)]["utility"])
                record["Q24"].append(finish(lane,model,state,h,hist,a))
                lane.reset()
            rows.append(record)
    write(out/"continuations.json.gz",dict(budget=24,results=rows))


if __name__=="__main__":
    out=Path(sys.argv[1])
    out.mkdir(parents=True,exist_ok=False)
    torch.set_num_threads(1)
    host,model=runtime(out)
    before=perf_counter()
    try:
        defense=sys.argv[2] if len(sys.argv)>2 else "FLAME_BARRIER"
        pressure(out,host,model,defense)
        if defense=="FLAME_BARRIER":
            continuations(out,host,model)
    finally:
        host.close()
        write(out/"run.json",dict(seconds=perf_counter()-before))
