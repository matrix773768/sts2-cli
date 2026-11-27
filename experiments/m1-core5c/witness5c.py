"""Restore the archived turn, generate normal policies, then execute every complete proposal."""
import sys,gzip,json
from time import perf_counter
from panel5c import E,OUT,FIVE
from complete import setup,program,execute_program,observation,move
from turn_worlds import source,prefix,restore,continue_high,model_key
from deploy5b import Lane,Search,Evaluator,load_net
from review import description
def run(tag):
    start=perf_counter()
    out=OUT/tag
    out.mkdir(parents=True,exist_ok=True)
    host,g2,net,planner=setup(out,"V2complete")
    lane=Lane(host,0)
    old=Search(net,"high")
    d=source(tag)
    past=prefix(lane,g2,net,d)
    restore(lane,d,past)
    h=d["right"]["snapshot"]["h"]
    planner.detail=True
    g,ch,q=planner(lane,h,past,net,g2,d["spec"])
    turn=planner.last
    lane.reset()
    v1=Evaluator(load_net(FIVE.parent/"m1-core4/evidence/v1.pt","V1high"))
    values=v1({k:v for k,v in turn.states.items() if "belief" in v},d["spec"])
    values={k:values.get(k,v) for k,v in turn.values.items()}
    results=[]
    for group in turn.records:
        first=json.loads(group["first"])
        for style,rows in (group["proposals"]|{"chosen":group["chosen"]}).items():
            cov,v,mass=turn.score(rows)
            row=dict(first=first,style=style,mass=mass,coverage=cov,v2=v,v1=sum(w*values.get(key,-50.) for w,k,key,_ in rows))
            if cov>=1-1e-9:
                st=restore(lane,d,past)
                st,played,reason=execute_program(lane,st,program(rows))
                actions=[]
                for o,i in played:
                    a=description(o,i)
                    if a["kind"]=="select_candidate":
                        a["pick"]=o["decision"]["candidates"][a["choice"]]
                    actions.append(a)
                row.update(actions=actions,execution=reason)
                if reason not in ("end","terminal"):
                    raise ValueError((tag,first,style,reason))
                if st.get("observed_c"):
                    key=model_key(st["observed_c"])
                    # Require the witnessed path AND the observed strategic input to agree.
                    signatures=[(observation(o,False),observation(o,True),move(o,o["actions"][i])) for o,i in played]
                    leaves=[leaf for _,kind,leaf,path in rows if kind=="C" and len(path)==len(signatures) and
                        all(k==sig[int(merged)] and action==sig[2] for (k,action,merged),sig in zip(path,signatures))]
                    row["matched_c"]=any(model_key(turn.states[leaf])==key for leaf in leaves)
                    if not row["matched_c"]:
                        raise ValueError((tag,first,style,"C mismatch"))
                st=continue_high(lane,st,past+played,g2,net,old,d["spec"])
                row.update(status=st["status"],terminal=st.get("terminal_observation"))
                lane.reset()
            results.append(row)
    host.close()
    lane.close()
    with gzip.open(E/f"witness-{tag}.gz","wt") as f:
        json.dump(dict(query=q,proposals=turn.records,
       observations=turn.snapshots,states=turn.states,values=dict(v1=values,v2=turn.values),results=results,
       seconds=perf_counter()-start),f,separators=(",",":"))
if __name__=="__main__":
    run(sys.argv[1])
