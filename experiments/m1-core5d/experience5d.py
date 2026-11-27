"""Execute full-turn alternatives on identical roots and resume the frozen 5C V2 policy."""
import gzip,json,sys
from time import perf_counter
from panel5d import E,OUT,load,rows,digest
from battle5d import configure
from options5d import menu,pair
from deploy5b import Lane,fight
from play_loop import cohort,step
from assessment import utility
from turn_worlds import model_key

def restore(lane,s,trace,turn,order=None):
    st=cohort.start(lane,s,order)
    past=[]
    for t,idx in trace:
        if t>=turn:break
        h=lane.host.project(st["observation"])
        if h["turn"]!=t:raise ValueError("Prefix turn changed")
        past.append((h,idx));st=step(lane,st,idx)
    return st,past

def realize(opt,lane,st,past,s,g2,net,plan,natural=None):
    root_turn=lane.host.project(st["observation"])["turn"]
    st,played,reason=opt.execute(lane,st)
    if reason not in ("end","terminal"):return dict(status="execution_gap",reason=reason)
    c=st.get("observed_c")
    key=model_key(c) if c else None
    if c:
        matched=any(k=="C" and v==key for k,v,_,_ in opt.law)
    elif st.get("terminal_observation") and st["status"] in ("death","predicted_win"):
        kind="death" if st["status"]=="death" else "victory"
        u=utility(s|dict(status=st["status"],terminal=st["terminal_observation"]))
        matched=any(k==kind and abs(v-u)<1e-4 for k,_,v,_ in opt.law)
    else:matched=False
    if natural and natural["terminal"] and [(h["turn"],i) for h,i in played]==[tuple(x) for x in natural["trace"] if x[0]==root_turn]:
        result=natural
    else:
        result=fight(lane,g2,s,"V2",net,planner=plan,resume=(st,past+played))
    t=result["terminal"];status=result["status"]
    return dict(status=status,terminal_hp=t["hp"] if t else None,realized=key,matched=matched,
                utility=utility(s|result) if t else None,reason=reason,steps=[i for _,i in played])

def sample(lane,g2,net,plan,w,natural):
    s=w["spec"];idx=natural["i"];q=natural["queries"];target=1+idx%5
    candidates=sorted(q,key=lambda v:(v["coverage"]<.999999, not -47<v["value"]<80,abs(v["turn"]-target)))
    for query in candidates[:3]:
        turn=query["turn"];st,past=restore(lane,s,natural["trace"],turn)
        h=lane.host.project(st["observation"])
        options,states,main,comparison=menu(lane,h,past,net,g2,s,plan)
        selected=pair(options,states,main,idx%2==0)
        if selected is None:
            lane.reset();continue
        outcomes=[];laws=[]
        for pos,opt in enumerate(selected):
            if pos:st,past=restore(lane,s,natural["trace"],turn)
            outcomes.append(realize(opt,lane,st,past,s,g2,net,plan,natural))
            laws.append(dict(label=opt.label,first=opt.first,v2=opt.value,law=opt.law))
            lane.reset()
        keys={key for opt in selected for k,key,v,p in opt.law if k=="C"}
        return dict(turn=turn,intervened=query["used"],main=main,menu=len(options),plans=laws,
                    states={k:states[k] for k in keys},outcomes=outcomes,
                    same_first=selected[0].first==selected[1].first)
    return dict(skip="no two distinct complete laws")

def run(group,shard,n,*,indices=None,parents=None,on_closed=None,on_record=None):
    start=perf_counter();tag=f"pairs-{group}-{shard}"
    out=OUT/tag;out.mkdir(parents=True,exist_ok=True)
    panel=load(E/("augmentation.gz" if group=="dev2" else "panel.gz"))[group];host,g2,net,plan=configure(out,"V2");lane=Lane(host,0)
    with gzip.open(E/(tag+".gz"),"xt",compresslevel=5) as f:
        files=sorted((parents or E).glob(group+"-V2-*.gz"))
        for path in files:
            for r in rows(path):
                i=r["i"]
                if indices is not None and i not in indices:continue
                if indices is None and i%n!=shard:continue
                w=panel[i]
                try:data=sample(lane,g2,net,plan,w,r) if r["terminal"] else dict(skip="unresolved parent")
                except (RuntimeError,ValueError,IndexError,KeyError) as err:
                    lane.close();data=dict(error=repr(err))
                record=dict(i=i,family=w["family"],seed=r["seed"],hp=r["hp"],max_hp=r["max_hp"],continuation="5C-V2-high",**data)
                f.write(json.dumps(record,separators=(",",":"))+"\n");f.flush()
                if on_record is not None:on_record(i)
    if on_closed is not None:on_closed(E/(tag+'.gz'))
    lane.close();host.close();(E/(tag+".time.json")).write_text(json.dumps(perf_counter()-start))
if __name__=="__main__":run(sys.argv[1],*map(int,sys.argv[2:]))
