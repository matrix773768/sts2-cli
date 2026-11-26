"""Frozen public plans followed by a specified policy, paired in independently accepted worlds."""
import argparse
from collections import Counter
from pathlib import Path
from time import perf_counter
from design import CFG, LOGS, PARENT, choices, digest, jobs, position, prepared, read, runtime, step, torch, world, write
from value import payoff


def rollout(lane,model,hist,h,st,path,budget,*,diagnostics=False):
    start=perf_counter()
    model.budget=budget
    c=prepared(model,h,hist)
    c.project=lane.host.project
    trace=[]
    post=[]
    first=None
    try:
        while st["status"]=="active" and st["actions"]<128:
            public=lane.host.project(st["observation"])
            if not public["enemies"] and public["decision"].get("effect")=="MoveToDrawTop":
                a=public["actions"][0]["index"]
                post.append(a)
            elif len(trace)<len(path):
                key,a=path[len(trace)]
                if digest(public)!=key:
                    raise ValueError("Public deterministic path drift")
                c.history=model.encoder.update(c.history,public,public["actions"][a])
                trace.append(a)
            else:
                a,_,_=c.act(public,lane,st["actions"])
                trace.append(a)
            st=step(lane,st,a)
            c.after(st)
            if first is None and st["status"]=="active":
                o=lane.host.project(st["observation"])
                first=dict(counter=o["nunchaku"],energy=o["energy"],turn=o["turn"])
        status=st["status"] if st["status"]!="active" else "truncated"
        term=st.get("terminal_observation")
        res=st.get("result") or {}
        u=None
        if status in ("predicted_win","death"):
            if not term or len(trace)<len(path):
                raise ValueError("Premature or missing terminal")
            u=-50. if status=="death" else float(payoff(torch.tensor(c.initial_hp-term["hp"]),torch.tensor(c.initial_max)))
        info=dict(counts=dict(c.counts),timing=dict(c.timing)) if diagnostics else {}
        return dict(status=status,detail=st.get("detail") or st.get("public_reason"),utility=u,terminal=term,
            gold=res.get("gold"),loss=res.get("cumulative_loss"),trace=trace,post_terminal_selection=post,
            after_first=first,seconds=perf_counter()-start,**info)
    finally:
        model.budget=0


def one(lane,model,j,n,k,reference,budgets,domain=""):
    anchor=world(j,"anchor",0)
    hist,h,st=position(lane,j,n,anchor)
    row=dict(id=j["id"],family=j["family"],split=j["split"],counter=n,history=hist,h=h,worlds={},failures=Counter(),k=[k,reference])
    if h is None:
        lane.reset()
        return row|dict(stop="anchor_prefix_unavailable")
    opts=choices(lane,model,h,hist)
    lane.reset()
    if opts is None:
        return row|dict(stop="no_eligible_graph_endpoint")
    row.update(opts)
    for block,need in (("selection",k),("reference",reference)):
        ws=row["worlds"][block]=[]
        for i in range(need*20):
            w=world(j,domain+block,i)
            before,obs,st=position(lane,j,n,w)
            if before!=hist or obs!=h:
                row["failures"][block+"_public_mismatch"]+=1
                lane.reset()
                continue
            results={}
            for b in budgets:
                ys={}
                cached={}
                for key,path in opts["paths"].items():
                    ident=digest(path)
                    if ident not in cached:
                        if cached or results:
                            before,obs,st=position(lane,j,n,w)
                            if before!=hist or obs!=h:
                                raise ValueError("Repeat drift")
                        cached[ident]=rollout(lane,model,hist,h,st,path,b)
                        lane.reset()
                    ys[key]=ident
                results[str(b)]=dict(refs=ys,outcomes=cached)
            ws.append(w|dict(results=results))
            if len(ws)==need:
                break
    complete=all(len(row["worlds"][b])==need for b,need in (("selection",k),("reference",reference)))
    resolved=all(y["utility"] is not None for ws in row["worlds"].values() for w in ws for rec in w["results"].values() for y in rec["outcomes"].values())
    return row|dict(stop="proposal_cap" if not complete else "unresolved" if not resolved else "complete")


def run(out,lo,hi,k,ref):
    out.mkdir(parents=True,exist_ok=False)
    js=jobs()[lo:hi]
    write(out/"manifest.json",dict(jobs=js,selection=k,reference=ref,graph=128,strong_subset="id % 6 == 0",counterfactual_domain="n4b-donor"))
    host,model=runtime(out)
    start=perf_counter()
    try:
        for j in js:
            for n in j["counts"]:
                tick=perf_counter()
                row=one(host.lane(),model,j,n,k,ref,[0,24] if j["id"]%6==0 else [0])
                write(out/f"{j['id']:03}-{n}.json.gz",row|dict(seconds=perf_counter()-tick))
    finally:
        host.close()
        write(out/"run.json",dict(seconds=perf_counter()-start,teacher=model.definition))


if __name__=="__main__":
    cli=argparse.ArgumentParser()
    cli.add_argument("out",type=Path)
    cli.add_argument("lo",type=int)
    cli.add_argument("hi",type=int)
    cli.add_argument("--k",default=4,type=int)
    cli.add_argument("--ref",default=8,type=int)
    a=cli.parse_args()
    run(a.out,a.lo,a.hi,a.k,a.ref)
