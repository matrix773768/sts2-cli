"""On the same published development menus, separate style pruning, action ranking and width."""
import time
from collections import Counter
from common6 import *
from policy6 import Guide
import numpy as np

def main():
    start=time.perf_counter()
    actor=Models()
    net=Guide(E/(read(E/"picked.json")["name"]+".pt"))
    held=set(read(A/"splits.json")["core5f"]["dev"])
    out={}; per_family={}
    n=0
    for base in (H5/"data",H5/"capacity",A/"dev"):
        for s in read(base/"manifest.json")["shards"]:
            if s["kind"]!="natural" or s["split"] not in ("train","dev"):continue
            for r,p in zip(read_rows(base/s["file"]),read_rows(base/"public"/(s["shard"]+".gz")),strict=True):
                if not r["eligible"] or (base!=A/"dev" and r["family"] not in held):continue
                n+=1; assert r["task_id"]==p["task_id"]
                memory=actor.g2.encoder.initial_history()
                queries={q["turn"]:q for q in r["trajectory"]["queries"]}
                for step in p["segments"][0]["steps"]:
                    obs=step["observation"]; f=obs["facts"]
                    h=choice_b(f,obs) if obs["status"]=="choice" else public_b(f)
                    i=step["index"]
                    if obs["status"]=="active" and len(h["actions"])>1 and f["turn"] in queries:
                        q=queries.pop(f["turn"]); ref=q["reference_law"]["value"]
                        assert q["selected"]==i
                        if ref is not None:
                            order=actor.rank(h,memory,r["spec"])
                            assert order[0]==q["reference"]
                            scores=net.scores(h,memory,r["spec"])
                            proposed=np.argsort(-scores,kind="stable").tolist()
                            end=next(a["index"] for a in h["actions"] if a["kind"]=="end_turn")
                            opp=any((a.get("preview") or {}).get("draw") or a.get("energy_x") for a in h["actions"])
                            fixed=2+int(bool(opp)); relaxed=2+int(bool(opp or scores[proposed[0]]-scores[proposed[1]]<.55))
                            best=max([ref]+[o["value"] for o in q["options"] if o["value"] is not None])
                            for name,ids in (("all_styles",order),("two_styles",order),("g2_fixed",order[:fixed]),("learned_fixed",proposed[:fixed]),("learned_adaptive",proposed[:relaxed])):
                                keep=set(ids)|{order[0],end}
                                opts=[o for o in q["options"] if o["index"] in keep and (name=="all_styles" or o["style"] in ("light","guard"))]
                                top=max([ref]+[o["value"] for o in opts if o["value"] is not None])
                                a=out.setdefault(name,Counter())
                                measures=dict(queries=1,options=len(opts),legal=len(order),kept=len(keep),recovered=int(best-top<1e-5),improves=int(top>ref),
                                              improvement=top-ref,missed=best-top)
                                a.update(measures)
                                per_family.setdefault(r["family"],{}).setdefault(name,Counter()).update(measures)
                    memory=actor.advance(memory,h,h["actions"][i])
                assert not queries
    assert n==275 and out["all_styles"]["queries"]==1000
    save(E/"shared-menu.json",dict(families=n,summary=out,by_family=per_family,seconds=time.perf_counter()-start))
if __name__=="__main__":main()
