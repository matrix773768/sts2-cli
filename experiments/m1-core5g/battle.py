"""Strict H5 fights. On V2 development battles also archive the genuine budget-32 menus."""
import gzip,hashlib,json,os,sys,time
from pathlib import Path
G=Path(__file__).resolve().parent
ROOT=G.parents[1]
INFRA=ROOT.parent/"sts2-infra"
E=G/"evidence"
W=ROOT/"logs/core5g"
os.environ["HOTSEARCH_BUILD"]=str(INFRA/"logs/hotsearch-h5")
sys.path.insert(0,str(INFRA/"engine/HotSearch"))
import hot_produce as hot
from models import Models,Evaluator,Value,torch,strategic,boundary_key
sys.path.insert(0,str(INFRA))
from engine.HotSearch.experience import check_battle,digest,sha,read_rows
POLICY="25740c4a3b29a5f378f6bd5723d3b594be6547a77e16b891e461bbf2bfcdcda7"

def record_menus(dest):
    original=hot.portfolio
    def capture(client,*args):
        result=original(client,*args)
        client.options=result
        return result
    hot.portfolio=capture
    class Recorder(hot.Client):
        def call(self,op,**fields):
            if op=="open":self.seed=fields["spec"]["seed"]
            return super().call(op,**fields)
        def reference(self,index,limit,models,h,history,opening):
            ref=super().reference(index,limit,models,h,history,opening)
            states={}
            def convert(g,style,value):
                leaves=[]
                if not g["gaps"]:
                    for leaf in g["leaves"]:
                        kind=leaf["kind"]
                        if kind=="C":
                            c=strategic(leaf["facts"],leaf["draw"])
                            key=boundary_key(kind,c)
                            states[key]=c
                        else:key=leaf["hp"]
                        leaves.append([kind,key,leaf["mass"]])
                return dict(index=g["index"],style=style,policy=g.get("policy",[]),gaps=g["gaps"],leaves=leaves,v2=value)
            plans=[convert(g,q["style"],q["value"]) for g,q in self.options]
            reference=convert(ref,"reference",None)
            dest.write(json.dumps(dict(seed=self.seed,turn=h["turn"],opening=opening,states=states,
                                       options=plans,reference=reference),separators=(",",":"))+"\n")
            return ref
    hot.Client=Recorder

def run(stage,arm,chunk):
    tick=time.perf_counter()
    specs=json.loads((E/("dev-battles.json" if stage=="dev" else "confirmation.json")).read_bytes())
    if stage=="confirm":
        assert arm in json.loads((E/"selection.json").read_bytes())["confirm"]
    panel=specs[chunk*64:(chunk+1)*64]
    assert panel
    if arm!="v2":
        row=json.loads((E/(arm+".json")).read_bytes())
        path=E/(arm+".pt")
        assert sha(path)==row["sha256"]
        class Candidate(Models):
            def __init__(self):
                super().__init__()
                net=Value()
                net.load_state_dict(torch.load(path,weights_only=True))
                self.evaluate=Evaluator(net.eval())
            def identity(self,*args):
                parent=super().identity(*args)
                assert parent["id"]==POLICY
                record=dict(schema="sts2.core5g.hotsearch.v1",parent=POLICY,value=row["sha256"],loader=sha(G/"battle.py"))
                return record|dict(id=digest(record))
        hot.Models=Candidate
    out=W/f"{stage}-{arm}-{chunk}"
    specs_path=out.with_suffix(".json")
    specs_path.write_text(json.dumps(panel))
    menus=None
    if stage=="dev" and arm=="v2":
        menus=gzip.open(E/"shared-menus.gz","xt",encoding="utf8")
        record_menus(menus)
    try:hot.run(out,None,"tactical",32,specs_path)
    finally:
        if menus:menus.close()
    rows=[]
    for spec,r in zip(panel,read_rows(out/"natural.jsonl.gz"),strict=True):
        assert (spec["family"],spec["spec"]["seed"])==(r["family"],r["seed"])
        if r["status"]!="failed":check_battle(r)
        t=r["terminal"]
        qs=r["queries"]
        rows.append(dict(family=r["family"],seed=r["seed"],opening=r["opening_hp"],maximum=r["opening_max_hp"],
                         status=r["status"],end=t["hp"] if t else None,reason=r.get("reason"),queries=len(qs),
                         closed=sum(q["reference_law"]["value"] is not None for q in qs),interventions=sum(q.get("committed",False) for q in qs)))
    ledger=json.loads((out/"ledger.json").read_bytes())
    if arm=="v2":assert ledger["policy"]["id"]==POLICY
    result=dict(stage=stage,arm=arm,chunk=chunk,rows=rows,ledger=ledger,seconds=time.perf_counter()-tick,raw=sha(out/"natural.jsonl.gz"))
    (E/f"{stage}-{arm}-{chunk}.json").write_text(json.dumps(result,separators=(",",":")))
if __name__=="__main__":run(sys.argv[1],sys.argv[2],int(sys.argv[3]))
