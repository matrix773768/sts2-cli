"""Independent conditional-world check on the fixed public opening and identical V2 suffix."""
import sys,json,gzip
from time import perf_counter
from panel5d import E,OUT,load,digest,cohort
from battle5d import configure
from options5d import menu,pair
from experience5d import realize
from deploy5b import Lane
def run(shard,n,reference_probe=0):
    start=perf_counter();tag=("reference" if reference_probe else "teacher")+f"-{shard}";out=OUT/tag;out.mkdir(parents=True,exist_ok=True)
    host,g2,net,plan=configure(out,"V2");lane=Lane(host,0)
    data=[]
    panel=load(E/"augmentation.gz")["dev2"] if reference_probe else load(E/"panel.gz")["dev"]
    for i,w in enumerate(panel):
        if i%n!=shard:continue
        s=w["spec"];case=dict(i=i,family=w["family"],worlds=[])
        data.append(case)
        try:
            st=cohort.start(lane,s);h=host.project(st["observation"]);law=st["public_law"]
            opts,states,main,q=menu(lane,h,[],net,g2,s,plan)
            if reference_probe and not q["use"]:
                case["same_deployed"]=True;lane.reset();continue
            # The comparator is the actual deployed teacher, including the frozen reference gate.
            if not any(o.label==main for o in opts) or len(opts)<2:
                case["skip"]="no complete deployed comparison";lane.reset();continue
            if reference_probe:
                selected=[o for o in opts if o.label in (main,"G2")]
                if len(selected)!=2:
                    case["skip"]="equivalent or absent reference law";lane.reset();continue
            else:selected=pair(opts,states,main,False)
            selected=sorted(selected,key=lambda o:o.label!=main)
            assert selected[0].label==main
            case.update(labels=[o.label for o in selected],scores=[o.value for o in selected],intervened=q["use"])
            lane.reset()
            if law.get("top") or law.get("bottom") or law.get("order_gap") or law.get("membership_gap"):
                case["skip"]="opening not exchangeable";continue
            for world in range(4):
                identity=["5d-ref",s["seed"]] if reference_probe else ["5d-teacher",w["family"]]
                order=cohort.permutation(s["deck"],h["hand"],digest(identity+[world]))
                outcomes=[]
                for opt in selected:
                    state=cohort.start(lane,s,order)
                    if host.project(state["observation"])!=h or state["public_law"]!=law:
                        outcomes.append(dict(status="opening_changed"))
                    else:outcomes.append(realize(opt,lane,state,[],s,g2,net,plan))
                    lane.reset()
                case["worlds"].append(dict(order=order,outcomes=outcomes))
        except (ValueError,RuntimeError,KeyError,IndexError) as error:
            lane.close();case["error"]=repr(error)
    lane.close();host.close()
    with gzip.open(E/(tag+".gz"),"xt") as f:json.dump(data,f)
    (E/(tag+".time.json")).write_text(json.dumps(perf_counter()-start))
if __name__=="__main__":run(*map(int,sys.argv[1:]))
