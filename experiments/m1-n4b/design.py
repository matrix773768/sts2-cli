"""Fixed family splits and artificial turn-two prior. No evaluation donor is used to design options."""
from pathlib import Path
import random
import sys
from time import perf_counter

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"m1-n4"))
import cohort
from cohort import CFG, PARENT, ROOT, Controller, Host, Policy, digest, load, prepared, read, step, torch, write
from loop_policy import extract

BUILD=ROOT/"logs/n4b-host-v2"
LOGS=ROOT/"logs"
SIZE={"train":64,"dev":16,"confirm":32}
ENCOUNTERS=["MAWLER_NORMAL","CUBEX_CONSTRUCT_NORMAL"]
HANDS=[
    ["STRIKE_IRONCLAD","BLUDGEON","BLOOD_WALL","DEFEND_IRONCLAD","INFLAME"],
    ["UPPERCUT","BLOOD_WALL","STRIKE_IRONCLAD","DEFEND_IRONCLAD","DEMON_FORM"],
    ["BASH","FLAME_BARRIER","TWIN_STRIKE","INFLAME","DEFEND_IRONCLAD"],
    ["BLUDGEON","SHRUG_IT_OFF","STRIKE_IRONCLAD","FLAME_BARRIER","INFLAME"],
]


def runtime(out):
    from cohort import checksum,PARENT_SHA
    if checksum(PARENT)!=PARENT_SHA:
        raise ValueError("Parent changed")
    torch.set_num_threads(1)
    host=Host(out,BUILD,CFG|dict(lane_recycles=256))
    base=host.project
    def public(wire):
        h=cohort.project(base,wire)
        n=wire["nunchaku"] if "NUNCHAKU" in h["relics"] else wire.get("nunchaku")
        if (n is None)!=("NUNCHAKU" not in h["relics"]) or (n is not None and not 0<=n<10):
            raise ValueError("Public relic ownership or counter invalid")
        return h|dict(nunchaku=n)
    host.project=public
    _,meta=load(PARENT)
    return host,Policy(PARENT,meta["deployment"],0,0.,host.version,CFG)


def jobs():
    used={j[3] for j in cohort.plan()}
    decks=set()
    result=[]
    for source,splits in (("train",("train",)),("development",("dev","confirm"))):
        records=read(LOGS/f"m1-dc1-formal/roots/{source}.json")["jobs"]
        reps={j[3]:j for j in records if j[3] not in used and j[1]["encounter"]!="KNOWLEDGE_DEMON_BOSS"}
        families=iter(sorted(reps,key=lambda f:digest(["n4b-family",f])))
        for split in splits:
            for i in range(SIZE[split]):
                while True:
                    f=next(families)
                    j=reps[f]
                    front=["DEFEND_IRONCLAD","STRIKE_IRONCLAD","DEFEND_IRONCLAD","BASH","STRIKE_IRONCLAD"]+HANDS[i%4]
                    rng=random.Random(digest(["n4b-visible-hand",f]))
                    deal=[dict(id=c,upgrade=int(rng.random()<.25)) for c in front[5:]]
                    rng.shuffle(deal)
                    deck=[dict(id=c,upgrade=0) for c in front[:5]]+deal+j[1]["deck"]
                    key=tuple(sorted(c["id"] for c in deck))
                    if key not in decks:
                        break
                decks.add(key)
                used.add(f)
                spec=j[1]|dict(act=1,act_variant="OVERGROWTH",schema=2,ascension=0,
                    encounter=ENCOUNTERS[(i+i//4)%2],deck=deck,hp=[14,24,36,50,20][i%5],max_hp=80,
                    relics=["NUNCHAKU"],potions=[])
                result.append(dict(id=len(result),family=f,split=split,spec=spec,source_spec=j[1],
                    enemy_hp=[24,38,47,61,32,42,55][i%7],counts=[None] if (i//4)%4==3 else [0,9]))
    return result


def world(j,domain,i):
    seed=digest(["n4b-donor",j["family"],domain,i])[:16].upper()
    tail=list(range(10,len(j["spec"]["deck"])))
    random.Random(digest(["n4b-order",j["family"],domain,i])).shuffle(tail)
    return dict(seed=seed,order=list(range(10))+tail,proposal=i)


def start(lane,j,n,w):
    spec=j["spec"]|dict(seed=w["seed"],relics=[] if n is None else ["NUNCHAKU"])
    fx=dict(n4_order=w["order"],enemy_hp=j["enemy_hp"])
    if n is not None:
        fx["relic_count"]=n
    lane.open()
    return lane.request("pre0_start",spec=spec,cap=128,sv1_fixture=fx)["episode"]


def position(lane,j,n,w):
    st=start(lane,j,n,w)
    hist=[]
    for kind in ("defend","end_turn"):
        h=lane.host.project(st["observation"])
        a=next(a for a in h["actions"] if (a["kind"]=="end_turn" if kind=="end_turn" else
            a["kind"]=="play_card" and h["hand"][a["card"]]["id"]=="DEFEND_IRONCLAD"))
        hist.append([h,a["index"]])
        st=step(lane,st,a["index"])
        if st["status"]!="active":
            return hist,None,st
    h=lane.host.project(st["observation"])
    if h["turn"]!=2 or h["decision"]["phase"]!="combat" or not h["enemies"]:
        return hist,None,st
    return hist,h,st


def path_steps(path):
    return [[digest(s.observation),s.index] for s in path]


def choices(lane,model,h,hist):
    c=prepared(model,h,hist)
    c.project=lane.host.project
    g=lane.request("i1_sv1_graph",mode="tree",public_run=True,transitions=128,wall_ms=1500,depth=8,memory_bytes=512*2**20)
    if g.get("stop") in ("wall_cap","managed_memory_cap"):
        raise RuntimeError("resource-capped option generation")
    obs,_,ends,skipped=extract(g,lane.host.project,model.encoder,h,c.history)
    options=[]
    for item,path in ends:
        last=path[-1]
        u=last.observation
        if item["kind"]=="victory":
            damage=sum(e["hp"] for e in h["enemies"])
        elif item["kind"]=="end_play_a" and u["actions"][last.index]["kind"]=="end_turn" and len(path)>1:
            damage=sum(e["hp"] for e in h["enemies"])-sum(e["hp"] for e in u["enemies"])
        else:
            continue
        options.append(dict(steps=path_steps(path),damage=damage,block=u["block"],hp=u["hp"],kind=item["kind"]))
    direct=int(c.score([(h,c.history)])[0][0].argmax())
    model.budget=24
    try:
        c.search(h,lane,len(hist))
        search=path_steps(list(c.plan)) or [[digest(h),direct]]
    finally:
        model.budget=0
    if not options:
        return None
    attack=max(options,key=lambda p:(p["damage"],p["block"],p["hp"],-len(p["steps"])))
    defend=max(options,key=lambda p:(p["block"],p["hp"],p["damage"],-len(p["steps"])))
    return dict(paths=dict(g2=[[digest(h),direct]],search=search,
        single_atk=attack["steps"][:1],single_def=defend["steps"][:1],plan_atk=attack["steps"],plan_def=defend["steps"]),
        endpoints=[attack,defend],graph=dict(transitions=g["transitions"],stop=g.get("stop"),ends=len(options),skipped=dict(skipped)))
