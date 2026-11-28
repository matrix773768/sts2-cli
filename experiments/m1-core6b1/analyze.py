"""Join frozen decisions, complete-law estimates, input audits and actual paired outcomes."""
import gzip
import json
import math
import statistics
import time
from collections import Counter, defaultdict
from panel import CORE, E, H, S, gz, read, save, sha

def paired(worlds, a, b):
    rows = []
    for row in worlds:
        left, right = [row["sides"][key] for key in (a,b)]
        if "utility" in left and "utility" in right:
            rows.append(dict(seed=row["seed"],delta=right["utility"]-left["utility"],
                             wins=[left["status"]=="Victory",right["status"]=="Victory"]))
    ds = [x["delta"] for x in rows]
    pos, neg = sum(d>0 for d in ds), sum(d<0 for d in ds)
    n = pos+neg
    p = min(1.,2*sum(math.comb(n,i) for i in range(min(pos,neg)+1))/2**n)
    return dict(base=a,other=b,attempts=len(worlds),pairs=len(ds),delta=ds,
                mean=statistics.mean(ds) if ds else None, wins=[sum(r["wins"][i] for r in rows) for i in (0,1)],
                signs=[pos,neg],p=p)

def check_archive(q,d):
    chosen=d["graphs"][d["selected"]["low"]]
    assert q["reference"]==d["g2"][0] and q["selected"]==chosen["first"]
    equivalent_tie=q["committed"]!=(d["selected"]["low"]!="low/ref")
    if equivalent_tie:
        assert chosen["policy"]==q["policy"] and chosen["law"]==q["law"]
        assert abs(chosen["q"]["value"]-q["reference_law"]["value"])<.002
    gap_aliases=[]
    def compare(old,new):
        assert old.keys()==new.keys()
        for k,v in old.items():
            if k=="value" and v is not None:assert abs(v-new[k])<.002
            elif k=="gaps" and v!=new[k]:
                # Preserve both engine diagnostics; check budget and each unresolved mass separately.
                assert sorted(v.values())==sorted(new[k].values()) and v.get("budget")==new[k].get("budget")
                gap_aliases.append(dict(archived=v,replayed=new[k]))
            else:assert v==new[k],k
    compare(q["reference_law"],d["graphs"]["low/ref"]["q"])
    for old,key in zip(q["options"],d["candidates"]["low"],strict=True):
        compare(old,d["graphs"][key]["q"])
    if q.get("policy") is not None:
        assert q["policy"]==chosen["policy"] and q["law"]==chosen["law"]
    return dict(committed=q["committed"],binding=q.get("matched"),observed=q.get("observed"),
                original_style=q.get("winner_style","ref"),equivalent_tie=equivalent_tie,gap_aliases=gap_aliases)

