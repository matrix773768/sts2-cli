"""Cost of using a previously certified quotient on the SAME completed finite tree."""
import time
from freeze import E,CORE,gz,read,save,sources,digest
from survey import Tree,Actor,s,recover

def identifiers(row):
    edges={(n,i):law for n,i,law in row["edges"]}
    signatures={}
    laws={}
    for n in reversed(range(len(row["labels"]))):
        _,obs,size=row["labels"][str(n)]
        parts=[]
        for i in range(size):
            atoms=sorted((signatures[k] if isinstance(k,int) else k,p) for k,p in edges[n,i])
            laws[n,i]=digest(atoms)
            parts.append(laws[n,i])
        signatures[n]=digest([obs,parts])
    return edges,signatures,laws

def run(row,host,model,st,opening,level):
    start=time.perf_counter()
    edges,classes,laws=identifiers(row)
    def key(a):
        n,i=a
        return a if level==0 else (classes[n],i if level==1 else laws[a])
    tree=Tree(st)
    for it,(p,obs,size) in row["labels"].items():
        assert tree.menu(tuple(p) if p else "",obs,size)==int(it)
    seen=set()
    # Fixed history/action order for all arms. A closed suffix can cover multiple edges.
    for a in sorted(edges):
        if key(a) in seen:continue
        tree.probe(host,model,opening,a,128)
        assert a in tree.edges
        for b,t in tree.edges.items():
            assert dict(edges[b]).keys()==t.keys() and all(abs(dict(edges[b])[k]-p)<1e-7 for k,p in t.items())
            seen.add(key(b))
        tree.edges.clear()
    return dict(seconds=time.perf_counter()-start,probes=len(tree.probes),steps=tree.count["steps"],classes=len(seen))

def main():
    start=time.perf_counter()
    m=Actor("v2")
    roots=sources()
    rows={}
    host=s.SearchClient(CORE/"logs/core-mcs0/quotient",False)
    try:
        for j,(id_,r) in enumerate(read(E/"results.json")["rows"].items()):
            if r.get("exact") is None:continue
            row=gz(E/"panel"/(id_+".gz"))
            root=roots[id_]
            st,_=recover(host,m,root)
            opening={k:root["spec"][k] for k in ("hp","max_hp")}
            rows[id_]={}
            for off in range(3):
                level=(j+off)%3
                rows[id_][level]=run(row,host,m,st,opening,level)
    finally:
        host.close()
        save("compression.json",dict(seconds=time.perf_counter()-start,roots=rows))

if __name__=="__main__":main()
