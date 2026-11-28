"""Replay the frozen historical roots; compare portfolios on identical menus."""
import gzip,json,time
from branch import H,E,W,Actor,portfolio,policy_key,s,return_law
import sys
sys.path.insert(0,str(H.parent/"m1-core6b1"))
from panel import gz,read,save,digest
import diagnose as previous

def run(keys):
    tick=time.perf_counter()
    old=H.parent/"m1-core6b1/evidence"
    panel=read(old/"panel.json")["roots"];prefixes=gz(old/"prefixes.gz")
    models={mode:Actor(mode) for mode in ("v2","low","target","general","expand")}
    host=s.SearchClient(W/"regression",False);rows={}
    try:
        for r in panel:
            if keys and r["id"] not in keys:continue
            source=prefixes[r["id"]]; spec=source["spec"];opening={k:spec[k] for k in ("hp","max_hp")}
            st,hist=previous.w.recover(previous.w.Recorder(host),models["v2"],
                dict(spec=spec,prefix=source,turn=r["turn"]),dict(prefix=previous.w.blank()))
            menu=previous.public_b(st["facts"]);arms={}
            for mode,model in models.items():
                start=time.perf_counter();before=model.work.copy();metric=model.metrics.copy()
                rank=model.rank(menu,hist,opening)
                groups=portfolio(host,model,rank,opening,"tactical",32)
                ref=host.reference(rank[0],32,model,menu,hist,opening)
                groups=[(ref,model.backup([ref],opening)[0]|dict(style="ref")),*groups]
                options=[]
                for graph,q in groups:
                    law=return_law(graph)
                    assert abs(sum(law.values())+sum(q["gaps"].values())-1)<1e-7
                    options.append(dict(q=q,program=digest(policy_key(graph)),law_id=digest(law)))
                    if r["id"] in ("A","B1","B2","B3"):
                        options[-1].update(policy=graph["policy"],law=law)
                        if r["id"]=="B2":
                            options[-1]["successors"]=[dict(kind=l["kind"],mass=l["mass"],
                                alive=[(e["slot"],e["species"],e["hp"]) for e in l["facts"]["known_enemies"] if e["hp"]>0]
                                if l["kind"]=="C" else [],hp=l["facts"]["hp"] if l["kind"]=="C" else l["hp"]) for l in graph["leaves"]]
                best=0
                if not ref["gaps"]:
                    best=max((i for i,o in enumerate(options) if o["q"]["value"] is not None),key=lambda i:options[i]["q"]["value"])
                arms[mode]=dict(options=options,best=best,seconds=time.perf_counter()-start,
                    model_work={k:v-before[k] for k,v in model.work.items()},extra=dict(model.metrics-metric))
            rows[r["id"]]=dict(group=r["group"],arms=arms)
    finally:host.close()
    E.mkdir(exist_ok=True)
    save(E/("pilot.gz" if keys else "regression.gz"),dict(roots=rows,seconds=time.perf_counter()-tick))
if __name__=="__main__":run(sys.argv[1:])
