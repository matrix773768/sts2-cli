"""Blind paired diagnostic on all eligible confirmation families, with frozen V0 continuation."""
from play_loop import fight,load_net
from core4_roots import *
from assessment import rows,ci,utility
from semantic import torch,encode,pack,expected
import numpy as np

def run(out,logs):
    start=perf_counter();logs.mkdir(parents=True,exist_ok=False);torch.set_num_threads(1)
    primary={r["family"]:r for f in out.glob("test-v0-*.gz") for r in rows(f)}
    host,g2=setup(logs);lane=Lane(host,0);net=load_net(out/"v0.pt","v0");updated=load_net(out/"v1.pt","v1")
    records=[]
    with gzip.open(out/"paired-check.gz","wt") as stream:
        for j in panels()["confirm"]:
            r=primary[j[3]]
            switches=[q["turn"] for q in r.get("queries",[]) if q["used"] and q["turn"]>=2]
            if not switches or not r.get("terminal"):continue
            skip=switches[len(switches)//2];spec=spec_for(j,"test")
            a=fight(lane,g2,spec,"v0",net,skip=skip);lane.reset()
            a.update(family=j[3],policy="skip_one_then_v0",seed=r["seed"],hp=r["hp"],max_hp=r["max_hp"],skip=skip)
            stream.write(json.dumps(a,separators=(",",":"))+"\n")
            if not a.get("terminal"):continue
            assert [c for c in r["states"] if c["turn"]<=skip]==[c for c in a["states"] if c["turn"]<=skip]
            def result(record):
                c=next((c for c in record["states"] if c["turn"]==skip+1),None)
                if not c:return None
                with torch.no_grad():
                    return expected(updated(*pack([encode(c)])).softmax(-1),torch.tensor(r["hp"]),torch.tensor([c["hp"]]),torch.tensor(r["max_hp"])).item()
            left,right=result(r),result(a)
            records.append(dict(family=j[3],turn=skip,actual=utility(r)-utility(a),prediction=None if left is None or right is None else left-right))
    lane.close();host.close()
    compare=[(r["actual"],r["prediction"])for r in records if r["actual"] and r["prediction"] is not None]
    correct=sum(x*y>0 for x,y in compare)
    (out/"paired-check.json").write_text(json.dumps(dict(rows=records,teacher_effect=ci([r["actual"] for r in records]),
        nonzero_with_two_C=len(compare),correct_direction=correct,seconds=perf_counter()-start),indent=2))
if __name__=="__main__":run(Path(sys.argv[1]),Path(sys.argv[2]))
