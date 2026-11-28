"""5E independent audit index 123, original 5D natural train index 87."""
import gzip
import json
from pathlib import Path
from native_h2 import HERE,ROOT,host_at,battle5d
from experience5d import restore
from check import delta

def run(probe=False):
    source=ROOT/"logs/infra0-world-inputs"
    case=json.load(gzip.open(source/"panel.gz"))["train"][123]
    record=next(r for p in (HERE.parent/"m1-core5d/evidence").glob("train-V2-?.gz")
                for r in map(json.loads,gzip.open(p)) if r["i"]==case["index"])
    out=ROOT/"logs/infra1h2/slug";out.mkdir(exist_ok=True)
    host=host_at(out,ROOT/"logs"/("infra1h2/5e-batch" if probe else "infra1h-5e-base2"));lane=battle5d.Lane(host,0)
    try:
        spec=case["spec"];st,history=restore(lane,spec,record["trace"],2)
        h=st["observation"];prior=st["observed_c"]
        assert prior==record["states"][0] and prior["turn"]==h["turn"]==2
        raw=dict(wire=h,prior=prior,law=st["public_law"],ascension=spec["ascension"])
        (out/"public.json").write_text(json.dumps(raw,indent=2))
        if probe:
            from slugs import SlugLane
            from lane import Unsupported
            b=SlugLane(lane,raw)
            results=[]
            def edge(route):
                r=b.request("i1_core5_reference",route=route,complete=True)["response"]
                old=lane.request("i1_core5_reference",route=route,complete=True)["response"]
                d=delta({k:v for k,v in r.items() if k!="calls"},{k:v for k,v in old.items() if k!="calls"})
                results.append(dict(route=route,kind=r["kind"],equal=not d,delta=d[:5]))
                return r
            for a in h["actions"]:
                e=dict(action=a["index"],draws=[])
                try:
                    r=edge([e])
                    if r["kind"]=="R":
                        for k in r["support"]:
                            fork=[dict(action=a["index"],draws=[k])]
                            child=edge(fork)
                            if child["kind"]=="decision":edge(fork+[dict(action=len(child["state"]["actions"])-1,draws=[])])
                except Unsupported as exc:results.append(dict(route=[e],stop=str(exc)))
            from search5 import Evaluator,reference
            from turn_worlds import model_key
            from semantic import encode
            import numpy as np
            from complete import PublicLane
            baseline=ROOT/"logs/infra0-runs/infra1h-A-audit-h-batch/worker-0"
            meta=json.loads((baseline/"worker.json").read_bytes())
            locked=next(r for r in map(json.loads,gzip.open(baseline/"evidence"/meta["closed"]["file"])) if r["i"]==123)
            same=[w["outcomes"][1]["steps"] for w in locked["worlds"]]
            assert all(route==same[0] for route in same)
            model,g2,net,_=battle5d.configure(out,"V2");model.close()
            evaluator=Evaluator(net)
            programs=[]
            for plan in locked["plans"]:
                receipt={"label":plan["label"]};programs.append(receipt)
                try:
                    leaves=[]
                    if plan["label"]=="graph/3":
                        support=b.request("i1_core5_reference",route=[dict(action=3,draws=[])],complete=True)["response"]["support"]
                        for token,n in support.items():
                            route=[dict(action=3,draws=[token])]
                            child=b.request("i1_core5_reference",route=route,complete=True)["response"]
                            route.append(dict(action=len(child["state"]["actions"])-1,draws=[]))
                            leaves.append((n/sum(support.values()),b.request("i1_core5_reference",route=route,complete=True)["response"]))
                    elif plan["label"]=="graph/1":
                        route=[dict(action=i,draws=[]) for i in same[0]]
                        leaves.append((1.,b.request("i1_core5_reference",route=route,complete=True)["response"]))
                    else:raise ValueError("Changed selected program")
                    states={model_key(r["state"]):r["state"] for prob,r in leaves if r["kind"]=="C"}
                    values=Evaluator(net)(states,spec)
                    old_states={k:locked["states"][k] for k in states if k in locked["states"]}
                    old_values=Evaluator(net)(old_states,spec)
                    tensors=states.keys()==old_states.keys() and all(all(np.array_equal(x,y)
                        for x,y in zip(encode(state),encode(old_states[k]))) for k,state in states.items())
                    law=sorted((r["kind"],model_key(r["state"]),weight) for weight,r in leaves)
                    expected=sorted((kind,k,prob) for kind,k,_,prob in plan["law"])
                    matching=[]
                    for _,key,weight in law:
                        state=states[key]
                        if key in locked["states"]:nearest=key
                        else:nearest=min((k for _,k,_ in expected),key=lambda k:len(delta(state,locked["states"][k])))
                        matching.append(dict(candidate=key,archived=nearest,weight=weight,delta=delta(state,locked["states"][nearest])[:10]))
                    receipt["leaf_differences"]=matching
                    receipt.update(law_equal=law==expected,public_C_equal=all(locked["states"].get(k)==c for k,c in states.items()),
                        same_batch_v2_equal=values==old_values,tensor_equal=tensors,leaves=len(leaves),utility=sum(weight*values[k] for _,k,weight in law),frozen_utility=plan["v2"],
                        probability=sum(v for _,_,v in law))
                except Unsupported as error:receipt["stop"]=str(error)
            g2_receipt={}
            try:
                b.close();b=SlugLane(lane,raw);lane.request("i1_core5_reference",clear=True)
                def semantic(run):
                    leaves,calls,first=run
                    return [first,calls,[{k:v for k,v in leaf.items() if k!="calls"} for leaf in leaves]]
                hot=semantic(reference(PublicLane(b),host.project(h),history,g2,limit=256))
                old=semantic(reference(PublicLane(lane),host.project(h),history,g2,limit=256))
                g2_receipt=dict(equal=hot==old,calls=hot[1],leaves=len(hot[2]))
            except Unsupported as error:g2_receipt["stop"]=str(error)
            b.close()
            (HERE/"evidence/slug123.json").write_text(json.dumps(dict(source_index=case["index"],wire=h,law=raw["law"],
                prior=prior,edges=results,programs=programs,reference=g2_receipt),indent=2))
    finally:lane.close();host.close()
if __name__=="__main__":
    import sys
    run("--probe" in sys.argv)
