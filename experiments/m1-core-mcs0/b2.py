"""Diagnostic scheduling sensitivity, separate from the preregistered budget curve."""
from collections import deque
import time
from freeze import E,CORE,sources,save
from survey import Actor,s,Tree,recover

def main():
    tick=time.perf_counter()
    m=Actor("v2")
    root=sources()["B2"]
    h=s.SearchClient(CORE/"logs/core-mcs0/b2",False)
    try:
        st,_=recover(h,m,root)
        opening={k:root["spec"][k] for k in ("hp","max_hp")}
        tree=Tree(st)
        q=deque((0,i) for i in range(tree.labels[0][2]))
        queued=set(q)
        while q and len(tree.probes)<2048 and time.perf_counter()-tick<65:
            a=q.popleft()
            if a not in tree.edges:
                tree.probe(h,m,opening,a,128)
            law=tree.edges.get(a,{})
            if len(law)!=1:continue
            child=next(iter(law))
            if not isinstance(child,int):continue
            for i in range(tree.labels[child][2]):
                b=(child,i)
                if b not in queued:
                    queued.add(b)
                    q.append(b)
        save("b2.json",dict(summary=tree.summary(),witness=tree.witness,probes=tree.probes,
                            seconds=time.perf_counter()-tick,queued_remaining=len(q)))
    finally:h.close()
if __name__=="__main__":main()
