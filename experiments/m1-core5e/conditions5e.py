"""Offline paired rollouts on a public midcombat root. Policies never receive resampling seeds."""
import gzip,json,sys
from time import perf_counter
from panel5e import D,E,OUT,WORLD,load,rows,digest
from battle5d import configure
from deploy5b import host_at,Lane
from experience5d import restore,realize
from options5d import menu,pair

def natural_rows(panel):
    records={}
    for source in {w["source"] for w in panel}:
        for path in D.glob(source+"-V2-*.gz"):
            for r in rows(path):records[source,r["i"]]=r
    return records

def choose_root(lane,g2,net,planner,w,r,index):
    spec=w["spec"];target=3+index%5
    queries=sorted(r["queries"],key=lambda q:(q["turn"]<2,q["coverage"]<.999999,
                   not -46<q["value"]<88,abs(q["turn"]-target)))
    skips=[]
    for q in queries[:5]:
        turn=q["turn"];st,past=restore(lane,spec,r["trace"],turn)
        h=lane.host.project(st["observation"]);law=st["public_law"]
        if len(law["counts"])<2 or any(law.get(k) for k in ("top","bottom","order_gap","membership_gap")):
            skips.append("nonexchangeable or deterministic");lane.reset();continue
        opts,states,main,comparison=menu(lane,h,past,net,g2,spec,planner)
        lane.reset()
        # Concentrate on plausible competing turns while retaining a comparison if the value model separates them.
        plausible=[o for o in opts if o.value>=max(x.value for x in opts)-35 or o.label==main]
        selected=pair(plausible if len(plausible)>=2 else opts,states,main,index%3==0)
        if selected is None:
            skips.append("no distinct complete policies");continue
        needed={key for opt in selected for kind,key,_,_ in opt.law if kind=="C"}
        return (h,law,turn,selected,{k:states[k] for k in needed},main,comparison),skips
    return None,skips

def followup():
    from statistics import variance
    from data5e import read_cases,completed,deltas
    cases=[r for r in read_cases("train") if completed(r)]
    noisy=sorted((r for r in cases if variance(deltas(r))>0),key=lambda r:-variance(deltas(r)))[:12]
    zeros=sorted((r for r in cases if not any(deltas(r))),key=lambda r:digest(["5e-zero-audit",r["family"]]))[:4]
    return {r["i"]:r for r in noisy+zeros}

def run(split,shard,n,audit=0):
    start=perf_counter();tag=("audit12" if audit else "worlds")+f"-{split}-{shard}"
    out=OUT/tag;out.mkdir(parents=True,exist_ok=True)
    old,g2,net,plan=configure(out,"V2");old.close()
    host=host_at(out,WORLD);lane=Lane(host,0)
    panel=load(E/"panel.gz")[split];natural=natural_rows(panel)
    selected_cases=followup() if audit else None
    with gzip.open(E/(tag+".gz"),"xt",compresslevel=4) as f:
        for i in range(shard,len(panel),n):
            if audit and i not in selected_cases:continue
            w=panel[i];s=w["spec"];r=natural[w["source"],w["index"]]
            case=dict(i=i,family=w["family"],seed=s["seed"],source=w["source"],index=w["index"],
                      hp=s["hp"],max_hp=s["max_hp"],continuation="5C-V2-high",worlds=[])
            try:
                chosen,case["skips"]=choose_root(lane,g2,net,plan,w,r,i)
                if chosen:
                    h,law,turn,selected,states,main,q=chosen
                    count=8 if split=="dev" or (i%4==0 and turn>=3) else 4
                    case.update(turn=turn,law=law,public=digest(h),states=states,world_count=count,
                                intervened=q["use"],main=main,same_first=selected[0].first==selected[1].first,
                                plans=[dict(label=o.label,first=o.first,v2=o.value,law=o.law) for o in selected])
                    if audit:
                        prior=selected_cases[i]
                        # JSON reload turns tuples into lists. Identity depends on the
                        # public program and its full law, independent of inference batch rounding.
                        signature=lambda plans:json.dumps([(p["label"],p["first"],p["law"]) for p in plans],sort_keys=True)
                        if case["public"]!=prior["public"] or signature(case["plans"])!=signature(prior["plans"]):
                            raise ValueError("Audited root or selected policy changed")
                        count=12;case["world_count"]=count
                    for j in range(count):
                        seed=int(digest(["5e-audit" if audit else "5e-estimate",split,w["family"],s["seed"],turn,j])[:7],16)
                        if audit:assert seed not in {v["seed"] for v in prior["worlds"]}
                        world=dict(seed=seed,outcomes=[]);case["worlds"].append(world)
                        for opt in selected:
                            st,past=restore(lane,s,r["trace"],turn)
                            sampled=lane.request("i1_core5_reference",diagnostic_world=seed)["response"]
                            if host.project(sampled["state"])!=h or sampled["law"]!=law:
                                raise ValueError("Conditioning changed public observation or law")
                            result=realize(opt,lane,st,past,s,g2,net,plan)
                            world["outcomes"].append(result);lane.reset()
            except (ValueError,RuntimeError,KeyError,IndexError) as error:
                case["error"]=repr(error);lane.close()
            f.write(json.dumps(case,separators=(",",":"))+"\n");f.flush()
    lane.close();host.close()
    (E/(tag+".time.json")).write_text(json.dumps(perf_counter()-start))
if __name__=="__main__":run(sys.argv[1],*map(int,sys.argv[2:]))
