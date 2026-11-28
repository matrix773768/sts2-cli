"""Check release invariants and collect the final worker ledger and coverage."""
import ast,gzip,sys,time
from collections import Counter
from paths5h import *
sys.path.insert(0,str(G))
from settings import sha,digest,load,A
from engine.HotSearch.experience import read_rows

def main():
    tick=time.perf_counter()
    banned={f for item in load(A/"history.gz")["sources"].values() for f in item["families"]}
    for ed,k in [("train","train"),("dev","dev"),("reserve","train")]:banned.update(r["family"] for r in load(A/(ed+".gz"))[k])
    banned.update(r["family"] for r in read(G/"evidence/confirmation.json"))
    panels={}
    for group in ("confirm","open"):
        rows=load(E/(group+".gz"))
        ids=Counter(r["family"] for r in rows)
        assert not banned.intersection(ids) and all(r["family"]==digest(sorted(c["id"] for c in r["spec"]["deck"])) for r in rows)
        assert len(set(r["spec"]["seed"] for r in rows))==len(rows)
        banned.update(ids)
        panels[group]=rows
        assert (len(ids),set(ids.values()))==((128,{2}) if group=="confirm" else (960,{1}))
    assert sha(LONG)==read(LONG.with_suffix(".json"))["sha256"] and sha(SCRATCH)==read(SCRATCH.with_suffix(".json"))["sha256"]
    selection=read(E/"selection.json")
    src=read(E/"source.json")
    production=read(E/"production.json")
    for file,h in production["archives"].items():assert sha(E/file)==h
    assert production["protocol_sha256"]==sha(H/"protocol.md")
    run_identity=dict(schema="sts2.core5h.active-experience.v1",core_start="1afd5ea78ebc1555ca5725533b2a1f1ec3783146",
                      infra_commit="80ca8165fee768ba4e2b55bfd367ee00df650616",source_release=src["release"],
                      natural_policy="25740c4a3b29a5f378f6bd5723d3b594be6547a77e16b891e461bbf2bfcdcda7",
                      suffix_behavior="51ed7db73b4d583c183d5a37bbcb6a2f3585bc73cd4cb931774fee46b8e32616",
                      selector_long=sha(LONG),native_audit="not_run",root_budget=32,suffix_budget=32,
                      infra_worlds=sha(A/"worlds.py"),adapter=sha(H/"collect5h.py"),protocol=sha(H/"protocol.md"),
                      open_cohort=sha(E/"open.gz"),raw_shards=production["archives"],
                      root_receipts={p.name:sha(p) for p in sorted(E.glob("root-*.gz"))})
    save(E/"release.json",run_identity|dict(id=digest(run_identity)))
    assert len({r["family"] for r in production["roots"]})==len(production["roots"])
    from statistics import mean
    import numpy as np
    from evidence5h import cluster
    rng=np.random.default_rng(5852)
    strata={}
    for root in production["roots"]:
        if root["role"]!="disagreement":
            continue
        receipt=load(E/f"root-{root['slot']:03}.gz")
        plans=[next(p for p in receipt["menu"] if [p["first"],p["style"]]==key) for key in receipt["ids"]]
        gap=plans[0]["long"]-plans[1]["long"]
        band="below_one" if gap<1 else "one_or_more"
        for split in ("all",root["split"]):
            strata.setdefault(f"{split}-{band}",[]).append(dict(slot=root["slot"],gap=gap,effect=root["effect"]))
    save(E/"margin-strata.json",{name:dict(roots=rows,actual=cluster([r["effect"] for r in rows],rng),
                                            mean_absolute=mean(abs(r["effect"]) for r in rows))
                                 for name,rows in strata.items()})
    weights=list(E.glob("*.pt"))
    assert len(weights)==12
    scratch_weights=list((E/"scratch").glob("*/*.pt"))
    assert len(scratch_weights)==4
    weights.extend(scratch_weights)
    for p in weights:assert sha(p)==read(p.with_suffix(".json"))["sha256"]
    ledger=dict(production=sum(read(E/f"scans-{j}.json")["seconds"] for j in range(4)),source=src["seconds"],
                fit=sum(read(E/f"fit-worker-{s}.json")["seconds"] for s in (5719,7213)),
                network_check=read(E/"network-checks.json")["seconds"],archive_analysis=production["seconds"],
                decision_analysis=read(E/"decisions.json")["seconds"],diagnostics=read(E/"diagnostics.json")["seconds"])
    ledger["exploratory_scratch"]=sum(read(E/f"scratch-{seed}.json")["seconds"] for seed in (5719,7213))
    coverage={}
    historical={}
    confirm_rows={}
    shards=0
    for stage,arms,jobs in [("dev",["v2","long",*selection["entries"]],read(G/"evidence/dev-battles.json")),
                              ("confirm",selection["arms"],panels["confirm"])]:
        cost=0
        for a in arms:
            ordered=[]
            for j in range(len(jobs)//64):
                name=f"{stage}-{a}-{j}"
                r=read(E/(name+".json"))
                raw=W/name/"natural.jsonl.gz"
                assert sha(raw)==r["raw_sha256"]
                ordered+=r["rows"]
                ident=r["ledger"]["policy"]
                if a!="v2":
                    assert ident["weight"]==sha(LONG if a=="long" else E/(a+".pt")) and ident["architecture"]==sha(H/"nets5h.py") and ident["entry"]==sha(H/"fight5h.py")
                assert all((z["status"]=="failed")==(z["end"] is None) for z in r["rows"])
                if a=="v2":
                    c=coverage.setdefault(stage,Counter())
                    for row in read_rows(raw):
                        for q in row["queries"]:
                            options=q["options"]
                            closed=[z for z in options if z["value"] is not None]
                            c["options"]+=len(options)
                            c["closed_options"]+=len(closed)
                            c["queries"]+=1
                            if q["reference_law"]["value"] is None:c["open_reference"]+=1
                            elif not closed:c["closed_reference_no_closed_candidate"]+=1
                cost+=r["worker_seconds"]
                shards+=1
            assert [(r["family"],r["seed"]) for r in ordered]==[(r["family"],r["spec"]["seed"]) for r in jobs]
            if stage=="dev":
                historical[a]=[{k:ordered[i][k] for k in ("family","seed","status","end")} for i in (22,46)]
            else:
                confirm_rows[a]=ordered
        ledger[stage+"_battles"]=cost
    from campaign5h import paired,complete
    # Pair every arm against the shared warm start. Also compare on identical admitted worlds.
    common=[i for i in range(len(panels["confirm"])) if all(complete(rows[i]) for rows in confirm_rows.values())]
    shared={a:[rows[i] for i in common] for a,rows in confirm_rows.items()}
    save(E/"common-panel.json",dict(
        vs_long={a:paired(rows,confirm_rows["long"]) for a,rows in confirm_rows.items()},
        shared_worlds=common,all_arms_common_vs_v2={a:paired(rows,shared["v2"]) for a,rows in shared.items()}))
    for path in H.glob("*.py"):ast.parse(path.read_text(encoding="utf8"))
    ledger["audit"]=time.perf_counter()-tick
    measured=sum(ledger.values())
    save(E/"historical-cases.json",dict(indices=[22,46],arms=historical))
    save(E/"ledger.json",dict(measured=measured,phases=ledger,allowance=180,budget_charge=measured+180,coverage=coverage,
                              weights=len(weights),battle_shards=shards,scope="Worker sums; 180 seconds estimated for freeze, smoke checks, subprocess import overhead, selection and remaining checks. Writing/Git excluded."))
if __name__=="__main__":main()
