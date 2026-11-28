"""Audit original human paths and the B2 target-only pairs with the released native replayer."""
import os,time
from diagnose import *
from native_audit import check
from semantic import static_rules,CARDS
from panel import sha
from engine.HotSearch.experience import read_rows

def native_row(steps,status,end):
    row=w.blank()
    for x in steps:
        o=x["observation"];i=x["index"];f=o["facts"]
        if o["status"]=="choice":
            row["choices"].append(dict(at=len(row["trace"])-1,options=o["options"],selected=i))
        else:w.record_boundary(row,f,public_b(f),i)
    return row|dict(status=status,terminal=end)

def main():
    import diagnose as module
    tick=time.perf_counter();m=s.Actor("v2");module.VALUE=m
    target=INFRA/"logs/hotsearch-h4/scene-oracle"
    os.environ["HOTSEARCH_ORACLE_DIR"]=str(target)
    oracle=target/"bin/Release/net9.0/OfflineSearchHarness.dll"
    assert sha(oracle)==read(INFRA/"experiments/m1-infra1h4/evidence/ledger.json")["native_binaries"]["scene-oracle"][oracle.name]
    host=s.SearchClient(W/"witness-host",False);rec=w.Recorder(host)
    refs=gz(E/"prefixes.gz");panel=read(E/"panel.json")["roots"]
    receipts={}
    rules=static_rules()
    save(E/"rules.json",dict(graphs={k:rules["graphs"].get(k) for k in ("BOWLBUG_ROCK","BOWLBUG_EGG","BOWLBUG_NECTAR","CHOMPER")},
                            powers={k:rules["powers"].get(k) for k in ("IMBALANCED_POWER","INFERNO_POWER","STRENGTH_POWER")},
                            cards={k:CARDS.get(k) for k in ("PRIMAL_FORCE","EXPECT_A_FIGHT","GIANT_ROCK","SHRUG_IT_OFF","BODY_SLAM","BLOOD_WALL")}))
    try:
        for r in panel[:4]:
            key=r["id"];d=gz(E/(key+".gz"));root=refs[key];spec=root["spec"];opening={k:spec[k] for k in ("hp","max_hp")}
            st,hist=w.recover(rec,m,dict(spec=spec,prefix=root,turn=r["turn"]),dict(prefix=w.blank()))
            h=public_b(st["facts"]);ref=host.reference(d["g2"][0],256,m,h,hist,opening)
            record=receipts[key]=dict(ref256=m.backup([ref],opening)[0],rows=[],states={})
            host.call("checkpoint")
            for world in d["worlds"]:
                seed=world["seed"]
                for tag,mode in d["labels"].items():
                    if world["sides"][tag]["status"]=="failed":continue
                    sample=rec.call("restore",**({} if seed is None else dict(world=seed)))
                    assert w.public(sample)==w.public(st)
                    after,mem,tr,k=run_turn(rec,m,sample,hist,opening,d["graphs"][tag],mode,tag)
                    assert k==world["sides"][tag]["boundary"]
                    row=dict(seed=seed,tag=tag,boundary=k)
                    if after.get("observed_c"):
                        cut=after["observed_c"];c=strategic(cut["facts"],cut["draw"])
                        if k not in record["states"]:
                            gl,x=encode(c)
                            with torch.inference_mode():p=m.evaluate.net(*pack([(gl,x)])).softmax(-1)[0].tolist()
                            record["states"][k]=dict(public=c,prob=p,value=m.evaluate({k:c},opening)[k],shape=list(x.shape))
                    if seed is None or key=="B2" and tag.startswith("B2-"):
                        if after["status"] in ("Victory","Defeat"):status,end=after["status"],after["facts"]
                        else:
                            b=w.blank()
                            s.hot.fight(rec,spec,m,"tactical",32,b,resume=(after,mem),require_match=True)
                            status,end=b["status"],b["terminal"]
                        assert (status,end["hp"])==(world["sides"][tag]["status"],world["sides"][tag]["terminal"]["hp"])
                        full=native_row(root["steps"]+rec.steps,status,end)
                        intervention=dict(at=sum(x["observation"]["status"]=="active" for x in root["steps"]),seed=seed,counts=st["facts"]["belief"]["counts"]) if seed is not None else None
                        try:
                            row["native"]=check(W/"native-witness",spec,full,intervention)
                        except (RuntimeError,ValueError,KeyError,TimeoutError,OSError) as e:row["native"]=dict(status="error",reason=str(e)[:400])
                    record["rows"].append(row)
            save(E/(key+"-witness.gz"),record)
    finally:host.close()
    save(E/"witness-ledger.json",dict(seconds=time.perf_counter()-tick,oracle=sha(oracle)))
if __name__=="__main__":main()
