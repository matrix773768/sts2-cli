"""Differential at Planner.__call__, including graph receipt and the complete conditional table."""
import gzip
import json
import os
from time import perf_counter
from native_h2 import ROOT,HERE,inputs,host_at,battle5d,cohort
from lane import BranchLane,Unsupported
from check import delta
from complete import Planner

def run():
    rows,panel=inputs()
    out=ROOT/"logs/infra1h2"/("turns-"+str(os.getpid()));out.mkdir()
    orig,g2,net,_=battle5d.configure(out,"V2");orig.close()
    import sys
    sys.path.insert(0,str(HERE.parent/"m1-infra1a"))
    import execution
    execution.install(dict(variant="batch",mode="baseline",kind="natural"),None,None)
    host=host_at(out,ROOT/"logs/infra1h2/5d-batch");lane=battle5d.Lane(host,0)
    sample=[("starter",dict(panel[0]["spec"],deck=[dict(id=c,upgrade=0) for c in ["STRIKE_IRONCLAD","DEFEND_IRONCLAD"]*4]))]
    sample.extend((str(row["i"]),panel[row["i"]]["spec"]) for row in rows if panel[row["i"]]["spec"]["encounter"]=="MECHA_KNIGHT_ELITE")
    results=[]
    try:
        for name,spec in sample:
            t=perf_counter();st=cohort.start(lane,spec);h=st["observation"];rec={"panel":name};results.append(rec)
            b=None
            try:
                b=BranchLane(lane,h,spec)
                g=b.request("i1_core1r2",mode="reduced",budget=512)
                old=lane.request("i1_core1r2",mode="reduced",budget=512)
                rec.update(nodes=len(g["nodes"]),graph_delta=delta({k:v for k,v in g.items() if k not in ("milliseconds","mode","schema_version","_b1a_ms")},
                    {k:v for k,v in old.items() if k not in ("milliseconds","mode","schema_version","_b1a_ms")})[:16])
                b.close();b=BranchLane(lane,h,spec)
                def query(backend):
                    plan=Planner(net);plan.detail=True
                    from hashlib import sha256
                    from semantic import encode
                    def model_key(c):
                        return sha256(b"".join(v.tobytes() for v in encode(c))).hexdigest()
                    captured=[]
                    def collect(graph,paths,laws,states,*rest):
                        captured.extend((k,model_key(v)) for k,v in states.items() if v.get("schema")=="sts2.core.c.v3")
                    plan.inspect=collect
                    qstart=perf_counter()
                    g,ch,q=plan(backend,host.project(h),[],net,g2,spec)
                    program=[(i,v) for i,v in sorted(ch.items())]
                    turn=plan.last
                    return dict(q=q,choices=program,graph_C_tensors=sorted(captured),
                        conditional_C_tensors=sorted((k,model_key(v)) for k,v in turn.states.items() if v.get("schema")=="sts2.core.c.v3"),
                        conditional_cache={repr(k):v for k,v in turn.cache.items()},
                        conditional_records=turn.records,seconds=perf_counter()-qstart)
                hot=query(b)
                old=query(lane)
                rec["candidate"]=hot["q"];rec["reference"]=old["q"];rec["hot_seconds"]=hot.pop("seconds");rec["reference_seconds"]=old.pop("seconds")
                rec["planner_delta"]=delta(hot,old)[:16]
                rec["C_tensors"]={k:len(hot[k]) for k in ("graph_C_tensors","conditional_C_tensors")}
                rec["C_tensors_equal"]=all(hot[k]==old[k] for k in rec["C_tensors"])
                rec["conditional_replies"]=len(hot["conditional_cache"])
                rec["hot_physical"]=dict(b.physical)
                rec["kernel_stats"]=b.rpc("stats")
                if name=="0":
                    identity=lane.request("i1_h2_branch",op="identity")["result"]
                    (HERE/"evidence/loaded.json").write_text(json.dumps(identity,indent=2))
            except Unsupported as e:rec["fallback"]=str(e)
            finally:
                if b is not None:b.close()
                lane.request("i1_core5_reference",clear=True);lane.reset()
                rec["seconds"]=perf_counter()-t
            (HERE/"evidence/turns.json").write_text(json.dumps(results,indent=2,default=str))
    finally:lane.close();host.close()
if __name__=="__main__":run()
