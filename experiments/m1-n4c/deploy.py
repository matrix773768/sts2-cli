"""Full-episode deployment of frozen, publicly witnessed policies."""
import argparse
from collections import Counter, deque
from copy import copy
from time import perf_counter
import numpy as np
from pilot_protocol import ARMS, LOGS, PROTOCOL, cohort, design, digest, gate, jobs, read, write
from design import prepared, extract, step, torch
from learn_menu import restore
from plan_value import features
from value import payoff

QFILE=LOGS/"n4b-finalfit/counter_pair-17-20.pt"
DIAGNOSTICS=("plan_once128","pair_once128","pair_once24","gate_once","gate128")

def position(lane,j,w):
    if j["domain"]=="natural":
        st=cohort.start(lane,j["spec"]|dict(seed=w["seed"]))
        return [],lane.host.project(st["observation"]),st
    if j["domain"].startswith("transfer_multi"):
        # Preserve natural enemy HP and intents. Condition on their whole public
        # history by rejection, using the same draw/deal and legal prefix.
        class NaturalEnemyHP:
            host=lane.host
            open=lane.open
            def request(self,command,**args):
                if command=="pre0_start":
                    args["sv1_fixture"].pop("enemy_hp")
                return lane.request(command,**args)
        return design.position(NaturalEnemyHP(),j,j["counter"],w)
    return design.position(lane,j,j["counter"],w)

def options(lane,c,h,cap,compromise=True):
    graph=lane.request("i1_sv1_graph",mode="tree",public_run=True,transitions=cap,
        depth=8,wall_ms=1500,memory_bytes=512*2**20)
    info=dict(transitions=graph["transitions"],stop=graph.get("stop") or "exhausted",
              boundaries=len(graph["boundaries"]))
    if info["stop"] in ("wall_cap","managed_memory_cap"):
        return [],info
    _,_,ends,skipped=extract(graph,c.project,c.model.encoder,h,c.history)
    pool=[]
    for item,path in ends:
        last=path[-1]
        u=last.observation
        if item["kind"]=="victory":
            damage=sum(e["hp"] for e in h["enemies"])
            hp=item["public"]["hp"]
        elif item["kind"]=="end_play_a" and len(path)>1 and u["actions"][last.index]["kind"]=="end_turn":
            damage=sum(e["hp"] for e in h["enemies"])-sum(e["hp"] for e in u["enemies"])
            hp=u["hp"]
        else:
            continue
        pool.append(dict(steps=design.path_steps(path),damage=damage,block=u["block"],hp=hp,kind=item["kind"]))
    info.update(candidates=len(pool),skipped=dict(skipped))
    if not pool:
        return [],info
    attack=max(pool,key=lambda p:(p["damage"],p["block"],p["hp"],-len(p["steps"])))
    defend=max(pool,key=lambda p:(p["block"],p["hp"],p["damage"],-len(p["steps"])))
    # Keep the fitted extremes. A third public Pareto compromise uses the same 16 features.
    third=max(pool,key=lambda p:(min(p["damage"]/max(1,attack["damage"]),p["block"]/max(1,defend["block"])),
                                 p["hp"],p["damage"],-len(p["steps"])))
    menu=(attack,defend,third) if compromise else (attack,defend)
    return list({digest(p["steps"]):p for p in menu}.values()),info

def eligible(arm,h,queries,turns):
    if h["decision"]["phase"]!="combat":
        return False
    if arm=="gate_once":
        return not queries and gate(h)
    if arm.endswith("_gate") or arm=="gate128":
        return gate(h) and h["turn"] not in turns
    if arm=="plan_turn":
        return h["turn"] not in turns
    if arm in ("plan_once","plan_once128","pair_once128","pair_once24"):
        return not queries
    if arm.endswith("_budget"):
        return queries<4 and h["turn"] not in turns
    return arm in ("plan_all","mixed_all")

