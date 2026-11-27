"""Frozen G2 trajectories from open DC1 roots, grouped by family before simulation."""
import gzip,json,sys
from pathlib import Path
from time import perf_counter
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"m1-core2"))
from state import rule_context
from search import host_at,Lane,step,cohort,read,digest
from design import runtime,prepared
ROOT=HERE.parents[1]

def jobs():
    reserved={j["family"] for j in read(HERE.parent/"m1-core1/benchmark.json")["jobs"]}
    rows=read(ROOT/"logs/m1-dc1-formal/roots/train.json")["jobs"]
    ids=sorted({j[3] for j in rows}-reserved,key=lambda f:digest(["core3-family",f]))
    groups={f:("confirmation" if i%10==0 else "development" if i%10==1 else "train") for i,f in enumerate(ids)}
    return [(groups[f],j) for f in ids for j in rows if j[3]==f]

def setup(out):
    old,model=runtime(out)
    old.close()
    return host_at(out,ROOT/"logs/core2-state03"),model

def finish(lane,model,st,hist=(),counts=None,last=None):
    h=lane.host.project(st["observation"]) if st["status"]=="active" else None
    c=prepared(model,h,hist) if h else None
    if c:c.project=lane.host.project
    states=[]
    while st["status"]=="active" and st["actions"]<128:
        h=lane.host.project(st["observation"])
        a,_,_=c.act(h,lane,st["actions"])
        st=step(lane,st,a)
        c.after(st)
        if st.get("observed_c"):states.append(st["observed_c"])
    if counts is not None and c is not None:counts.update(c.counts)
    if last is not None:last.update(st.get("terminal_observation") or st.get("observation") or {})
    t=st.get("terminal_observation")
    return dict(status=st["status"],actions=st["actions"],states=states,
        terminal=(t|dict(gold=(st.get("result") or {}).get("gold"))) if t and st["status"] in ("death","predicted_win") else None)

def run(out,start,count):
    out.mkdir(parents=True,exist_ok=False)
    t=perf_counter()
    host,model=setup(out)
    lane=Lane(host,0)
    with gzip.open(out/"fights.gz","wt",encoding="utf8",compresslevel=3) as stream:
        for split,j in jobs()[start:start+count]:
            try:
                st=cohort.start(lane,j[1])
                row=finish(lane,model,st)
                lane.reset()
            except (ValueError,RuntimeError,KeyError) as ex:
                lane.close()
                row=dict(error=str(ex),terminal=None,states=[])
            stream.write(json.dumps(dict(split=split,family=j[3],ordinal=j[0],policy="frozen-G2",**row),separators=(",",":"))+"\n")
    lane.close();host.close()
    (out/"seconds.json").write_text(json.dumps(perf_counter()-t))
if __name__=="__main__":run(Path(sys.argv[1]),int(sys.argv[2]),int(sys.argv[3]))
