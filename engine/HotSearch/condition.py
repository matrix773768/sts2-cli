"""Run matched Hot-only interventions on an exchangeable, public midcombat checkpoint."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time
from client import ROOT,Client
from models import Models,public_b,strategic,torch,payoff,boundary_key,return_law
from semantic import encode
from hot_produce import fight,peak_rss,record_boundary,portfolio as tactical_portfolio
import sys
sys.path.insert(0,str(ROOT))
from engine.HotSearch.native_audit import check as native_check
from models import choice_b


def key(c):
    g,x=encode(c)
    return hashlib.sha256(g.tobytes()+x.tobytes()).hexdigest()


def digest(o):
    return hashlib.sha256(json.dumps(o,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def restore(client,spec,trace,turn,models,prefix):
    st=client.call("open",spec=spec);history=models.g2.encoder.initial_history()
    selected=None
    for t,index in trace:
        if t>=turn:break
        if st["status"]=="choice":
            # Frozen menu selects a candidate then confirms it. Hot resolves the same binding atomically.
            if selected is None:
                selected=index
                continue
            if index!=len(st["options"]) and index!=0:
                # Frozen selected-menu size differs by scope. Verify against the saved public root below.
                raise ValueError("prefix/choice_confirmation")
            obs=choice_b(st["facts"],st)
            history=models.advance(history,obs,obs["actions"][selected])
            prefix["choices"].append(dict(at=len(prefix["trace"])-1,options=st["options"],selected=selected))
            st=client.call("step",index=selected);selected=None
        else:
            h=public_b(st["facts"])
            if h["turn"]!=t:raise ValueError("prefix/turn")
            record_boundary(prefix,st["facts"],h,index)
            history=models.g2.encoder.update(history,h,h["actions"][index])
            st=client.call("step",index=index)
    if st["status"]!="active" or st["facts"]["turn"]!=turn:raise ValueError("prefix/root")
    return st,history


def run(out,ids,limit,split="train",audit=False,hot_pairs=False,diagnostic=False,arm="tactical",suffix_limit=32,native_worlds=0):
    out.mkdir(parents=True,exist_ok=False)
    if hot_pairs:
        if split!="train" or audit:raise ValueError("hot pair panel is the train intervention panel")
        panel=[w|dict(source=split,index=i) for i,w in enumerate(json.load(gzip.open(ROOT/"experiments/m1-core5d/evidence/panel.gz"))[split])]
        groups=json.loads((ROOT/"experiments/m1-infra0/panel.json").read_bytes())["pairs"]
        if ids is None:ids=groups["two_continuations"]+groups["natural_reuse"]
    else:
        panel=json.load(gzip.open(ROOT/"logs/infra0-world-inputs/panel.gz"))[split]
        if ids is None:ids=list(range(len(panel)))
    world_count=0 if hot_pairs else 12 if audit else 8 if split=="dev" else 4
    old={}
    for source in (set() if hot_pairs else {panel[i]["source"] for i in ids}):
        for p in (ROOT/"experiments/m1-core5d/evidence").glob(source+"-V2-*.gz"):
            for r in map(json.loads,gzip.open(p)):old[source,r["i"]]=r
    start=time.perf_counter();cpu=time.process_time()
    models=Models();identity=models.identity(arm,suffix_limit);client=Client(out/"transport")
    try:
        with gzip.open(out/"worlds.jsonl.gz","xt",encoding="utf8") as stream:
            for i in ids:
                w=panel[i];s=w["spec"]
                case=dict(i=i,split=split,world_count=world_count,source=w["source"],source_index=w["index"],family=w["family"],turn=2,
                          worlds=[],plans=[],natural_pair=[],states={},status="failed",work=0)
                try:
                    prefix=dict(trace=[],choices=[],states=[],queries=[],actual_steps=0)
                    case.update(prefix=prefix,policy_id=identity["id"],policy_version="h4-public-program-v1",suffix_arm=arm,suffix_limit=suffix_limit)
                    if hot_pairs:
                        reached=fight(client,s,models,arm,suffix_limit,prefix,until=2,require_match=not diagnostic)
                        case["prefix"]=prefix
                        if reached is None:raise ValueError("terminal before midcombat root")
                        st,hist=reached
                    else:
                        st,hist=restore(client,s,old[w["source"],w["index"]]["trace"],2,models,prefix)
                    facts=st["facts"];opening={k:s[k] for k in ("hp","max_hp")}
                    if not hot_pairs and split=="train" and i==123:
                        archive=json.loads((ROOT/"experiments/m1-infra1h2/evidence/slug123.json").read_bytes())
                        b=archive["wire"]
                        if ([(c["id"],c["upgrade"]) for c in b["hand"]]!=[(c["id"],c["upgrade"]) for c in facts["hand"]]
                            or [e["hp"] for e in b["enemies"]]!=[e["hp"] for e in facts["enemies"]]
                            or any(facts[k]!=b[k] for k in ("hp","max_hp","block","energy","stars","draw_count"))
                            or any(facts["belief"][k]!=archive["law"][k] for k in ("counts","top","bottom"))):
                            raise ValueError("frozen 123 public root mismatch")
                    case["public"]=digest(facts);case["belief"]=facts["belief"]
                    if facts["belief"]["top"] or facts["belief"]["bottom"] or len(facts["belief"]["counts"])<2:
                        raise ValueError("not an exchangeable multitype tail")
                    rank=models.rank(public_b(facts),hist,opening)
                    def portfolio():
                        if arm=="contingent":
                            return [g|dict(then_end=o["style"]=="end",style=o["style"])
                                    for g,o in tactical_portfolio(client,models,rank,opening,arm,limit)]
                        return [r|dict(then_end=style=="end",style=style) for style in ("light","guard","build","end")
                                for r in client.call("search",indices=rank,limit=limit,style=style)]
                    graph=portfolio()
                    q=[q|dict(then_end=r["then_end"],style=r["style"]) for r in graph for q in models.backup([r],opening)]
                    case["query"]=q;case["work"]=sum(a["steps"] for a in graph)
                    candidates=sorted((a for a in q if a["value"] is not None),key=lambda a:-a["value"])
                    for a in candidates:
                        result=next(r for r in graph if r["index"]==a["index"] and r["style"]==a["style"])
                        dist={}
                        for leaf in result["leaves"]:
                            k=key(strategic(leaf["facts"],leaf["draw"])) if leaf["kind"]=="C" else leaf["kind"]+"/"+str(leaf["hp"])
                            dist[k]=dist.get(k,0.)+leaf["mass"]
                        if any(p["law"]==dist for p in case["plans"]):continue
                        for leaf in result["leaves"]:
                            if leaf["kind"]=="C":
                                c=strategic(leaf["facts"],leaf["draw"]);case["states"][boundary_key("C",c)]=c
                        case["plans"].append(dict(first=a["index"],then_end=a["then_end"],style=a["style"],policy=result["policy"],value=a["value"],law=dist,public_law=return_law(result)))
                        if len(case["plans"])==2:break
                    if len(case["plans"])<2:raise ValueError("two distinct complete turn laws unavailable")
                    client.call("checkpoint")
                    for world in range(-1,world_count):
                        seed=int(digest(["5e-audit" if audit else "5e-estimate",split,w["family"],s["seed"],2,world])[:7],16)
                        sides=[]
                        if world<0:case["natural_pair"]=sides
                        else:case["worlds"].append(dict(seed=seed,outcomes=sides))
                        for plan in case["plans"]:
                            row=dict(states=[],queries=[],trace=[],choices=[],actual_steps=0)
                            try:
                                sample=client.call("restore",**({"world":seed} if world>=0 else {}))
                                if sample["facts"]!=facts:raise ValueError("resampling changed public state")
                                if world==0 and not sides:
                                    perturbed=client.call("restore",world=seed,audit_rng=seed)
                                    if perturbed["facts"]!=facts:raise ValueError("private RNG changed public root")
                                    again=portfolio()
                                    case["work"]+=sum(a["steps"] for a in again)
                                    if digest(graph)!=digest(again):raise ValueError("private permutation/RNG changed public search")
                                    case["invariant"]=True
                                    sample=client.call("restore",world=seed)
                                fight(client,s,models,arm,suffix_limit,row,resume=(sample,hist.copy()),first=plan["first"],then_end=plan["then_end"],
                                      require_match=not diagnostic,intervention_law=plan["public_law"],intervention_policy=plan["policy"])
                                end=row["terminal"];observed=key(row["states"][0]) if row["states"] else row["status"]+"/"+str(end["hp"])
                                cut=row["states"][0] if row["states"] else None
                                public_key=boundary_key("C",cut) if cut else boundary_key(row["status"],end)
                                if cut:case["states"][public_key]=cut
                                sides.append(dict(status=row["status"],hp=end["hp"],max_hp=end["max_hp"],gold=end["gold"],observed=observed,
                                    matched=observed in plan["law"],public_key=public_key,public_matched=public_key in plan["public_law"],actual_steps=row["actual_steps"],
                                    search_steps=sum(q["reference_law"]["steps"]+sum(o["steps"] for o in q["options"]) for q in row["queries"]),
                                    utility=-50 if row["status"]=="Defeat" else float(payoff(torch.tensor(s["hp"]-end["hp"]),torch.tensor(s["max_hp"])))))
                                if native_worlds and world<native_worlds:
                                    witness=dict(trace=prefix["trace"]+row["trace"],
                                        boundaries=prefix.get("boundaries",[])+row.get("boundaries",[]),
                                        choices=prefix["choices"]+[c|dict(at=c["at"]+len(prefix["trace"])) for c in row["choices"]],
                                        terminal=end,status=row["status"])
                                    intervention=dict(at=len(prefix["trace"]),seed=seed,counts=facts["belief"]["counts"]) if world>=0 else None
                                    sides[-1]["native_trace"]=witness
                                    tick=time.perf_counter()
                                    sides[-1]["native_meter"]={}
                                    try:sides[-1]["native"]=native_check(out,s,witness,intervention,meter=sides[-1]["native_meter"])
                                    except (KeyError,ValueError,RuntimeError,TimeoutError) as e:sides[-1]["native"]=dict(status="audit_error",reason=str(e)[:300])
                                    sides[-1]["native_seconds"]=time.perf_counter()-tick
                            except (KeyError,RuntimeError,ValueError,IndexError) as e:
                                sides.append(dict(status="failed",reason=str(e)[:300],actual_steps=row["actual_steps"],
                                    failed_boundary=next((q for q in [row.get("intervention",{}),*row["queries"]] if q.get("matched") is False),None)))
                    outcomes=case["natural_pair"]+[r for w in case["worlds"] for r in w["outcomes"]]
                    case["status"]="matched" if all(r.get("matched") and r.get("public_matched") for r in outcomes) else "law_or_execution_gap"
                    if any(r["native"]["status"]!="matched" for r in outcomes if "native" in r):
                        case["status"]="native_audit_gap"
                except (ValueError,RuntimeError,KeyError,IndexError) as e:case["reason"]=str(e)[:300]
                stream.write(json.dumps(case,separators=(",",":"))+"\n");stream.flush()
        host=client.call("metrics")
    finally:client.close()
    (out/"ledger.json").write_text(json.dumps(dict(policy=identity,model_work=models.work|dict(v2_inferred=models.evaluate.misses),ids=ids,limit=limit,diagnostic=diagnostic,wall=time.perf_counter()-start,
        python_cpu=time.process_time()-cpu,python_peak_rss=peak_rss(),host=host),indent=2))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("output",type=Path)
    p.add_argument("--ids",type=int,nargs="+");p.add_argument("--limit",type=int,default=128)
    p.add_argument("--split",choices=["train","dev"],default="train");p.add_argument("--audit",action="store_true")
    p.add_argument("--hot-pairs",action="store_true",help="generate independent midcombat prefixes and paired natural suffixes")
    p.add_argument("--diagnostic",action="store_true",help="continue matching the intervention after later policy-law mismatches")
    p.add_argument("--arm",choices=["tactical","contingent","turn"],default="tactical")
    p.add_argument("--suffix-limit",type=int,default=32)
    p.add_argument("--native-worlds",type=int,default=0,help="audit original plus this many resampled worlds per root")
    a=p.parse_args();run(a.output,a.ids,a.limit,a.split,a.audit,a.hot_pairs,a.diagnostic,a.arm,a.suffix_limit,a.native_worlds)
