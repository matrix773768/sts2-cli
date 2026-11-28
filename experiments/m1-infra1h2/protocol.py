"""Capture frozen schemas for the selector and graph development cases."""
import gzip
import json
from native_h2 import ROOT,HERE,inputs,host_at,battle5d,cohort
def run():
    rows,panel=inputs()
    out=ROOT/"logs/infra1h2/protocol"
    out.mkdir(exist_ok=True)
    host=host_at(out,ROOT/"logs/infra1h2/5d")
    lane=battle5d.Lane(host,0)
    try:
        for tag,deck in [("natural",None),("starter",["STRIKE_IRONCLAD"]*4+["DEFEND_IRONCLAD"]*4)]:
            spec=panel[0]["spec"].copy()
            if deck:spec["deck"]=[dict(id=c,upgrade=0) for c in deck]
            st=cohort.start(lane,spec)
            h=st["observation"]
            g=lane.request("i1_core1r2",mode="reduced",budget=512)
            with gzip.open(out/(tag+".gz"),"wt") as f:json.dump(g,f)
            if not deck:
                route=[dict(action=3,draws=[])]
                records=[]
                for idx in [None,0,0]:
                    if idx is not None:route.append(dict(action=idx,draws=[]))
                    rec=lane.request("i1_core5_reference",route=route,complete=True)["response"]
                    records.append(rec)
                (out/"selector.json").write_text(json.dumps(records))
            lane.reset()
    finally:lane.close();host.close()
if __name__=="__main__":run()
