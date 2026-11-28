"""One measured shard with raw public export and frozen production readback."""
import time
START=time.perf_counter()
import sys,gzip,json
from collections import Counter
from branch import Actor,portfolio,H,E,W,s
from battle6 import published,check_segment,read_rows,sha,read,save

def run(stage,arm,index):
    if stage=="dev":
        jobs=read(H.parent/"m1-core5g/evidence/dev-battles.json")[:32]
    else:
        selection=read(E/"selection.json")
        assert arm in selection["arms"] and sha(E/"confirm.gz")==selection["panel_sha"]
        with gzip.open(E/"confirm.gz") as f:jobs=json.load(f)[index*64:(index+1)*64]
    name=f"{stage}-{arm}-{index}"
    root=W/name
    root.mkdir(parents=True,exist_ok=False)
    save(root/"jobs.json",jobs)
    actor=Actor(arm)
    if stage=="confirm":assert actor.identity("tactical",32)["id"]==selection["policies"][arm]
    s.hot.Models=lambda:actor
    s.hot.Client=lambda out:s.SearchClient(out,True)
    s.hot.portfolio=portfolio
    original=s.hot.fight
    with gzip.open(root/"public.gz","wt",encoding="utf8",compresslevel=2) as public:
        def record(client,spec,*args,**kwargs):
            try:return original(client,spec,*args,**kwargs)
            finally:
                segment=dict(origin="open",world=None,steps=client.steps)
                public.write(json.dumps(dict(seed=spec["seed"],segment=segment),separators=(",",":"),allow_nan=False)+"\n")
        s.hot.fight=record
        try:s.hot.run(root/"engine",None,"tactical",32,root/"jobs.json")
        finally:s.hot.fight=original
    raw=root/"engine/natural.jsonl.gz"
    rows=[]
    for job,b,v in zip(jobs,read_rows(raw),read_rows(root/"public.gz"),strict=True):
        assert job["family"]==b["family"] and job["spec"]["seed"]==b["seed"]==v["seed"]
        if b["status"]!="failed":
            published.check_battle(b)
            check_segment(v["segment"],b)
        qs=b["queries"];opts=[o for q in qs for o in q["options"]]
        wins=Counter();realized=0;changed_first=0
        # Raw bindings are scoped to a turn. Reconstruct actual per-turn (cursor,view,index)
        # from the public trace and chosen tree, including intermediate choices.
        steps_by_turn={}
        for step in v["segment"]["steps"]:
            obs=step["observation"]
            steps_by_turn.setdefault(obs["facts"]["turn"],[]).append((obs["view"],step["index"]))
        for q in qs:
            style=q.get("winner_style","")
            if not style.startswith("branch-"):continue
            wins[style]+=1
            opt=next(o for o in q["options"] if o["style"]==style and o["index"]==q["selected"]
                     and o["value"]==max(x["value"] for x in q["options"] if x["value"] is not None))
            edges={(e["parent"],e["view"]):e for e in q["policy"]}
            diff={tuple(e) for e in opt["changed_edges"]};parent=0
            for view,j in steps_by_turn.get(q["turn"],[]):
                e=edges.get((parent,view))
                if not e or e["index"]!=j:break
                if (parent,view,j) in diff:
                    realized+=1;changed_first+=int(parent==0);break
                parent=e["node"]
        rows.append(dict(family=b["family"],seed=b["seed"],status=b["status"],reason=b.get("reason"),
             opening=b["opening_hp"],maximum=b["opening_max_hp"],end=b["terminal"]["hp"] if b["terminal"] else None,
             steps=b["actual_steps"],C=len(b["states"]),seconds=b["seconds"],queries=len(qs),
             closed=sum(q["reference_law"]["value"] is not None for q in qs),
             candidates=len(opts),complete_options=sum(o["value"] is not None for o in opts),
             option_steps=sum(o["steps"] for o in opts),reference_steps=sum(q["reference_law"]["steps"] for q in qs),
             interventions=sum(q["committed"] for q in qs),branch_winners=dict(wins),realized=realized,changed_first=changed_first))
    ledger=read(root/"engine/ledger.json")
    save(E/(name+".json"),dict(arm=arm,stage=stage,index=index,rows=rows,metrics=dict(actor.metrics),
         model_work=ledger["model_work"],host=ledger["host"],policy=ledger["policy"],raw=sha(raw),public=sha(root/"public.gz"),
         process_seconds=time.perf_counter()-START))
if __name__=="__main__":run(sys.argv[1],sys.argv[2],int(sys.argv[3]))
