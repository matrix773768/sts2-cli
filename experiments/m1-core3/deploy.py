"""Repeated public turn intervention with the same frozen search settings as one-turn deployment."""
from paired import *

def run(out,fit,offset,count):
    out.mkdir(parents=True,exist_ok=False);start=perf_counter()
    arm=read(fit/"fit.json")["selected"];net=network(arm)
    net.load_state_dict(torch.load(fit/(arm+".pt"),weights_only=True));net.eval()
    host,model=setup(out);lane=Lane(host,0);rows=[]
    selected={}
    for group,j in jobs():
        if group=="confirmation":selected.setdefault(j[3],j)
    for j in list(selected.values())[offset:offset+count]:
        r=dict(family=j[3],ordinal=j[0],fallback=0,queries=0,calls=0,seconds_search=0.,events=Counter())
        rows.append(r)
        try:
            st=cohort.start(lane,j[1]);hist=[]
            while st["status"]=="active" and st["actions"]<128:
                h=host.project(st["observation"]);prior=st["actions"]
                if h["decision"]["phase"]=="combat":
                    begin=perf_counter();g,ch,ops,stats=compile_turn(lane,h,hist,net,arm)
                    r["queries"]+=1;r["calls"]+=stats["calls"];r["seconds_search"]+=perf_counter()-begin
                    if ops and ops[0][1]>=1-1e-9:
                        st,trace,reason=execute(lane,st,g,ch,ops[0][0]);hist.extend(trace);r["events"][reason]+=1
                if prior==st["actions"]:
                    c=prepared(model,h,hist);c.project=host.project
                    a,_,_=c.act(h,lane,prior);hist.append((h,a));st=step(lane,st,a);r["fallback"]+=1
            t=st.get("terminal_observation");r.update(status=st["status"],actions=st["actions"],terminal=t,
                utility=terminal("death" if st["status"]=="death" else "victory",t,j[1]) if t and st["status"] in ("death","predicted_win") else None)
            lane.reset()
        except (KeyError,IndexError,ValueError,RuntimeError) as e:r["error"]=repr(e);lane.close()
        (out/"deploy.json").write_text(json.dumps(dict(rows=rows,seconds=perf_counter()-start)))
    lane.close();host.close()
if __name__=="__main__":run(Path(sys.argv[1]),Path(sys.argv[2]),int(sys.argv[3]),int(sys.argv[4]))
