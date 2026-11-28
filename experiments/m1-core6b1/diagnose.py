"""Replay frozen roots, persist conditional graphs, and evaluate public programs on paired worlds."""
import sys,time
from collections import Counter
from pathlib import Path
from panel import H,E,W,CORE,read,save,gz,digest
from programs import HUMAN,choose
sys.path.insert(0,str(H.parent/"m1-core6a"))
import search6 as s
from common6 import INFRA,public_b,choice_b,torch
sys.path.insert(0,str(INFRA/"experiments/m1-infra2a"))
import worlds as w
from models import strategic,boundary_key,return_law
from semantic import encode,F,CENTERS,pack
from value import payoff
import numpy as np

def custom_graph(host,m,name,st,hist,opening,limit):
    f=st["facts"]; h=public_b(f)
    first=choose(name,0,lambda:m.rank(h,hist,opening)[0],f)
    memory={0:(m.advance(hist,h,h["actions"][first]),1)}
    reply=host.engine.send(dict(op="search",indices=[first],limit=limit,g2=True))
    while reply["type"]=="g2":
        ticket=reply["ticket"]; parent,depth=memory[reply["parent"]]
        try:
            f,p=reply["facts"],reply["prompt"]
            obs=choice_b(f,p) if p else public_b(f)
            j=choose(name,depth,lambda:m.rank(obs,parent,opening)[0],f,p)
            memory[ticket]=(m.advance(parent,obs,obs["actions"][j]),depth+1)
        except Exception:
            host.engine.send(dict(op="g2",ticket=ticket,index=-1));raise
        reply=host.engine.send(dict(op="g2",ticket=ticket,index=j))
    if not reply["ok"]:raise RuntimeError(reply["reason"])
    return reply["result"][0]

def summarize(g,q,opening,states):
    leaves=[]; pm=Counter(); death=0.
    for l in g["leaves"]:
        mass=l["mass"]; kind=l["kind"]
        if kind=="C":
            c=strategic(l["facts"],l["draw"]); k=boundary_key("C",c)
            if k not in states:
                gl,x=encode(c)
                with torch.inference_mode():p=VALUE.evaluate.net(*pack([(gl,x)])).softmax(-1)[0].tolist()
                states[k]=dict(public=c,prob=p,shape=list(x.shape),global_vector=gl.tolist(),
                               tensor_id=w.digest([gl.tolist(),x.tolist()]),features={f:int(np.count_nonzero(x[:,i])) for f,i in F.items() if x[:,i].any()})
            p=states[k]["prob"];death+=mass*p[0]
            for center,prob in zip(CENTERS,p[1:],strict=True):pm[str(opening["hp"]-c["hp"]+center)]+=mass*prob
        else:
            k=boundary_key(kind,l)
            if kind=="Defeat":death+=mass
            else:pm[str(opening["hp"]-l["hp"])]+=mass
        leaves.append(dict(kind=kind,key=k,mass=mass,hp=c["hp"] if kind=="C" else l["hp"],gold=c["gold"] if kind=="C" else l["gold"]))
    assert abs(sum(pm.values())+death-q["coverage"])<2e-5
    if q["value"] is not None:
        predicted=-50*death+sum(prob*float(payoff(torch.tensor(int(loss)),torch.tensor(opening["max_hp"]))) for loss,prob in pm.items())
        assert abs(predicted-q["value"])<.004
    return dict(first=g["index"],policy=g["policy"],leaves=leaves,law=return_law(g),q=q,death_mass=death,opening_loss_mass=pm)

def run_turn(host,m,st,hist,opening,plan,mode,tag):
    hist=hist.copy(); trace=[]; turn=st["facts"]["turn"]
    policy=s.hot.TurnPolicy(plan["policy"]) if mode=="bound" else None
    row=w.blank()
    while st["status"] in ("active","choice") and st["facts"]["turn"]==turn:
        f=st["facts"]; prompt=st if st["status"]=="choice" else None
        h=choice_b(f,st) if prompt else public_b(f)
        ranked=lambda:m.rank(h,hist,opening)[0]
        if policy:j=policy.take(st,row)
        elif mode=="g2":j=ranked()
        else:j=choose(tag,len(trace),ranked,f,prompt)
        a=h["actions"][j]
        trace.append(dict(view=st["view"],kind=a["kind"],index=j,card=f["hand"][a["card"]]["id"] if a["card"] is not None else None,
                          target=a["target"],hp=f["hp"],energy=f["energy"],block=f["block"],hand=[(c["id"],c["cost"]) for c in f["hand"]],
                          foes=[(e["species"],e["hp"],e["move"],e["block"]) for e in f["enemies"]],powers=f["powers"]))
        hist=m.advance(hist,h,a);st=host.call("step",index=j)
        if st.get("observed_c"):break
    if st["status"] in ("Victory","Defeat"):key=boundary_key(st["status"],st["facts"])
    else:
        cut=st.get("observed_c")
        if not cut:raise ValueError("missing real C")
        key=boundary_key("C",strategic(cut["facts"],cut["draw"]))
    return st,hist,trace,key

