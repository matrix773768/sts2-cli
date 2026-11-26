"""Common permitted opening-hand worlds, fixed continuation and isolated selection/reference blocks."""
from turn_value import *
from collections import Counter

def run(out,fit,split,offset,count):
    out.mkdir(parents=True,exist_ok=False)
    started=perf_counter()
    arm=read(fit/"fit.json")["selected"]
    net=network(arm);net.load_state_dict(torch.load(fit/(arm+".pt"),weights_only=True));net.eval()
    host,model=setup(out);lane=Lane(host,0)
    seen=set();families=[]
    for group,j in jobs():
        if group==split and j[3] not in seen:families.append(j);seen.add(j[3])
    rows=[];proposals=0;steps=0
    for j in families[offset:offset+count]:
        spec=j[1];family=j[3];row=dict(family=family,blocks={});rows.append(row)
        try:
            st=cohort.start(lane,spec);h=host.project(st["observation"])
            g,choices,opts,stats=compile_turn(lane,h,[],net,arm)
            row.update(search=stats,root=h,options=opts)
            supported=[a for a,c,u in opts if c>=1-1e-9]
            # Distinct first actions with full support. Include diverse predicted values for ranking tests.
            picks=list(dict.fromkeys([supported[i] for i in (0,len(supported)//2,-1)])) if supported else []
            actions=["G2"]+[str(a) for a in picks];row["actions"]=actions
            lane.reset()
            for block,need in ([("selection",2),("reference",3)] if split=="development" else [("deployment",1)]):
                records=[];row["blocks"][block]=records
                for n in range(80 if block!="deployment" else 1):
                    if block=="deployment":donor=spec;order=None
                    else:
                        donor=spec|dict(seed=cohort.seed(family,"core3-"+block,n))
                        order=cohort.permutation(spec["deck"],h["hand"],cohort.seed(family,"core3-suffix-"+block,n))
                    proposals+=1
                    st=cohort.start(lane,donor,order)
                    if host.project(st["observation"])!=h:
                        lane.reset();continue
                    record=dict(proposal=n,outcomes={});records.append(record)
                    for index,key in enumerate(actions):
                        if index:
                            st=cohort.start(lane,donor,order)
                            if host.project(st["observation"])!=h:raise ValueError("paired root drift")
                        hist=[];reason="baseline"
                        if key!="G2":st,hist,reason=execute(lane,st,g,choices,int(key))
                        boundary=st.get("observed_c") if hist and reason=="end" else None
                        r=finish(lane,model,st,hist);steps+=r["actions"]
                        utility=None if not r["terminal"] else terminal("death" if r["status"]=="death" else "victory",r["terminal"],h)
                        record["outcomes"][key]=dict(utility=utility,status=r["status"],terminal=r["terminal"],boundary=boundary,
                            actions=r["actions"],witness=[a for _,a in hist],reason=reason)
                        lane.reset()
                    if len(records)>=need:break
        except (RuntimeError,ValueError,KeyError,IndexError) as ex:row["error"]=repr(ex);lane.close()
        with gzip.open(out/"audit.gz","wt",encoding="utf8") as stream:
            json.dump(dict(rows=rows,split=split,seconds=perf_counter()-started,proposals=proposals,steps=steps),stream,separators=(",",":"))
    lane.close();host.close()
if __name__=="__main__":run(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3],int(sys.argv[4]),int(sys.argv[5]))
