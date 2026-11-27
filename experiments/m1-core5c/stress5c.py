"""Compare exact ordered transcripts to the multiset quotient for the same post-draw policy."""
import sys,json,gzip
from time import perf_counter
from collections import Counter
from panel5c import E,OUT
from complete import Turn,PublicLane,setup
from deploy5b import Lane
from turn_worlds import source,prefix,restore,model_key
from memory5c import peak
class Ordered(Turn):
    def outcomes(self,route,group=False,merged=False,p=1.):
        # Keep the continuation identical to the quotient's (order-invariant) legal menu.
        k,v=self.read(route)
        batch=group and k=="R" and v[1]>1
        yield from super().outcomes(route,False,merged or batch,p)
def run(mode,limit):
    t=perf_counter()
    out=OUT/f"stress-{mode}-{limit}"
    out.mkdir(parents=True,exist_ok=True)
    host,g2,net,plan=setup(out,"V2complete")
    lane=Lane(host,0)
    d=source("loss")
    past=prefix(lane,g2,net,d)
    restore(lane,d,past)
    h=d["right"]["snapshot"]["h"]
    start=perf_counter()
    engine=(Turn if mode=="multiset" else Ordered)(PublicLane(lane),h,d["spec"],plan.evaluator,128-len(past))
    engine.cap=limit
    action=next(a for a in h["actions"] if a["kind"]=="play_card" and h["hand"][a["card"]]["id"]=="BATTLE_TRANCE")
    data={}
    for style in ("end","block","repeat","attack"):
        rows=[]
        engine.follow(h,action,(),style,False,1.,(),rows)
        law=Counter()
        for w,k,v,_ in rows:
            key=(model_key(engine.states[v]) if k=="C" else k)
            law[key]+=w
        data[style]=dict(law=law,mass=sum(law.values()),leaves=len(rows))
    result=dict(policies=data,requests=len(engine.cache),sim_calls=engine.calls,seconds=perf_counter()-start,
                host_peak=peak(int(lane.client.proc._handle)),python_peak=peak(),wall=perf_counter()-t)
    lane.close()
    host.close()
    (E/f"stress-{mode}-{limit}.json").write_text(json.dumps(result,indent=2))
if __name__=="__main__":
    run(sys.argv[1],int(sys.argv[2]))