def main():
    tick=time.perf_counter()
    panel=read(E/"panel.json")
    assert panel["protocol"]==sha(H/"protocol.md") and panel["prefixes"]==sha(E/"prefixes.gz")
    rep=gz(E/"representation.gz")["roots"]; archives={}
    for shard in range(4):
        name=f"confirm-low-{shard}"
        folder=CORE/"logs/core6a"/read(S/(name+".json")).get("directory",name)/"engine"
        archives[shard]=[json.loads(line) for line in gzip.open(folder/"natural.jsonl.gz","rt")]
    results={};total=defaultdict(Counter)
    for r in panel["roots"]:
        k=r["id"];d=gz(E/(k+".gz"));gs=d["graphs"];low=d["selected"]["low"]
        archive=archives[r["shard"]][r["battle"]]
        assert archive["family"]==r["family"] and archive["seed"]==r["seed"]
        q=next(q for q in archive["queries"] if q["turn"]==r["turn"])
        compare=check_archive(q,d)
        tags={};rep_gaps=[]
        for field,edit in rep[k]["edits"].items():
            if field=="layers" and not any(any(c["layers"].values()) for c in rep[k]["cards"]):
                continue
            if edit["raw_changed"] and not (edit["g2"] or edit["guide"]):
                rep_gaps.append(field)
        if rep_gaps:tags["REPRESENTATION_GAP"]="Both action encoders invariant to public inputs: "+", ".join(rep_gaps)
        menu={};refopen=gs["low/ref"]["q"]["value"] is None
        count=Counter(roots=1,open_ref=int(refopen))
        if refopen:tags["REFERENCE_GATE"]="Open G2 reference stops low proposals and prevents H5 acceptance."
        for arm,keys in d["candidates"].items():
            closed=sum(gs[c]["q"]["value"] is not None for c in keys)
            first=sorted({gs[c]["first"] for c in keys}); menu[arm]=dict(total=len(keys),closed=closed,first=first)
            count.update({arm+"_programs":len(keys),arm+"_closed":closed,arm+"_first":len(first)})
        count.update(legal=len(d["menu"]),blocked_closed_h5=menu["h5"]["closed"]*int(refopen))
        if any(g["q"]["gaps"] for g in gs.values()):tags["SEARCH_INCOMPLETE"]="At least one graph has explicitly unresolved probability."
        worlds=d.get("worlds",[]); comparisons=[]
        keys=list(d["labels"]); other=keys[1:]
        def contrast(a,b):
            res=paired(worlds[1:],a,b);res["original"]=paired(worlds[:1],a,b)
            va,vb=(gs[tag]["q"]["value"] for tag in (a,b))
            if va is not None and vb is not None:
                res["predicted_delta"]=vb-va
                if res["pairs"] and sum(res["signs"])>=6 and res["p"]<=.05 and res["mean"]*(vb-va)<0:
                    tags["VALUE_MISRANK"]=a+" / "+b
            return res
        if worlds:
            comparisons=[contrast(low,b) for b in other]
            if len(other)==2:comparisons.append(contrast(other[-1],other[0]))
            count.update(paired_roots=1,world_attempts=len(worlds)-1,paired_worlds=comparisons[0]["pairs"])
            if not comparisons[0]["pairs"]:
                tags["INCONCLUSIVE"]="No commonly completed reordered pairs."
            elif not any(x["pairs"] and x["p"]<=.05 and x["mean"]>0 for x in comparisons):
                tags["NO_CONFIRMED_GAIN"]="No reliable positive difference on primary reordered worlds."
        else:tags["INCONCLUSIVE"]="No paired suffix allocation."
        # A different closed law means a different terminal/resource distribution; compare complete laws only.
        alternatives=[]
        for b in other:
            g=gs[b];idx=g["first"];eligible=d["candidates"]["low"]+[low]
            same_first=any(gs[key]["first"]==idx for key in eligible)
            same_law=g["q"]["value"] is not None and any(gs[key]["q"]["value"] is not None and gs[key]["law"]==g["law"] for key in eligible)
            same_tree=any(gs[key]["policy"]==g["policy"] for key in eligible)
            alternatives.append(dict(key=b,covered_first=same_first,covered_law=same_law,covered_program=same_tree))
            # Attribute pruning only when the reference permits proposals.
            if not refopen and not same_law and not same_tree:
                if not same_first:tags["FIRST_ACTION_MISS"]="Probed alternative first action absent from low portfolio."
                else:tags["CONTINUATION_MISS"]="Alternative continuation absent from low portfolio."
        if k=="B2":
            tags["TARGET_ALLOCATION_MISS"]="With first/third actions fixed, the right-Slam closed law is absent and wins all eight target-only pairs."
        if k=="A":
            tags["CONTINUATION_MISS"]="All four H5 programs with PRIMAL_FORCE differ from the explicit left/right Rock program."
            tags["INCONCLUSIVE"]="Empty exchangeable tail; only original executable; both full laws unresolved."
        if any(x.get("reason") and "nonexchangeable_tail" not in x["reason"] for row in worlds for x in row["sides"].values()):
            tags["EXECUTION_GAP"]="See per-side execution or restoration exception."
        count.update({"tag_"+tag:1 for tag in tags})
        for field in rep_gaps:count["missing_actor_"+field]+=1
        total[r["group"]].update(count)
        results[k]=dict(archive=compare,reference_open=refopen,menus=menu,alternatives=alternatives,
                        comparisons=comparisons,labels=tags,direct=d["guide_rank"][0])
    sens=gz(E/"sensitivity.gz")
    extra={}
    for k,z in sens["records"].items():
        if "low_suffix" in z:
            rows=z["low_suffix"];base,*other=rows[0]["sides"]
            extra[k]=[paired(rows[1:],base,b) for b in other]
    gate=gz(E/"gate.gz")
    extra["B3_fresh_gate"]=paired(gate["worlds"][1:],"low/ref",gate["candidate"])
    assert len(results)==40 and len({r["family"] for r in panel["roots"]})==38
    save(E/"results.json",dict(roots=results,groups=total,supplemental=extra,seconds=time.perf_counter()-tick))

if __name__=="__main__":main()
