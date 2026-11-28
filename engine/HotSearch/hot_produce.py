"""Produce isolated, labelled Hot-only trajectories from the frozen natural panel."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import time
import ctypes
from ctypes import wintypes


def peak_rss():
    class Counters(ctypes.Structure):
        _fields_=[("cb",wintypes.DWORD),("faults",wintypes.DWORD)]+[(k,ctypes.c_size_t) for k in ("peak","rss","p1","p2","p3","p4","p5","p6")]
    record=Counters()
    record.cb=ctypes.sizeof(record)
    if not ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(-1),ctypes.byref(record),record.cb):
        raise ctypes.WinError()
    return record.peak
from client import BUILD, ROOT, Client
from models import Models, public_b, strategic, choice_b, boundary_key, return_law


def panel():
    source=json.loads((ROOT/"experiments/m1-infra0/panel.json").read_bytes())["natural"]
    return list(dict.fromkeys(i for group in source.values() for i in group))


def fight(client,spec,models,arm,limit,row,*,resume=None,until=None,first=None,then_end=False,require_match=False,intervention_law=None):
    if resume is None:
        step=client.call("open",spec=spec)
        history=models.g2.encoder.initial_history()
    else:
        step,history=resume
    locked=None
    queried=None
    prediction=None
    if intervention_law is not None:
        prediction={"law":intervention_law}
        row["intervention"]=prediction
    opening={k:spec[k] for k in ("hp","max_hp")}
    while step["status"]=="active":
        f=step["facts"];h=public_b(f)
        if until is not None and f["turn"]>=until:return step,history
        rank=models.rank(h,history,opening)
        selected=rank[0]
        if first is not None:
            selected=first;first=None;locked=f["turn"]
        elif locked==f["turn"]:
            selected=len(h["actions"])-1 if then_end else client.call("continue")
        elif arm in ("turn","feedback") and queried!=f["turn"] and len(rank)>1:
            then_end=False
            queried=f["turn"]
            ids=list(dict.fromkeys([*rank[:2],len(rank)-1]))
            if arm=="feedback":
                results=[client.reference(i,limit,models,h,history,opening) for i in ids if i!=rank[0]]
            else:
                results=client.call("search",indices=ids,limit=limit)
            options=models.backup(results,opening)
            ref_graph=client.reference(rank[0],limit,models,h,history,opening)
            reference=models.backup([ref_graph],opening)[0]
            row["queries"].append(dict(turn=f["turn"],reference=rank[0],options=options,reference_law=reference))
            if reference["value"] is not None:
                complete=[o for o in options if o["value"] is not None and o["value"]>reference["value"]]
                graph=ref_graph
                if complete:
                    selected=max(complete,key=lambda o:o["value"])["index"]
                    if arm=="turn":locked=f["turn"]
                    graph=next(r for r in results if r["index"]==selected)
                prediction=row["queries"][-1]
                prediction["law"]=return_law(graph)
            row["queries"][-1].update(selected=selected,committed=locked==f["turn"] or selected!=rank[0])
        row["trace"].append([f["turn"],selected,h["actions"][selected]["kind"],h["actions"][selected].get("card"),h["actions"][selected]["target"],h["actions"][selected]["target_side"]])
        row.setdefault("boundaries",[]).append(dict(turn=f["turn"],hp=f["hp"],max_hp=f["max_hp"],block=f["block"],
            energy=f["energy"],hand=[(c["id"],c["upgrade"]) for c in f["hand"]],foes=[(e["species"],e["hp"],e["block"]) for e in f["enemies"]]))
        history=models.g2.encoder.update(history,h,h["actions"][selected])
        row["actual_steps"]+=1
        step=client.call("step",index=selected)
        while step["status"]=="choice":
            ch=choice_b(step["facts"],step)
            pick=0 if locked==f["turn"] else models.rank(ch,history,opening)[0]
            history=models.g2.encoder.update(history,ch,ch["actions"][pick])
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
    f=step["facts"]
    if step["status"] not in ("Victory","Defeat"):raise ValueError(step["status"])
    row.update(status=step["status"],terminal={k:f[k] for k in ("turn","hp","max_hp","gold","stars","energy","block","hand","discard","exhaust","belief","powers","enemies","potion_slots")})


def run(out,ids,arm,limit,specs=None,diagnostic=False):
    out.mkdir(exist_ok=False,parents=True)
    start=time.perf_counter();cpu=time.process_time()
    if specs is None:
        jobs=json.load(gzip.open(ROOT/"experiments/m1-core5d/evidence/panel.gz"))["train"]
        split="train"
    else:
        jobs=json.loads(specs.read_bytes())
        if not isinstance(jobs,list) or not jobs:raise ValueError("expected an array of {family,spec} records")
        ids=list(range(len(jobs)));split="custom"
    models=Models()
    client=Client(out/"transport");counts=Counter()
    try:
        with gzip.open(out/"natural.jsonl.gz","xt",encoding="utf8",compresslevel=3) as stream:
            for i in ids:
                spec=jobs[i]["spec"]
                row=dict(i=i,split=split,family=jobs[i]["family"],seed=spec["seed"],encounter=spec["encounter"],
                         opening_hp=spec["hp"],opening_max_hp=spec["max_hp"],arm=arm,
                         states=[],queries=[],trace=[],choices=[],actual_steps=0,terminal=None)
                before=time.perf_counter()
                try:fight(client,spec,models,arm,limit,row,require_match=not diagnostic)
                except (ValueError,RuntimeError,TimeoutError,KeyError,IndexError) as e:
                    row.update(status="failed",reason=str(e).split("; phase=")[0][:500])
                row["seconds"]=time.perf_counter()-before
                stream.write(json.dumps(row,separators=(",",":"),allow_nan=False)+"\n");stream.flush()
                counts[row["status"]]+=1
        native=client.call("metrics")
    finally:client.close()
    ledger=dict(attempts=len(ids),status=counts,wall=time.perf_counter()-start,python_cpu=time.process_time()-cpu,
        python_peak_rss=peak_rss(),host=native,limit=limit,arm=arm,diagnostic=diagnostic,ids=ids)
    (out/"ledger.json").write_text(json.dumps(ledger,indent=2))
    print(json.dumps(ledger),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("output",type=Path);p.add_argument("--arm",choices=["turn","feedback","g2"],default="turn")
    source=p.add_mutually_exclusive_group()
    source.add_argument("--ids",type=int,nargs="+");source.add_argument("--specs",type=Path)
    p.add_argument("--limit",type=int,default=32)
    p.add_argument("--diagnostic",action="store_true",help="retain and continue trajectories after a recorded public return-law mismatch")
    args=p.parse_args()
    run(args.output,args.ids if args.ids is not None else panel(),args.arm,args.limit,args.specs,args.diagnostic)
