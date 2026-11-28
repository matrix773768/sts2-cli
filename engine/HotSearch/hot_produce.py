"""Produce isolated, labelled Hot-only trajectories from the frozen natural panel."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import time
import ctypes
from ctypes import wintypes


def peak_rss(handle=-1):
    class Counters(ctypes.Structure):
        _fields_=[("cb",wintypes.DWORD),("faults",wintypes.DWORD)]+[(k,ctypes.c_size_t) for k in ("peak","rss","p1","p2","p3","p4","p5","p6")]
    record=Counters()
    record.cb=ctypes.sizeof(record)
    if not ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(handle),ctypes.byref(record),record.cb):
        raise ctypes.WinError()
    return record.peak
from client import BUILD, ROOT, Client
from models import Models, public_b, strategic, choice_b, boundary_key, return_law


def panel():
    source=json.loads((ROOT/"experiments/m1-infra0/panel.json").read_bytes())["natural"]
    return list(dict.fromkeys(i for group in source.values() for i in group))


def record_boundary(row,f,h,selected):
    row["trace"].append([f["turn"],selected,h["actions"][selected]["kind"],h["actions"][selected].get("card"),h["actions"][selected]["target"],h["actions"][selected]["target_side"]])
    row.setdefault("boundaries",[]).append(dict(turn=f["turn"],hp=f["hp"],max_hp=f["max_hp"],block=f["block"],
        energy=f["energy"],hand=[(c["id"],c["upgrade"]) for c in f["hand"]],foes=[(e["species"],e["hp"],e["block"]) for e in f["enemies"]]))


class TurnPolicy:
    def __init__(self, edges):
        self.cursor=0
        self.edges={(e["parent"],e["view"]):e for e in edges}

    def take(self, step, row):
        view=step["view"]
        edge=self.edges.get((self.cursor,view))
        if edge is None:
            row["policy_failure"]=dict(parent=self.cursor,actual=view,expected=[v for parent,v in self.edges if parent==self.cursor],facts=step["facts"])
            raise ValueError("policy/observation_outside_evaluated_program")
        row.setdefault("executed_bindings",[]).append([self.cursor,view,edge["index"]])
        self.cursor=edge["node"]
        return edge["index"]


def portfolio(client,models,rank,opening,arm,limit):
    groups=[]
    common=set()
    styles=("light","guard","build","end","setup") if arm=="contingent" else ("light","guard","build","end")
    for style in styles:
        indices=[i for i in rank if i not in common]
        if not indices:break
        graphs=client.call("search",indices=indices,limit=limit,style=style)
        values=models.backup(graphs,opening,annotate=arm=="contingent")
        for graph,value in zip(graphs,values):
            option=value|dict(style=style)
            if arm=="contingent" and not graph["gaps"] and len(graph["policy"])==1:
                # No second player decision occurs before any leaf. Continuation style has no effect.
                common.add(graph["index"])
                option["equivalent_remaining_styles"]=True
            groups.append((graph,option))
    if arm=="contingent":
        from contingent import synthesize
        groups.extend(list(synthesize(groups)))
    return groups


def fight(client,spec,models,arm,limit,row,*,resume=None,until=None,first=None,then_end=False,require_match=False,intervention_law=None,intervention_policy=None,margin=0.):
    if resume is None:
        step=client.call("open",spec=spec)
        history=models.g2.encoder.initial_history()
    else:
        step,history=resume
    locked=None
    program=TurnPolicy(intervention_policy) if intervention_policy is not None else None
    queried=None
    prediction=None
    if intervention_law is not None:
        prediction={"law":intervention_law}
        row["intervention"]=prediction
    opening={k:spec[k] for k in ("hp","max_hp")}
    while step["status"]=="active":
        f=step["facts"];h=public_b(f)
        if until is not None and f["turn"]>=until:return step,history
        rank=[] if program is not None else models.rank(h,history,opening)
        selected=rank[0] if rank else None
        if first is not None:
            selected=first;first=None;locked=f["turn"]
        elif locked==f["turn"] and program is not None:
            selected=None
        elif locked==f["turn"]:
            raise ValueError("policy/missing_intervention_program")
        elif arm in ("turn","feedback","tactical","contingent") and queried!=f["turn"] and len(rank)>1:
            then_end=False
            queried=f["turn"]
            ids=list(dict.fromkeys([*rank[:2],len(rank)-1]))
            groups=[]
            if arm in ("tactical","contingent"):
                groups=portfolio(client,models,rank,opening,arm,limit)
            elif arm=="feedback":
                results=[client.reference(i,limit,models,h,history,opening) for i in ids if i!=rank[0]]
            else:
                results=client.call("search",indices=ids,limit=limit)
            if arm not in ("tactical","contingent"):
                groups=list(zip(results,models.backup(results,opening)))
            options=[v for g,v in groups]
            ref_graph=client.reference(rank[0],limit,models,h,history,opening)
            reference=models.backup([ref_graph],opening)[0]
            row["queries"].append(dict(turn=f["turn"],reference=rank[0],options=options,reference_law=reference))
            if reference["value"] is not None:
                complete=[o for o in options if o["value"] is not None and o["value"]>reference["value"]+margin]
                graph=ref_graph
                if complete:
                    winner=max(complete,key=lambda o:o["value"])
                    selected=winner["index"]
                    graph=next(g for g,v in groups if v is winner)
                    row["queries"][-1]["winner_style"]=winner.get("style",arm)
                locked=f["turn"]
                program=TurnPolicy(graph["policy"])
                row["queries"][-1]["policy"]=graph["policy"]
                prediction=row["queries"][-1]
                prediction["law"]=return_law(graph)
            row["queries"][-1].update(selected=selected,committed="winner_style" in row["queries"][-1])
        if program is not None: selected=program.take(step,row)
        record_boundary(row,f,h,selected)
        history=models.g2.encoder.update(history,h,h["actions"][selected])
        row["actual_steps"]+=1
        step=client.call("step",index=selected)
        while step["status"]=="choice":
            ch=choice_b(step["facts"],step)
            pick=program.take(step,row) if program is not None else models.rank(ch,history,opening)[0]
            history=models.advance(history,ch,ch["actions"][pick])
            row["choices"].append(dict(at=len(row["trace"])-1,turn=f["turn"],kind=step["kind"],options=step["options"],selected=pick))
            row["actual_steps"]+=1
            step=client.call("step",index=pick)
        if step.get("observed_c"):
            cut=step["observed_c"]
            row["states"].append(strategic(cut["facts"],cut["draw"]))
        if prediction is not None and (step["status"]!="active" or step.get("observed_c")):
            if step.get("observed_c"):
                observed=boundary_key("C",row["states"][-1])
            else:
                observed=boundary_key(step["status"],step["facts"])
            prediction["observed"]=observed
            prediction["matched"]=observed in prediction["law"]
            if require_match and not prediction["matched"]:
                raise ValueError("conditional_policy/realized_boundary_outside_law")
            prediction=None
            program=None
    f=step["facts"]
    if step["status"] not in ("Victory","Defeat"):raise ValueError(step["status"])
    row.update(status=step["status"],terminal={k:f[k] for k in ("turn","hp","max_hp","gold","stars","energy","block","hand","discard","exhaust","belief","powers","enemies","potion_slots")})


def run(out,ids,arm,limit,specs=None,diagnostic=False,margin=0.):
    out.mkdir(exist_ok=False,parents=True)
    start=time.perf_counter();cpu=time.process_time()
    if specs is None:
        jobs=json.load(gzip.open(ROOT/"experiments/m1-core5d/evidence/panel.gz"))["train"]
        split="train"
    else:
        jobs=json.loads(specs.read_bytes())
        if not isinstance(jobs,list) or not jobs:raise ValueError("expected an array of {family,spec} records")
        ids=list(range(len(jobs)));split="custom"
    models=Models();identity=models.identity(arm,limit,margin)
    client=Client(out/"transport");counts=Counter()
    try:
        with gzip.open(out/"natural.jsonl.gz","xt",encoding="utf8",compresslevel=3) as stream:
            for i in ids:
                spec=jobs[i]["spec"]
                row=dict(i=i,split=split,family=jobs[i]["family"],seed=spec["seed"],encounter=spec["encounter"],
                         opening_hp=spec["hp"],opening_max_hp=spec["max_hp"],arm=arm,policy_version="h4-public-program-v1",policy_id=identity["id"],rule_budget=limit,margin=margin,incomplete_reference="direct-g2",
                         states=[],queries=[],trace=[],choices=[],actual_steps=0,terminal=None)
                before=time.perf_counter()
                try:fight(client,spec,models,arm,limit,row,require_match=not diagnostic,margin=margin)
                except (ValueError,RuntimeError,TimeoutError,KeyError,IndexError) as e:
                    row.update(status="failed",reason=str(e).split("; phase=")[0][:500])
                row["seconds"]=time.perf_counter()-before
                stream.write(json.dumps(row,separators=(",",":"),allow_nan=False)+"\n");stream.flush()
                counts[row["status"]]+=1
        native=client.call("metrics")
    finally:client.close()
    ledger=dict(policy=identity,attempts=len(ids),status=counts,wall=time.perf_counter()-start,python_cpu=time.process_time()-cpu,
        python_peak_rss=peak_rss(),model_work=models.work|dict(v2_cache_hits=models.evaluate.hits,v2_inferred=models.evaluate.misses),host=native,limit=limit,arm=arm,diagnostic=diagnostic,ids=ids)
    (out/"ledger.json").write_text(json.dumps(ledger,indent=2))
    print(json.dumps(ledger),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("output",type=Path);p.add_argument("--arm",choices=["turn","feedback","g2","tactical","contingent"],default="turn")
    source=p.add_mutually_exclusive_group()
    source.add_argument("--ids",type=int,nargs="+");source.add_argument("--specs",type=Path)
    p.add_argument("--limit",type=int,default=32)
    p.add_argument("--diagnostic",action="store_true",help="retain and continue trajectories after a recorded public return-law mismatch")
    p.add_argument("--margin",type=float,default=0.,help="minimum expected utility gain over the complete G2 reference")
    args=p.parse_args()
    run(args.output,args.ids if args.ids is not None else panel(),args.arm,args.limit,args.specs,args.diagnostic,args.margin)
