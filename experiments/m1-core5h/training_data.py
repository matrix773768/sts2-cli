"""Reuse the 5G frozen conversion in a fresh CORE-5H output directory."""
import sys,gzip,pickle,hashlib
from collections import Counter
from pathlib import Path
from paths5h import *
sys.path.insert(0,str(G))
from settings import torch,Data,base_net,logits,differences,utility,digest,sha,terminal_target
from nets5h import network
from statistics import mean

def prepare():
    import importlib.util
    spec=importlib.util.spec_from_file_location("prepare5g",G/"prepare.py")
    source=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(source)
    source.WORK=source.OUT=W
    source.main()
    new,old=read(W/"data.json"),read(G/"evidence/data.json")
    assert {k:v for k,v in new.items() if k!="seconds"}=={k:v for k,v in old.items() if k!="seconds"}
    save(E/"source.json",dict(release=new["release"],counts=new["train"],seconds=new["seconds"],cache_sha256=sha(W/"corpus.pkl")))

def active_data():
    streams={"train":Data(),"dev":Data()}
    reports=[]
    for path in sorted(E.glob("root-*.gz")):
        r=json.load(gzip.open(path))
        if not r["eligible"]:continue
        d=streams[r["split"]]
        hp,mx=r["spec"]["hp"],r["spec"]["max_hp"]
        st=r["states"]
        keys={}
        for k,c in st.items():
            assert k==digest([c,list(c["belief"]["counts"])])
            d.add(k,c)
            g,x=d.states[k][0]
            keys[k]=hashlib.sha256(g.tobytes()+x.tobytes()).hexdigest()
        laws=[]
        for identity,plan in zip(r["ids"],r["plans"],strict=True):
            menu=next(p for p in r["menu"] if [p["first"],p["style"]]==identity)
            assert menu["program"]==digest([plan["first"],plan["policy"]]) and abs(menu["v2"]-plan["value"])<.002
            law=[]
            masses=Counter()
            for k,p in plan["public_law"].items():
                if k in plan["terminals"]:
                    e=plan["terminals"][k]
                    assert k==digest([e["kind"],e["hp"],e["max_hp"],e["gold"]])
                    label=e["kind"]+"/"+str(e["hp"])
                    law.append((e["kind"],None,utility(hp,e["hp"],mx,e["kind"]=="Defeat"),p))
                else:
                    label=keys[k]
                    law.append(("C",k,None,p))
                masses[label]+=p
            assert masses.keys()==plan["law"].keys() and all(abs(v-plan["law"][k])<1e-8 for k,v in masses.items())
            laws.append(law)
        ys=[v for b in r["blocks"][:2] for v in b["deltas"]]
        assert len(ys)==8 and len(set(s for b in r["blocks"] for s in b["seeds"]))==sum(len(b["seeds"]) for b in r["blocks"])
        d.pair_ids.append(r["family"])
        d.pairs.append((laws,hp,mx,mean(ys)))
        reports.append(dict(slot=r["slot"],family=r["family"],split=r["split"],role=r["role"],disagree=r["disagree"],turn=r["turn"],
                            same_first=r["ids"][0][0]==r["ids"][1][0],ys=ys,original=r["original"][0]-r["original"][1],
                            repeat=r["blocks"][2]["deltas"] if len(r["blocks"])>2 and r["blocks"][2]["status"]=="matched" else []))
    return streams,reports
if __name__=="__main__":prepare()
