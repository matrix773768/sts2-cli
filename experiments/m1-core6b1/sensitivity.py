"""Secondary continuation and draw-mechanism controls; separate from the primary eight worlds."""
from diagnose import *
def main():
    t=time.perf_counter();model=s.Actor("low");host=s.SearchClient(W/"sensitivity-host",False)
    refs=gz(E/"prefixes.gz"); records={}
    try:
        for key in ("B1","B2","B3"):
            r=refs[key];d=gz(E/(key+".gz"));spec=r["spec"]
            st,mem=w.recover(w.Recorder(host),model,dict(spec=spec,prefix=r,turn=d["turn"]),dict(prefix=w.blank()))
            op={k:spec[k] for k in ("hp","max_hp")}
            z=records[key]={}
            if key in ("B1","B2"):
                s.hot.portfolio=s.portfolio
                try:
                    z["low_suffix"]=outcomes(host,model,r,st,mem,op,d["graphs"],d["labels"],[x["seed"] for x in d["worlds"][1:]])
                finally:s.hot.portfolio=s.original_portfolio
            if key in ("B1","B3"):
                # Record one actual public witness per possible first draw, not a performance panel.
                st,mem=w.recover(w.Recorder(host),model,dict(spec=spec,prefix=r,turn=d["turn"]),dict(prefix=w.blank()))
                tag=key+"-adapt"; host.call("checkpoint");z["draw_witness"]={};tries=0
                counts=st["facts"]["belief"]["counts"]
                for i in range(96):
                    seed=int(digest(["6b1-draw",key,i])[:7],16);sample=host.call("restore",world=seed)
                    first=d["graphs"][tag]["first"];h=public_b(sample["facts"]);nxt=host.call("step",index=first)
                    c=nxt["facts"]["hand"][-1]; token=c["id"]+"#"+str(c["upgrade"]);assert token in counts
                    tries+=1
                    if token not in z["draw_witness"]:
                        original=host.call("restore",world=seed)
                        after,_,trace,k=run_turn(host,model,original,mem,op,d["graphs"][tag],"manual",tag)
                        z["draw_witness"][token]=dict(seed=seed,count=counts[token],trace=trace,boundary=k,
                                                     hp=after["facts"]["hp"],enemies=after["facts"]["known_enemies"])
                    if set(z["draw_witness"])==set(counts):break
                z["draw_attempts"]=tries
    finally:host.close()
    save(E/"sensitivity.gz",dict(records=records,seconds=time.perf_counter()-t))
if __name__=="__main__":main()
