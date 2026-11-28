"""Volatile experiment evaluator; frozen H5 search and action binding run as released."""
import gzip,os,sys,time
from paths5h import *
os.environ["HOTSEARCH_BUILD"]=str(INFRA/"logs/hotsearch-h5")
sys.path.insert(0,str(INFRA/"engine/HotSearch"))
import hot_produce as hot
from models import Models,Evaluator,torch
from nets5h import network
sys.path.insert(0,str(INFRA))
from engine.HotSearch.experience import digest,sha,check_battle,read_rows

POLICY="25740c4a3b29a5f378f6bd5723d3b594be6547a77e16b891e461bbf2bfcdcda7"
def run(stage,arm,index):
    tick=time.perf_counter()
    jobs=json.load(gzip.open(E/"confirm.gz")) if stage=="confirm" else read(G/"evidence/dev-battles.json")
    if stage=="confirm":assert arm in read(E/"selection.json")["arms"]
    panel=jobs[64*index:64*(index+1)]
    out=W/f"{stage}-{arm}-{index}"
    path=out.with_suffix(".json")
    save(path,panel)
    cost=dict(seconds=0.,batches=0,rows=0)
    class Measured(Models):
        def __init__(self):
            super().__init__()
            if arm!="v2":
                weights=LONG if arm=="long" else E/(arm+".pt")
                meta=read(weights.with_suffix(".json"))
                self.weight=sha(weights)
                assert self.weight==meta["sha256"]
                net=network(meta.get("kind","pool"))
                net.load_state_dict(torch.load(weights,weights_only=True))
                self.evaluate=Evaluator(net.eval())
            net=self.evaluate.net
            original=net.forward
            def timed(g,x,m):
                start=time.perf_counter()
                result=original(g,x,m)
                cost["seconds"]+=time.perf_counter()-start
                cost["batches"]+=1
                cost["rows"]+=len(g)
                return result
            net.forward=timed
        def identity(self,*args):
            parent=super().identity(*args)
            assert parent["id"]==POLICY
            if arm=="v2":return parent
            body=dict(schema="sts2.core5h.value.v1",base_policy=POLICY,weight=self.weight,architecture=sha(H/"nets5h.py"),entry=sha(H/"fight5h.py"))
            return body|dict(id=digest(body))
    hot.Models=Measured
    hot.run(out,None,"tactical",32,path)
    rows=[]
    for job,r in zip(panel,read_rows(out/"natural.jsonl.gz"),strict=True):
        assert r["family"]==job["family"] and r["seed"]==job["spec"]["seed"]
        if r["status"]!="failed":check_battle(r)
        q=r["queries"]
        rows.append(dict(family=r["family"],seed=r["seed"],opening=r["opening_hp"],maximum=r["opening_max_hp"],end=r["terminal"]["hp"] if r["terminal"] else None,
                         status=r["status"],reason=r.get("reason"),queries=len(q),closed=sum(z["reference_law"]["value"] is not None for z in q),
                         interventions=sum(z.get("committed",False) for z in q)))
    save(E/(out.name+".json"),dict(rows=rows,seconds=time.perf_counter()-tick,forward=cost,ledger=read(out/"ledger.json"),raw_sha256=sha(out/"natural.jsonl.gz")))
if __name__=="__main__":run(sys.argv[1],sys.argv[2],int(sys.argv[3]))
