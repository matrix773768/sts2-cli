"""Descriptive probes on public CORE-2 interventions and already frozen deployed failures."""
from turn_value import *
from collections import Counter

def run(out,logs):
    logs.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(HERE.parent/"m1-core1"))
    from compare import episode,check
    start=perf_counter();torch.set_num_threads(1)
    models={}
    for arm in ("simple","mechanism"):
        net=network(arm);net.load_state_dict(torch.load(out/(arm+".pt"),weights_only=True));net.eval();models[arm]=net
    fx=json.load(gzip.open(HERE.parent/"m1-core2/evidence/diagnostics.json.gz"))["rows"]
    probes={}
    for k in ("persistent","growth","strike","headbutt"):
        cs=[x["C"] for x in fx[k] if x["C"]]
        probes[k]={arm:predict(net,arm,cs,dict(hp=80,max_hp=80)) for arm,net in models.items()}
    fails=[];host,g2=setup(logs);lane=Lane(host,0)
    from design import runtime
    histories=[]
    arm=read(out/"fit.json")["selected"]
    fights={r["ordinal"]:r for f in out.glob("fights*.gz") for line in gzip.open(f)for r in [json.loads(line)]}
    specs={j[0]:j[1] for _,j in jobs()}
    for row in read(out/"deploy.json")["rows"]:
        if row.get("status")!="death" or fights[row["ordinal"]]["status"]!="predicted_win":continue
        spec=specs[row["ordinal"]];st=cohort.start(lane,spec);hist=[];trace=[]
        while st["status"]=="active" and st["actions"]<128:
            h=host.project(st["observation"]);before=st["actions"]
            if h["decision"]["phase"]=="combat":
                g,ch,ops,stats=compile_turn(lane,h,hist,models[arm],arm)
                if ops and ops[0][1]>=1-1e-9:
                    st,played,reason=execute(lane,st,g,ch,ops[0][0]);hist.extend(played)
                    trace.append(dict(turn=h["turn"],hp=h["hp"],first=ops[0][0],estimate=ops[0][2],
                                      options=len(ops),steps=len(played),reason=reason))
            if before==st["actions"]:
                c=prepared(g2,h,hist);c.project=host.project
                a,_,_=c.act(h,lane,before);hist.append((h,a));st=step(lane,st,a)
        fails.append(dict(ordinal=row["ordinal"],encounter=spec["encounter"],terminal=st["status"],trace=trace))
        histories.append((spec,hist))
        lane.reset()
    lane.close();host.close()
    native_host,native_model=runtime(logs)
    for record,(spec,hist) in zip(fails,histories):
        audits={}
        for label,forced in (("search",[({k:v for k,v in o.items() if k not in ("order_hooks","tuning_fork")},a) for o,a in hist]),("G2",[])):
            left,right=Lane(native_host,1),Lane(native_host,2)
            try:
                ref=episode(native_host,native_model,dict(spec=spec),0,forced,True)
                left.open();right.open()
                audits[label]=check(left,right,[record["ordinal"],spec],ref,native_host.runtime["targets"].project)
            except (ValueError,RuntimeError,KeyError,AssertionError) as err:audits[label]=dict(error=repr(err))
            finally:left.close();right.close()
        record["native"]=audits
    native_host.close()
    return dict(probes=probes,failures=fails,seconds=perf_counter()-start)
if __name__=="__main__":
    out=Path(sys.argv[1]);(out/"diagnostics.json").write_text(json.dumps(run(out,Path(sys.argv[2])),indent=2))