def episode(lane,m,q,j,w,arm,weights,reference,timed=False):
    t=perf_counter()
    hist,h,st=position(lane,j,w)
    if h is None or digest([hist,h])!=reference:
        raise ValueError("Public root/history replay drift")
    c=prepared(m,h,hist)
    c.project=lane.host.project
    qc=prepared(q,h,hist) if arm.startswith("q_") else None
    if qc:
        qc.project=lane.host.project
        q.budget=24 if arm=="q_budget" else 0
    turns=set()
    queue=deque()
    trace=[]
    events=[]
    counts=Counter()
    if timed:
        def instrument(controller,label):
            forward=controller.score
            def measured(states):
                tick=perf_counter()
                result=forward(states)
                counts[label+"_score_seconds"]+=perf_counter()-tick
                counts[label+"_states"]+=len(states)
                counts[label+"_calls"]+=1
                return result
            controller.score=measured
        instrument(c,"g2")
        if qc:
            instrument(qc,"q")
    admin=[]
    m.budget=24 if arm=="search" else 0
    while st["status"]=="active" and st["actions"]<128:
        o=lane.host.project(st["observation"])
        pos=st["actions"]
        if not o["enemies"] and o["decision"].get("effect")=="MoveToDrawTop":
            a=o["actions"][0]["index"]
            admin.append(a)
        elif arm in ("search","g2"):
            tick=perf_counter()
            a,_,_=c.act(o,lane,pos)
            counts["decision_seconds"]+=perf_counter()-tick
            trace.append(a)
        else:
            decision_start=perf_counter()
            key=digest(o)
            query=not queue and eligible(arm,o,len(events),turns)
            if query:
                turns.add(o["turn"])
            direct=None
            if queue:
                exp,a=queue.popleft()
                if key!=exp:
                    raise ValueError("Witness diverged from legal observation")
            elif arm=="q_budget" and query:
                direct=int(c.score([(o,c.history)])[0][0].argmax())
                before_transitions=qc.counts["transitions"]
                try:
                    proposed,reason=qc.search(o,lane,pos)
                except ValueError as exc:
                    proposed,reason=None,str(exc)
                a=direct if proposed is None else proposed
                path=design.path_steps(list(qc.plan))
                queue.extend(path[1:])
                qc.plan.clear()
                qc.predicted_end=None
                events.append(dict(pos=pos,turn=o["turn"],h=key,a=a,direct=direct,
                    path=path,stop=reason,transitions=qc.counts["transitions"]-before_transitions))
            elif arm=="q_all" or (arm=="q_gate" and query):
                a=int(qc.score([(o,qc.history)])[0][0].argmax())
                if query:
                    direct=int(c.score([(o,c.history)])[0][0].argmax())
                    events.append(dict(pos=pos,turn=o["turn"],h=key,a=a,direct=direct))
            elif query:
                tick=perf_counter()
                ps,info=options(lane,c,o,128 if arm.endswith("128") else 24,not arm.startswith("pair_once"))
                if timed:
                    counts["endpoint_generation_seconds"]+=perf_counter()-tick
                tick=perf_counter()
                vals=[float(features(dict(h=o,endpoints=ps),k)@weights) for k in range(len(ps))]
                if timed:
                    counts["ridge_seconds"]+=perf_counter()-tick
                chosen=int(np.argmax([0.,*vals]))-1
                direct=int(c.score([(o,c.history)])[0][0].argmax())
                a=direct
                if chosen>=0:
                    queue.extend(ps[chosen]["steps"])
                    exp,a=queue.popleft()
                    if exp!=key:
                        raise ValueError("Witness starts at different root")
                events.append(dict(pos=pos,turn=o["turn"],h=key,direct=direct,a=a,chosen=chosen,
                    scores=vals,paths=ps,**info))
            else:
                a=int(c.score([(o,c.history)])[0][0].argmax())
            counts["decision_seconds"]+=perf_counter()-decision_start
            c.history=m.encoder.update(c.history,o,o["actions"][a])
            if qc:
                qc.history=q.encoder.update(qc.history,o,o["actions"][a])
            trace.append(a)
        st=step(lane,st,a)
        c.after(st)
    if queue:
        raise ValueError("Unconsumed committed witness")
    status=st["status"] if st["status"]!="active" else "truncated"
    term=st.get("terminal_observation")
    resolved=status in ("predicted_win","death")
    loss=c.initial_hp-term["hp"] if resolved else None
    utility=(-50. if status=="death" else float(payoff(torch.tensor(loss),torch.tensor(c.initial_max)))) if resolved else None
    res=st.get("result") or {}
    return dict(trace=trace,admin=admin,events=events,counts=dict(c.counts+counts),status=status,
        initial_hp=c.initial_hp,terminal=term,net_loss=loss,gold=res.get("gold"),utility=utility,
        reason=st.get("detail") or st.get("public_reason"),cumulative_loss=res.get("cumulative_loss"),
        seconds=perf_counter()-t)

def repaired(j):
    spec=j["spec"]
    card="HEAVY_BLADE"
    if j["domain"]!="transfer" or not any(c["id"]==card for c in spec["deck"][5:10]):
        return None
    deck=[(c|dict(id="HEMOKINESIS") if 5<=i<10 and c["id"]==card else c) for i,c in enumerate(spec["deck"])]
    return j|dict(spec=spec|dict(deck=deck),domain="transfer_repair")

