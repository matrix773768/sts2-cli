"""B3 exploratory gate control. Pick the top closed H5 law before sampling eight fresh worlds."""
from diagnose import *

def main():
    tick=time.perf_counter()
    root=gz(E/"prefixes.gz")["B3"]
    data=gz(E/"B3.gz")
    m=s.Actor("v2")
    host=s.SearchClient(W/"gate-host",False)
    try:
        st,hist=w.recover(w.Recorder(host),m,dict(spec=root["spec"],prefix=root,turn=3),dict(prefix=w.blank()))
        graphs=data["graphs"]
        closed=[k for k in data["candidates"]["h5"] if graphs[k]["q"]["value"] is not None]
        best=max(closed,key=lambda k:graphs[k]["q"]["value"])
        ref=data["selected"]["low"]
        opening={k:root["spec"][k] for k in ("hp","max_hp")}
        seeds=[int(digest(["6b1-B3-gate",i])[:7],16) for i in range(8)]
        assert not set(seeds)&{x["seed"] for x in data["worlds"]}
        rows=outcomes(host,m,root,st,hist,opening,graphs,{ref:"g2",best:"bound"},seeds)
    finally:host.close()
    save(E/"gate.gz",dict(candidate=best,worlds=rows,seconds=time.perf_counter()-tick))

if __name__=="__main__":main()
