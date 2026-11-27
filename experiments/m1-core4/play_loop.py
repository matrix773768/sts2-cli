"""Run complete policies; alternate suffixes keep the same public prefix and frozen continuation."""
from improve import *
from core4_roots import panels,spec_for
from turn_value import compile_turn
from value_net import network as old_network

def fight(lane,g2,spec,mode,net,skip=None,trace=None,planner=graph_plan,order=None,counts=None,last=None):
    st=cohort.start(lane,spec,order);history=[];states=[];queries=[]
    if mode in ("G2","G2search"):
        g2.budget=24 if mode=="G2search" else 0
        result=finish(lane,g2,st,counts=counts,last=last);g2.budget=0
        return result|dict(queries=[])
    locked=-1
    while st["status"]=="active" and st["actions"]<128:
        h=lane.host.project(st["observation"]);turn=h["turn"];before=st["actions"]
        if h["decision"]["phase"]=="combat" and turn!=locked:
            if mode=="core3":
                g,ch,ops,q=compile_turn(lane,h,history,net,"simple")
                use=ops and ops[0][1]>=1-1e-9;idx=ops[0][0] if ops else None
            else:
                g,ch,q=planner(lane,h,history,net,g2,spec);use=q["use"];idx=ch.get(0)
            queries.append(q|dict(turn=turn,used=bool(use and turn!=skip),hp=h["hp"]))
            if use and turn!=skip:
                st,played,reason=g["execute"](lane,st) if "execute" in g else execute(lane,st,g,ch,idx)
                history.extend(played);queries[-1]["result"]=reason
            if mode!="core3":locked=turn
        if st["actions"]==before:
            ctrl=prepared(g2,h,history);ctrl.project=lane.host.project
            a,_,_=ctrl.act(h,lane,before);history.append((h,a));st=step(lane,st,a)
        if st.get("observed_c"):states.append(st["observed_c"])
    if trace is not None:trace.extend(history)
    if last is not None:last.update(st.get("terminal_observation") or st.get("observation") or {})
    end=st.get("terminal_observation")
    return dict(status=st["status"],actions=st["actions"],states=states,queries=queries,
        terminal=(end|dict(gold=(st.get("result") or {}).get("gold"))) if end and st["status"] in ("predicted_win","death") else None)

def load_net(path,mode):
    if mode.startswith("G2"):return None
    net=old_network("simple") if mode=="core3" else Value()
    net.load_state_dict(torch.load(path,weights_only=True));net.eval();return net

def run(out,path,group,mode,count,shard,n,repeat=0):
    out.mkdir(parents=True,exist_ok=False);start=perf_counter();host,g2=setup(out);lane=Lane(host,0)
    net=load_net(path,mode)
    with gzip.open(out/"rows.gz","wt",encoding="utf8",compresslevel=3) as stream:
        for index,j in enumerate(panels()[group][:count]):
            if index%n!=shard:continue
            channel=("test" if repeat==0 else f"replication{repeat}") if group=="confirm" else "onpolicy"
            spec=spec_for(j,channel)
            def record(row,policy):
                stream.write(json.dumps(row|dict(family=j[3],hp=spec["hp"],max_hp=spec["max_hp"],seed=spec["seed"],policy=policy,
                    split="development" if group=="dev" else group),separators=(",",":"))+"\n");stream.flush()
            try:
                row=fight(lane,g2,spec,mode,net);lane.reset();record(row,mode)
                if mode=="v0" and group=="train" and index%2==0:
                    changed=[q["turn"] for q in row["queries"] if q["used"] and q["turn"]>=2]
                    if changed:
                        skip=changed[index%len(changed)]
                        alt=fight(lane,g2,spec,mode,net,skip);lane.reset();record(alt|dict(skip=skip),"paired")
            except (ValueError,RuntimeError,KeyError,IndexError) as e:
                lane.close();record(dict(error=repr(e),states=[],terminal=None),"error")
    lane.close();host.close();(out/"seconds.json").write_text(json.dumps(perf_counter()-start))
if __name__=="__main__":run(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3],sys.argv[4],*map(int,sys.argv[5:]))
