"""Apply the same option experiment to the unstratified, qualified N4 opening distribution."""
from pathlib import Path
import sys
from time import perf_counter
from design import LOGS, choices, cohort, read, runtime, write
from research import rollout


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    host,model=runtime(out)
    begin=perf_counter()
    try:
        for j in cohort.plan()[116:]:
            i,spec,_,family,_=j
            old=read(LOGS/f"n4-v2-confirm/{i:03}.json.gz")
            row=dict(id=i,family=family,split="natural",counter=None,worlds={},stop=old["stop"])
            if old["stop"]=="complete":
                repeat=read(LOGS/f"n4-v2-repeat-{116 if i<136 else 136}/{i:03}.json.gz")
                lane=host.lane()
                def position(w):
                    return cohort.prefix(lane,spec|dict(seed=w["seed"]),w["order"],i%3==1)
                # An independent anchor supplies the public graph; no scoring world selects candidates.
                anchor_seed=cohort.seed(family,"anchor",0)
                order=cohort.permutation(spec["deck"],old["hand"],cohort.seed(family,"anchor-order",0))
                hist,h,st=position(dict(seed=anchor_seed,order=order))
                assert {k:v for k,v in h.items() if k!="nunchaku"}==old["h"]
                options=choices(lane,model,h,hist)
                lane.reset()
                if options is None:
                    row["stop"]="no_eligible_graph_endpoint"
                else:
                    row.update(options,history=hist,h=h)
                    for block,k in (("selection",4),("reference",8)):
                        ws=row["worlds"][block]=[]
                        for w in repeat["blocks"][block][:k]:
                            refs={}
                            outcomes={}
                            for name,path in options["paths"].items():
                                key=cohort.digest(path)
                                refs[name]=key
                                if key in outcomes:
                                    continue
                                before,obs,st=position(w)
                                assert before==hist and obs==h
                                outcomes[key]=rollout(lane,model,hist,h,st,path,0)
                                lane.reset()
                            if any(y["utility"] is None for y in outcomes.values()):
                                row["stop"]="unresolved"
                            ws.append({k:w[k] for k in ("proposal","seed","order")}|dict(results={"0":dict(outcomes=outcomes,refs=refs)}))
            write(out/f"{i:03}.json.gz",row)
    finally:
        host.close()
        write(out/"run.json",dict(seconds=perf_counter()-begin))


if __name__=="__main__":
    run(Path(sys.argv[1]))
