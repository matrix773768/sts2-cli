"""Estimate a two-plan terminal-outcome teacher and validate it in independent conditional decks."""
from produce import *
from assessment import utility,ci
from statistics import mean

def teacher(out):
    out.mkdir(parents=True,exist_ok=False);start=time.perf_counter()
    old,g2=runtime(out);old.close();host=host_at(out,ROOT/"logs/core5a-host3");lane=Lane(host,0)
    net=load_net(FIVE.parent/"m1-core4/evidence/v1.pt","v1")
    plan=Planner(net)
    with gzip.open(FIVE/"evidence/panels.gz","rt") as f:jobs=json.load(f)["dev"]
    cases=[]
    for j in jobs:
        spec=j[1]|dict(seed=cohort.seed(j[3],"5a-teacher",0))
        st=cohort.start(lane,spec);h=host.project(st["observation"])
        law=st["public_law"];turn=h["turn"]
        plan.alternate_turn=None
        _,_,q=plan(lane,h,[],net,g2,spec)
        lane.reset()
        if "predicted_gap" not in q:continue
        ws=[]
        for w in range(4):
            # Independently sample the hidden deck tail conditional on the same opening.
            order=cohort.permutation(spec["deck"],h["hand"],digest([j[3],"5a-tail",w]))
            st=cohort.start(lane,spec,order)
            matched=host.project(st["observation"])==h and st["public_law"]==law
            lane.reset()
            if not matched:
                ws.append(dict(matched=False));continue
            outcomes=[]
            for alt in (False,True):
                plan.alternate_turn=turn if alt else None
                row=fight(lane,g2,spec,"v1",net,planner=plan,order=order);lane.reset()
                outcomes.append(dict(status=row["status"],terminal=row["terminal"],actions=row["actions"],
                    value=utility(row|spec) if row["terminal"] else None,first=row["queries"][0]))
            ws.append(dict(matched=True,order=order,outcomes=outcomes))
        cases.append(dict(family=j[3],seed=spec["seed"],gap=q["predicted_gap"],worlds=ws))
    lane.close();host.close()
    gains=[]; switched=0; held_improvements=[]
    for c in cases:
        ws=c["worlds"]
        if not all(w["matched"] and all(r["value"] is not None for r in w["outcomes"]) for w in ws):continue
        ds=[w["outcomes"][1]["value"]-w["outcomes"][0]["value"] for w in ws]
        switch=mean(ds[:2])>0
        gains.append(mean(ds[2:]) if switch else 0.)
        if switch:switched+=1;held_improvements.append(mean(ds[2:]))
    summary=dict(eligible=len(cases),complete=len(gains),switched=switched,teacher_vs_v1=ci(gains),
                 conditional_switch_gain=ci(held_improvements),seconds=time.perf_counter()-start)
    (out/"teacher.json").write_text(json.dumps(summary,indent=2))
    with gzip.open(out/"worlds.gz","wt") as f:json.dump(cases,f)
if __name__=="__main__":teacher(Path(sys.argv[1]))
