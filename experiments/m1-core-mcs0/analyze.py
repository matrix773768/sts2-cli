"""Compute per-root costs, closure and comparable value differences from archived evidence."""
from collections import Counter
from statistics import median, mean
from time import perf_counter
from freeze import E,H,read,gz,save
from certificate import certificate

def stats(v):
    return dict(n=len(v),min=min(v),median=median(v),mean=mean(v),max=max(v),positive=sum(x>1e-4 for x in v)) if v else dict(n=0)

def main():
    start=perf_counter()
    panel=read(E/"panel.json")
    review=read(E/"review.json")["roots"]
    rows={}
    for info in panel:
        id_=info["id"]
        r=gz(E/"panel"/(id_+".gz"))
        if "error" in r:
            rows[id_]=dict(error=r["error"])
            continue
        c=r["curve"][-1]
        certified=certificate(r)
        value=certified.pop("feasible")
        certified.pop("policy")
        exact=c["exact"]
        if value is not None:
            assert abs(review[id_]["q"]["value"]-value)<1e-4
        if exact is not None:assert "recheck" in review[id_]
        arms={}
        for mode,a in r["arms"].items():
            options=[o["q"]["value"] for o in a["options"]]
            closed=[v for v in options if v is not None]
            arms[mode]=dict(adopted=options[a["best"]],candidate=max(closed,default=None),
                            open_reference=options[0] is None,closed=len(closed),offered=len(options))
        refs=[v for v in [value,*[a["candidate"] for a in arms.values()]] if v is not None]
        ref=exact if exact is not None else max(refs,default=None)
        for a in arms.values():
            for kind in ("candidate","adopted"):
                diff=None if a[kind] is None else ref-a[kind]
                assert diff is None or diff>=-1e-4,(id_,a,ref)
                a[kind+"_gap"]=None if diff is None else max(0,diff)
        gaps=Counter(k for p in r["probes"] for k in p["gaps"])
        stops=[]
        if exact is None:
            if c["probes"]>=c["budget"]:stops.append("logical_budget")
            if r["time_cap"]:stops.append("wall")
            if "budget" in gaps:stops.append("per_program_step_cap")
            if "depth" in gaps:stops.append("depth")
            if any("unmodeled_rng" in k for k in gaps):stops.append("unmodeled_rng")
            if set(gaps)-{"budget","depth"}-{k for k in gaps if "unmodeled_rng" in k}:stops.append("other_mechanism")
            assert stops
        rows[id_]=dict(exact=exact,reference=ref,search_value=value,arms=arms,compression=certified,
                       flags=info["flags"],group=info["group"],root_legal=info["legal"],summary=c,stops=stops,
                       gap_queries=gaps,C=sum(v["kind"]=="C" for v in r["leaves"].values()),
                       terminal=sum(v["kind"]!="C" for v in r["leaves"].values()),prefix=r["replayed"],
                       peak=r["host"]["peak_rss"],model=r["work"],curve=r["curve"])
    ok=[r for r in rows.values() if "error" not in r]
    regrets={}
    for tag in ("exact","pooled"):
        for mode in ("v2","low","general"):
            for kind in ("candidate","adopted"):
                vals=[r["arms"][mode][kind+"_gap"] for r in ok if (r["exact"] is not None)==(tag=="exact")]
                regrets[tag,mode,kind]=stats([x for x in vals if x is not None])
    groups={}
    for key in ("all","draw","multi_enemy","energy","X","cost_layer","none"):
        rs=[r for r in ok if key=="all" or key in r["flags"] or key=="none" and not r["flags"]]
        groups[key]=dict(roots=len(rs),exact=sum(r["exact"] is not None for r in rs),
                         **{k:stats([r["summary"][k] for r in rs]) for k in ("histories","legal","steps","seconds")},
                         menu=stats([r["root_legal"] for r in rs]))
    save("results.json",dict(rows=rows,groups=groups,regrets={"/".join(k):v for k,v in regrets.items()},
         solved=[sum(r["curve"][i]["exact"] is not None for r in ok) for i in range(3)],
         stops=Counter(x for r in ok for x in r["stops"]),analysis_seconds=perf_counter()-start))

if __name__=="__main__":main()
