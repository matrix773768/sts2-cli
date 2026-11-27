"""Replay whole policies, then change exactly one turn on the same root with the same suffix."""
from deploy5b import *
from search5 import prepared
from collections import defaultdict
from assessment import utility
from time import perf_counter

def description(obs,index):
    a=obs["actions"][index]
    card=(obs["hand"][a["card"]] if a.get("card") is not None else {})
    return dict(kind=a["kind"],card=card.get("id"),upgrade=card.get("upgrade"),target=a.get("target"),choice=a.get("choice"),
                effect=obs["decision"].get("effect"),preview=a.get("preview"))

class Inspect(Search):
    def __init__(self,net,arm):
        super().__init__(net,arm)
        self.turn=None;self.snapshot=None;self.swap=None
    def __call__(self,lane,h,past,net,g2,spec):
        arm=self.swap[1] if self.swap and self.swap[0]==h["turn"] else self.arm
        old=arm=="5A"
        transitions,limit,cap,exp=BUDGET["base" if old else arm]
        def capture(g,paths,laws,states,values,choices,opts,ref_law,ref_first):
            nodes=g["nodes"]
            def walk(i,first,actions,p,leaves):
                n=nodes[i];kind=n["kind"]
                if kind=="R":
                    for e in n["edges"]:walk(e["to"],None,actions,p*e["probability"],leaves)
                elif kind=="decision":
                    j=first if i==0 else choices.get(i)
                    o=lane.host.project(n["state"])
                    if j==-1:
                        for k,key,v,w in laws[i]:
                            leaves.append(dict(p=p*w,kind=k,c=states.get(key),value=values.get(key,v),actions=actions+[description(o,n["end"])]))
                    elif j is not None:
                        edge=n["edges"][j]
                        walk(edge["to"],None,actions+[description(o,edge["input"]["index"])],p,leaves)
                    else:leaves.append(dict(p=p,kind="missing",actions=actions))
                else:leaves.append(dict(p=p,kind=kind,c=n.get("state"),actions=actions))
            plans=[]
            for cov,v,j in sorted(opts,key=lambda x:(round(x[0],9),x[1]),reverse=True)[:4]:
                leaves=[];walk(0,j,[],1.,leaves)
                plans.append(dict(cov=cov,value=v,j=j,leaves=leaves))
            self.snapshot=dict(h=h,plans=plans,ref_first=description(h,ref_first),
                ref_law=[dict(kind=k,c=states.get(key),value=values.get(key,v),p=w) for k,key,v,w in ref_law])
        try:
            g,ch,q=graph_plan(lane,h,past,net,g2,spec,limit,direct=partial(reference,limit=cap),evaluator=self.evaluator,
                fast=True,transitions=transitions,expansions=exp,alternatives=True,inspect=capture if h["turn"]==self.turn else None)
        finally:
            if not old:lane.request("i1_core5_reference",clear=True)
        if self.force and self.force[0]==h["turn"]:
            j=self.force[1];q["use"]=j is not None
            if j is not None:ch[0]=j
        return g,ch,q

def case(tag,spec,a,b,oracle=None):
    out=LOGS/"5b-review"/tag;out.mkdir(parents=True,exist_ok=True)
    def battle(arm,turn=None,force=False,j=None,switch=None):
        host,g2,net,_=init(out,arm);lane=Lane(host,0);trace=[]
        plan=Inspect(net,arm);plan.turn=turn;plan.force=(turn,j) if force else None;plan.swap=switch
        r=fight(lane,g2,spec,arm,net,planner=plan,trace=trace);lane.close();host.close()
        turns=defaultdict(list)
        for h,idx in trace:turns[h["turn"]].append(description(h,idx))
        return dict(row=r,turns=dict(turns),snapshot=plan.snapshot)
    left=battle(a);right=battle(b)
    turn=next((t for t,acts in left["turns"].items() if acts!=right["turns"].get(t)),None)
    if oracle:
        native=defaultdict(list)
        for action in oracle["actions"]:
            if action["kind"]=="PlayCard":native[action["turn"]].append(action["card_id"])
        turn=next((t for t,acts in right["turns"].items() if [a["card"] for a in acts if a["kind"]=="play_card"]!=native[t]),turn)
    if turn is None:turn=next(iter(left["turns"]))
    left=battle(a,turn);right=battle(b,turn)
    # Conditional comparison uses b on every other turn.
    rival=next((p for p in right["snapshot"]["plans"][1:] if p["cov"]>=1-1e-9),None)
    alternates=dict(reference=battle(b,turn,True))
    if rival:alternates["rival"]=battle(b,turn,True,rival["j"])
    if a!="5A":alternates["left_turn"]=battle(b,turn,switch=(turn,a))
    data=dict(tag=tag,spec=spec,turn=turn,a=a,b=b,left=left,right=right,alternates=alternates,oracle=oracle)
    with gzip.open(E/f"review-{tag}.gz","xt",compresslevel=6) as f:json.dump(data,f,separators=(",",":"))

def indexed(pattern):
    return {r["i"]:r for f in E.glob(pattern) for r in records(f)}
def select():
    panel=json.load(gzip.open(E/"panel.gz","rt"));base=indexed("fresh-base-*.gz");high=indexed("fresh-high-*.gz")
    jobs=[]
    for tag,win in (("rescue",True),("loss",False)):
        candidates=[i for i,r in high.items() if r["terminal"] and base[i]["terminal"] and
                    (r["status"]=="predicted_win")==win and r["status"]!=base[i]["status"]]
        if candidates:jobs.append((tag,panel["fresh"][min(candidates)]["spec"],"base","high"))
    archived={ (r["family"],r["seed"]):r for f in (FIVE/"evidence").glob("confirm-v2-*.gz") for r in records(f)}
    history=indexed("historical-base-*.gz")
    gains=[i for i,r in history.items() if r["status"]=="predicted_win" and archived[r["family"],r["seed"]]["status"]=="death"]
    if gains:jobs.append(("recovery",panel["historical"][min(gains)]["spec"],"5A","base"))
    hp=indexed("high-high-*.gz");low=indexed("high-base-*.gz")
    ids=[i for i,r in hp.items() if panel["high"][i]["hard"] and r["terminal"] and low[i]["terminal"]]
    if ids:
        i=max(ids,key=lambda i:abs(hp[i]["last_hp"]-low[i]["last_hp"]))
        jobs.append(("long",panel["high"][i]["spec"]|dict(hp=999,max_hp=999),"base","high"))
    oracles=[(r["world"],r["reference"]) for r in records(E/"oracle.gz") if r["reference"]]
    if not oracles:
        oracles=[(r["world"],r["validation"]) for f in E.glob("beam-*.gz") for r in records(f) if r.get("validation",{}).get("status")=="native_win"]
    if oracles:
        w,win=oracles[0];jobs.append(("oracle",w["spec"],"base","high",win))
    for job in jobs:case(*job)
if __name__=="__main__":
    t=perf_counter();select();(E/"reviews-cost.json").write_text(json.dumps(perf_counter()-t))
