"""Execute automatically generated target portfolios on the archived B2 paired worlds."""
import sys,time
from branch import H,E,W,Actor,portfolio,s,return_law
sys.path.insert(0,str(H.parent/"m1-core6b1"))
import diagnose as old
from panel import gz,save

def main():
    t=time.perf_counter()
    source=H.parent/"m1-core6b1/evidence"
    root=gz(source/"prefixes.gz")["B2"]
    original=gz(source/"B2.gz")
    model=Actor("target");suffix=Actor("v2")
    client=s.SearchClient(W/"b2-replay",False)
    try:
        st,hist=old.w.recover(old.w.Recorder(client),model,dict(spec=root["spec"],prefix=root,turn=2),
                              dict(prefix=old.w.blank()))
        opening={k:root["spec"][k] for k in ("hp","max_hp")}
        h=old.public_b(st["facts"]);rank=model.rank(h,hist,opening)
        entries=portfolio(client,model,rank,opening,"tactical",32)
        ref=client.reference(rank[0],32,model,h,hist,opening)
        pairs=[("ref",ref,model.backup([ref],opening)[0])]
        pairs.extend((f"branch-{i}",g,q) for i,(g,q) in enumerate(entries) if q["style"]=="branch-target" and q["value"] is not None)
        plans={k:dict(policy=g["policy"],law=return_law(g),q=q) for k,g,q in pairs}
        for key,graph,q in pairs:
            plans[key]["single_backup"]=model.backup([graph],opening)[0]["value"]
            assert abs(plans[key]["single_backup"]-q["value"])<.002
        worlds=old.outcomes(client,suffix,root,st,hist,opening,plans,{k:"bound" for k in plans},
                            [x["seed"] for x in original["worlds"][1:]])
        assert all(z["status"] in ("Victory","Defeat") for row in worlds for z in row["sides"].values())
    finally:client.close()
    save(E/"b2-paired.gz",dict(plans=plans,worlds=worlds,seconds=time.perf_counter()-t))
if __name__=="__main__":main()
