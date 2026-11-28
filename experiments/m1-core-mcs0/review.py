"""Replay conditional plans on the frozen host. Re-query exact certificates with native stamps."""
import time
from collections import Counter
from freeze import sources, gz, E, CORE, read, save, digest
from survey import s, Actor, Tree, recover
from certificate import certificate

def replay(host,st,opening,m,row,sol):
    tick=time.perf_counter()
    labels=row["labels"]
    bykey={(tuple(p),v):int(n) for n,(p,v,_) in labels.items() if p}
    policy=sol["policy"]
    first=policy[0]
    memory={0:(0,first)}
    response=host.engine.send(dict(op="search",indices=[first],limit=4096,g2=True))
    while response["type"]=="g2":
        f,p=response["facts"],response["prompt"]
        parent=memory[response["parent"]]
        n=bykey[parent,digest([f,p])]
        i=policy[n]
        memory[response["ticket"]]=(n,i)
        response=host.engine.send(dict(op="g2",ticket=response["ticket"],index=i))
    assert response["ok"]
    graph=response["result"][0]
    q=m.backup([graph],opening)[0]
    assert q["value"] is not None and abs(q["value"]-sol["feasible"])<1e-4
    return dict(q=q,program=graph["policy"],seconds=time.perf_counter()-tick,
                outcomes=[dict(mass=x["mass"],kind=x["kind"],enemies=[(e["slot"],e["hp"]) for e in x["facts"]["known_enemies"]]
                             if x["kind"]=="C" else []) for x in graph["leaves"]])

def main():
    start=time.perf_counter()
    m=Actor("v2")
    host=s.SearchClient(CORE/"logs/core-mcs0/review",False)
    roots=sources()
    rows={}
    try:
        for info in read(E/"panel.json"):
            id_=info["id"]
            row=gz(E/"panel"/(id_+".gz"))
            if "error" in row:continue
            sol=certificate(row)
            if sol["feasible"] is None:continue
            root=roots[id_]
            st,_=recover(host,m,root)
            opening={k:root["spec"][k] for k in ("hp","max_hp")}
            rows[id_]=replay(host,st,opening,m,row,sol)
            if row["curve"][-1]["exact"] is None:continue
            tree=Tree(st)
            native={}
            hits,misses=m.evaluate.hits,m.evaluate.misses
            for probe in row["probes"]:
                tree.probe(host,m,opening,tuple(probe["target"]),128,native)
            assert tree.edges.keys()=={(n,i) for n,i,_ in row["edges"]}
            assert len(native)==len(tree.labels)
            assert abs(tree.summary()["exact"]-sol["feasible"])<1e-4
            rows[id_]["recheck"]=dict(native_menus=len(native),steps=tree.count["steps"],
                                       inference_rows=m.evaluate.misses-misses,cached_rows=m.evaluate.hits-hits)
    finally:
        host.close()
        save("review.json",dict(seconds=time.perf_counter()-start,roots=rows))

if __name__=="__main__":main()
