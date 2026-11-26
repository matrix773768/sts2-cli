"""Public histories, independent world proposals and paired MC returns under frozen G2."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import random
import sys
from time import perf_counter

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"m1-n1bc"))
from arena import CFG, PARENT, PARENT_SHA, ROOT, Controller, Host, Policy, checksum, digest, load, project, torch
from value import payoff

BUILD=ROOT/"logs/n4-host-v2"
CAP=128


def write(path, obj):
    raw=json.dumps(obj,separators=(",",":"),allow_nan=False).encode()
    path.write_bytes(gzip.compress(raw,compresslevel=4,mtime=0) if path.suffix==".gz" else raw)


def read(path):
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix==".gz" else raw)


def plan():
    jobs=[]
    decks=set()
    for source,partitions in (("train",[("train",96)]),("development",[("dev",20),("confirm",40)])):
        originals=read(ROOT/f"logs/m1-dc1-formal/roots/{source}.json")["jobs"]
        unique={j[3]:j for j in originals if j[1]["encounter"]!="KNOWLEDGE_DEMON_BOSS"}
        ordered=iter(sorted(unique,key=lambda f:digest(["n4-family-1",f])))
        for split,n in partitions:
            for i in range(n):
                family=next(ordered)
                _,spec,_,_,room=unique[family]
                key=tuple(sorted(c["id"] for c in spec["deck"]))
                if key in decks:
                    raise ValueError("Repeated deck family")
                decks.add(key)
                hp=(55,80,100,70)[i%4]
                jobs.append([len(jobs),spec|dict(hp=hp,max_hp=max(hp,80),seed=seed(family,"battle",0)),
                             split,family,room])
    return jobs


def seed(family,domain,i):
    return digest(["n4-world-v1",family,domain,i])[:16].upper()


def runtime(out):
    if checksum(PARENT)!=PARENT_SHA:
        raise ValueError("Frozen G2 changed")
    host=Host(out,BUILD,CFG | dict(lane_recycles=220))
    original=host.project
    host.project=lambda wire:project(original,wire)
    _,meta=load(PARENT)
    return host,Policy(PARENT,meta["deployment"],0,0.,host.version,CFG)


def controller(model,h):
    c=Controller(model,None,lambda rows:next(model.forward([(rows,)])),random.Random(0))
    c.initial_hp,c.initial_max=h["hp"],h["max_hp"]
    return c


def permutation(deck,hand,key):
    free=list(range(len(deck)))
    front=[]
    for c in hand:
        i=next(i for i in free if (deck[i]["id"],deck[i]["upgrade"])==(c["id"],c["upgrade"]))
        free.remove(i)
        front.append(i)
    random.Random(key).shuffle(free)
    return front+free


def start(lane,spec,order=None):
    lane.open()
    fixture={} if order is None else dict(sv1_fixture=dict(n4_order=order))
    return lane.request("pre0_start",spec=spec,cap=CAP,**fixture)["episode"]


def step(lane,state,index):
    next_state=lane.request("i1_n2_step",position=state["actions"],index=int(index))["episode"]
    if next_state["actions"]!=state["actions"]+1:
        raise ValueError("Move did not advance")
    return next_state


def prefix(lane,spec,order,mid):
    state=start(lane,spec,order)
    opening=lane.host.project(state["observation"])
    history=[]
    if mid:
        index=next((a["index"] for a in opening["actions"] if a["kind"]=="play_card" and
                    opening["hand"][a["card"]]["id"] in {"STRIKE_IRONCLAD","DEFEND_IRONCLAD","BASH"}),None)
        if index is not None:
            state=step(lane,state,index)
            history.append([opening,index])
    h=lane.host.project(state["observation"]) if state["status"]=="active" else None
    return history,h,state


def candidates(c,h):
    scores=c.score([(h,c.history)])[0][0]
    order=sorted(range(len(scores)),key=lambda i:(-float(scores[i]),i))
    options=[]
    seen=set()
    for i in order:
        a=h["actions"][i].copy()
        a.pop("index")
        idx=a.pop("card")
        card=None if idx is None else {k:v for k,v in h["hand"][idx].items() if k!="index"}
        key=digest([a,card])
        if key not in seen:
            options.append(i)
            seen.add(key)
    if len(options)>2:
        options=[*options[:2],random.Random(digest(h)).choice(options[2:])]
    return options


def prepared(model,h,hist):
    c=controller(model,hist[0][0] if hist else h)
    for o,i in hist:
        c.history=model.encoder.update(c.history,o,o["actions"][i])
    return c


def finish(lane,model,state,h,hist,index):
    c=prepared(model,h,hist)
    c.project=lane.host.project
    started=perf_counter()
    trace=[]
    while state["status"]=="active" and state["actions"]<CAP:
        public=lane.host.project(state["observation"])
        if not trace:
            if public!=h:
                raise ValueError("Intervention at wrong history")
            c.history=model.encoder.update(c.history,public,public["actions"][index])
        else:
            index,_,_=c.act(public,lane,state["actions"])
        trace.append(index)
        state=step(lane,state,index)
        c.after(state)
    terminal=state.get("terminal_observation")
    status=state["status"] if state["status"]!="active" else "truncated"
    if status in ("predicted_win","death") and terminal is None:
        raise ValueError("Missing terminal")
    result=state.get("result") or {}
    utility=None
    if status=="death":
        utility=-50.
    elif status=="predicted_win":
        utility=payoff(torch.tensor(c.initial_hp-terminal["hp"]),torch.tensor(c.initial_max)).item()
    return dict(status=status,reason=state.get("detail") or state.get("public_reason"),
                terminal=terminal,gold=result.get("gold"),cumulative_loss=result.get("cumulative_loss"),
                utility=utility,actions=trace,seconds=perf_counter()-started)


def one(lane,model,job,k,cap,domain="main"):
    ordinal,spec,split,family,_=job
    anchor=spec|dict(seed=seed(family,"anchor",0))
    original=lane.host.project(start(lane,anchor)["observation"])
    lane.reset()
    hand=original["hand"]
    mid=ordinal%3==1
    out=dict(ordinal=ordinal,split=split,family=family,hand=hand,blocks={},reasons=Counter(),k=k)
    if len(hand)!=5 or original["draw_count"]!=len(spec["deck"])-5:
        return out|dict(stop="opening_zones")
    # The target h is frozen using a donor outside every MC block.
    order=permutation(spec["deck"],hand,seed(family,"anchor-order",0))
    hist,h,_=prefix(lane,anchor,order,mid)
    lane.reset()
    if h is None:
        return out|dict(stop="terminal_prefix")
    opts=candidates(prepared(model,h,hist),h)
    out.update(history=hist,h=h,key=digest([hist,h]),options=opts)
    if len(opts)<2:
        return out|dict(stop="one_semantic_action")
    # Ordinary supervision spends as many completed rollouts as the CF arm, all on greedy Q.
    blocks=[("paired",k),("extra",k*(len(opts)-1))] if split=="train" else [("selection",k),("reference",k)]
    for label,need in blocks:
        records=[]
        out["blocks"][label]=records
        for i in range(cap if label!="extra" else cap*(len(opts)-1)):
            key=seed(family,domain+label,i)
            donor=spec|dict(seed=key)
            order=permutation(spec["deck"],hand,seed(family,domain+label+"-order",i))
            before,obs,state=prefix(lane,donor,order,mid)
            if obs!=h or before!=hist:
                out["reasons"][label+"_different_history"]+=1
                lane.reset()
                continue
            record=dict(proposal=i,seed=key,order=order,outcomes={})
            for j,action in enumerate(opts[:1] if label=="extra" else opts):
                if j:
                    before,obs,state=prefix(lane,donor,order,mid)
                    if before!=hist or obs!=h:
                        raise ValueError("Paired replay drift")
                record["outcomes"][str(action)]=finish(lane,model,state,h,hist,action)
                lane.reset()
            records.append(record)
            if len(records)==need:
                break
    complete=all(len(out["blocks"][name])==n for name,n in blocks)
    resolved=all(res["utility"] is not None for block in out["blocks"].values() for w in block for res in w["outcomes"].values())
    return out|dict(stop="complete" if complete and resolved else "proposal_cap" if not complete else "unresolved_branch")


def run(out,jobs,k_train,k_test,cap,limit_s):
    out.mkdir(parents=True,exist_ok=False)
    write(out/"manifest.json",dict(jobs=jobs,train=k_train,test=k_test,cap=cap,seconds_cap=limit_s))
    host,model=runtime(out)
    counts=Counter()
    start_time=perf_counter()
    try:
        for job in jobs:
            t=perf_counter()
            try:
                row=one(host.lane(),model,job,k_train if job[2]=="train" else k_test,cap)
            except (RuntimeError,StopIteration) as e:
                host.lane().close()
                row=dict(ordinal=job[0],family=job[3],split=job[2],stop="host_or_recipe_error",detail=str(e))
            row["seconds"]=perf_counter()-t
            write(out/f"{job[0]:03}.json.gz",row)
            counts[row["stop"]]+=1
            if perf_counter()-start_time>limit_s:
                break
    finally:
        host.close()
        write(out/"run.json",dict(seconds=perf_counter()-start_time,counts=counts,teacher=model.definition,
                                  source=checksum(Path(__file__)),build=checksum(BUILD/"build.json")))


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("out",type=Path)
    p.add_argument("--slice",type=int,nargs=2,default=(0,156))
    p.add_argument("--train",type=int,default=4)
    p.add_argument("--test",type=int,default=6)
    p.add_argument("--cap",type=int,default=64)
    p.add_argument("--seconds",type=int,default=3200)
    a=p.parse_args()
    run(a.out,plan()[slice(*a.slice)],a.train,a.test,a.cap,a.seconds)