def run(out,split,lo,hi,arms,mixed,repair=False,multi=False,extended=False,stress=False,timed=False):
    out.mkdir(parents=True,exist_ok=False)
    js=[j for j in jobs(replication=split=="replication") if j["split"]==split and lo<=j["id"]<hi]
    if repair:
        js=[k for j in js if (k:=repaired(j))]
    if multi:
        js=[(repaired(j) or j)|dict(domain="transfer_multi_extended" if extended else "transfer_multi") for j in js
            if j["domain"]=="transfer" and j["spec"]["encounter"]=="SNAPPING_JAXFRUIT_NORMAL"]
    if stress:
        js=[j for j in js if j["domain"]=="target" and j["id"] in (14,18)]
    if timed:
        js=[j for j in js if j["domain"]=="natural"]
    ridge=np.asarray(read(LOGS/"n4b-plan.json")["weights"])
    mix=np.asarray(read(mixed)["weights"]) if mixed else None
    write(out/"manifest.json",dict(protocol=PROTOCOL,jobs=js,arms=arms,weights=ridge.tolist(),
        mixed=mix.tolist() if mixed else None,q_sha=cohort.checksum(QFILE)))
    host,m=design.runtime(out)
    q=copy(m)
    q.net,q.encoder,q.slot=restore(QFILE)
    lane=host.lane()
    begin=perf_counter()
    try:
        for j in js:
            row=dict(id=j["id"],family=j["family"],domain=j["domain"],split=split,encounter=j["spec"]["encounter"],
                     worlds=[],failures=Counter(),anchor=None)
            need=12 if stress else 1 if j["domain"]=="natural" else 4 if split=="replication" else 2
            try:
                anchor=design.world(j,"n4c-anchor",0)
                if j["domain"]!="natural":
                    history,h,_=position(lane,j,anchor)
                    if h is None:
                        raise ValueError("anchor prefix incomplete")
                    row["anchor"]=digest([history,h])
                    lane.reset()
                for i in range(512 if extended else need*20):
                    w=design.world(j,"n4c-loss-diagnostic" if stress else "n4c-reference",i)
                    history,h,_=position(lane,j,w)
                    lane.reset()
                    k=digest([history,h])
                    if h is None or row["anchor"] not in (None,k):
                        row["failures"]["public_history_mismatch"]+=1
                        continue
                    ys={}
                    order=sorted(arms,key=lambda name:digest(["n4c-timing",j["family"],name])) if timed else arms
                    for name in order:
                        try:
                            ys[name]=episode(lane,m,q,j,w,name,mix if name.startswith("mixed_") else ridge,k,timed)
                            lane.reset()
                        except (RuntimeError,ValueError,KeyError) as exc:
                            ys[name]=dict(status="unresolved",reason=str(exc),utility=None)
                            lane.close()
                    row["worlds"].append(dict(world=w,public=k,outcomes=ys))
                    if len(row["worlds"])==need:
                        break
                row["stop"]="complete" if len(row["worlds"])==need else "proposal_cap"
            except (ValueError,RuntimeError,KeyError,StopIteration) as exc:
                row["stop"]="unqualified"
                row["error"]=str(exc)
                lane.close()
            write(out/f"{j['id']:03}-{j['domain']}.json.gz",row)
    finally:
        host.close()
        write(out/"run.json",dict(seconds=perf_counter()-begin,teacher=m.definition))

if __name__=="__main__":
    from pathlib import Path
    cli=argparse.ArgumentParser()
    cli.add_argument("out",type=Path)
    cli.add_argument("split",choices=("dev","confirm","replication"))
    cli.add_argument("lo",type=int)
    cli.add_argument("hi",type=int)
    cli.add_argument("--arms",nargs="+",choices=(*ARMS,"mixed_gate","mixed_all",*DIAGNOSTICS),default=ARMS)
    cli.add_argument("--mixed",type=Path)
    cli.add_argument("--repair",action="store_true")
    cli.add_argument("--multi",action="store_true")
    cli.add_argument("--stress",action="store_true",help="post-hoc independent donor audit for the two observed win-to-death families")
    cli.add_argument("--timed",action="store_true",help="interleaved instrumented natural battles")
    cli.add_argument("--extended",action="store_true",help="512 public-history rejection proposals for multi-enemy fixtures")
    a=cli.parse_args()
    if any(name.startswith("mixed_") for name in a.arms) and not a.mixed:
        cli.error("mixed deployment requires its fitted weights")
    if a.extended and not a.multi:
        cli.error("--extended requires --multi")
    run(a.out,a.split,a.lo,a.hi,a.arms,a.mixed,a.repair,a.multi,a.extended,a.stress,a.timed)
