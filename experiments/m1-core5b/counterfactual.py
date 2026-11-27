"""Change one eligible turn, resume high V2, and record realized outcomes on the paired seed."""
from deploy5b import *
from assessment import utility
def run_cf():
    out=LOGS/"5b-counterfactual-fixed";out.mkdir(exist_ok=False);t=perf_counter()
    host,g2,net,plan=init(out,"high");lane=Lane(host,0)
    panel=json.load(gzip.open(E/"panel.gz","rt"))["fresh"]
    rows={r["i"]:r for f in E.glob("fresh-high-*.gz") for r in records(f)}
    with gzip.open(E/"counterfactual.gz","xt") as f:
        for i in range(0,len(panel),2):
            row=rows[i];spec=panel[i]["spec"]
            if not row["terminal"]:continue
            choices=[]
            for q in row["queries"]:
                if q["used"]:choices.append((q,None,"intervention"));continue
                opts=[o for o in q["options"] if o[0]>=1-1e-9]
                if opts:
                    best=max(opts,key=lambda o:o[1])
                    choices.append((q,best[2],"reference_gap" if q["reference_coverage"]<1-1e-9 else "gate_or_reference"))
            if not choices:continue
            q,j,why=min(choices,key=lambda x:(abs(x[0]["turn"]-3),x[0]["turn"]))
            plan.force=(q["turn"],j)
            alt=fight(lane,g2,spec,"high",net,planner=plan);lane.reset()
            alt.pop("states")
            f.write(json.dumps(dict(i=i,turn=q["turn"],reason=why,main=q,alternate=alt,
                delta=utility(alt|spec)-utility(row) if alt["terminal"] else None))+"\n");f.flush()
    lane.close();host.close();(E/"counterfactual-cost.json").write_text(json.dumps(perf_counter()-t))
if __name__=="__main__":run_cf()