def outcomes(host,m,root,st,hist,opening,plans,labels,worlds):
    rows=[]
    host.call("checkpoint")
    for seed in [None,*worlds]:
        sides={}
        for tag,mode in labels.items():
            side={};sides[tag]=side
            try:
                sample=host.call("restore",**({} if seed is None else dict(world=seed)))
                assert w.public(sample)==w.public(st)
                after,mem,trace,k=run_turn(host,m,sample,hist,opening,plans[tag],mode,tag)
                side.update(turn_trace=trace,boundary=k,boundary_resources={a:after["facts"][a] for a in ("hp","block","energy","gold","turn","powers","enemies")})
                if plans[tag]["q"]["value"] is not None and k not in plans[tag]["law"]:raise ValueError("actual boundary outside closed law")
                if after["status"] in ("Defeat","Victory"):
                    end=after["facts"];status=after["status"];n=0
                else:
                    battle=w.blank()
                    s.hot.fight(host,root["spec"],m,"tactical",32,battle,resume=(after,mem),require_match=True)
                    end=battle["terminal"];status=battle["status"];n=battle["actual_steps"]
                side.update(status=status,terminal={a:end[a] for a in ("turn","hp","max_hp","gold","stars","energy","block","powers","enemies")},
                            suffix_actions=n,utility=-50 if status=="Defeat" else float(payoff(torch.tensor(opening["hp"]-end["hp"]),torch.tensor(opening["max_hp"]))))
            except w.FAIL as err:side.update(status="failed",reason=str(err)[:400])
        rows.append(dict(seed=seed,sides=sides))
    return rows

def diagnose(host,record,root,m,low):
    t=time.perf_counter();case=dict(prefix=w.blank())
    st,hist=w.recover(w.Recorder(host),m,dict(spec=root["spec"],prefix=root,turn=record["turn"]),case)
    op={a:root["spec"][a] for a in ("hp","max_hp")};h=public_b(st["facts"])
    rank=m.rank(h,hist,op); score=low.guide.scores(h,hist,op)
    graphs={};states={}
    def register(tag,g,q=None):
        if q is None:q=m.backup([g],op)[0]
        graphs[tag]=summarize(g,q,op,states);return tag
    def portfolio(arm,actor):
        ranked=actor.rank(h,hist,op)
        opts=(s.portfolio if arm=="low" else s.original_portfolio)(host,actor,ranked,op,"tactical",32)
        ref=host.reference(rank[0],32,actor,h,hist,op); refid=register(arm+"/ref",ref);rv=graphs[refid]["q"]["value"]
        keys=[register(f"{arm}/{q['style']}/{g['index']}",g,q) for g,q in opts]
        elig=[k for k in keys if rv is not None and graphs[k]["q"]["value"] is not None and graphs[k]["q"]["value"]>rv]
        return (max(elig,key=lambda k:graphs[k]["q"]["value"]) if elig else refid),keys
    h5,h5keys=portfolio("h5",m); selected,lowkeys=portfolio("low",low)
    actual=graphs[selected]
    assert actual["first"]==record["actual"],(record["id"],actual["first"],record["actual"])
    labels={selected:"g2" if actual["q"]["value"] is None else "bound"}
    probes={}
    for tag in HUMAN.get(record["id"],[]):
        for limit in (32,256):
            g=custom_graph(host,m,tag,st,hist,op,limit)
            key=register(tag if limit==256 else tag+"/32",g)
            probes[key]=limit
        labels[tag]="manual"
    if record["group"]!="human":
        opts=[k for k in h5keys+[h5] if graphs[k]["q"]["value"] is not None and graphs[k]["law"]!=actual["law"]]
        if opts:labels[max(opts,key=lambda k:graphs[k]["q"]["value"])]="bound"
    return dict(id=record["id"],turn=record["turn"],menu=h["actions"],g2=rank,guide_scores=score.tolist(),guide_rank=np.argsort(-score,kind="stable").tolist(),
                selected=dict(low=selected,h5=h5,g2=rank[0]),candidates=dict(low=lowkeys,h5=h5keys),graphs=graphs,states=states,probes=probes,labels=labels,
                discovery_seconds=time.perf_counter()-t),st,hist,op

def main(phase):
    global VALUE
    start=time.perf_counter();torch.set_num_threads(1);VALUE=s.Actor("v2");low=s.Actor("low")
    panel=read(E/"panel.json")["roots"]; prefixes=gz(E/"prefixes.gz")
    host=s.SearchClient(W/("host-"+phase),False)
    counts=Counter(); ledger=[]
    try:
        for r in panel:
            if (r["group"]=="human")!=(phase=="human"):continue
            t=time.perf_counter()
            if t-start>(550 if phase=="human" else 1100):break
            try:
                d,st,hist,op=diagnose(host,r,prefixes[r["id"]],VALUE,low)
                if len(d["labels"])>1 and (phase=="human" or counts[r["group"]]<3):
                    counts[r["group"]]+=1
                    seeds=[int(digest(["6b1",r["key"],i])[:7],16) for i in range(8 if phase=="human" else 4)]
                    d["worlds"]=outcomes(host,VALUE,prefixes[r["id"]],st,hist,op,d["graphs"],d["labels"],seeds)
                d["seconds"]=time.perf_counter()-t;save(E/(r["id"]+".gz"),d)
                ledger.append(dict(id=r["id"],seconds=d["seconds"],worlds=len(d.get("worlds",[]))))
            except (ValueError,RuntimeError,AssertionError,KeyError,IndexError) as err:
                ledger.append(dict(id=r["id"],error=repr(err),seconds=time.perf_counter()-t))
    finally:host.close()
    save(E/(phase+"-ledger.json"),dict(rows=ledger,seconds=time.perf_counter()-start))
if __name__=="__main__":main(sys.argv[1])
