"""Family-paired analysis; missing terminal outcomes stay censored."""
from fit import *
from itertools import combinations
from statistics import mean
from collections import defaultdict

def interval(values):
    if not values:return dict(n=0)
    a=np.array(values)
    rng=np.random.default_rng(351)
    bounds=np.quantile(rng.choice(a,(10000,len(a))).mean(1),[.025,.975])
    return dict(n=len(a),mean=float(a.mean()),interval=bounds.tolist(),positive=int((a>0).sum()),negative=int((a<0).sum()))

def score_all(out):
    t=perf_counter()
    fights=[json.loads(l) for f in sorted(out.glob("fights*.gz")) for l in gzip.open(f)]
    metrics=read(out/"fit.json");net=network("mechanism")
    net.load_state_dict(torch.load(out/"mechanism.pt",weights_only=True));net.eval()
    torch.set_num_threads(1)
    def pairs(split):
        return [(s,r) for r in fights if r["split"]==split and r.get("terminal") for s in r["states"]]
    def labels(p):
        return targets(torch.tensor([c["hp"] for c,r in p]),torch.tensor([r["terminal"]["hp"] for c,r in p]),torch.tensor([r["status"]=="death" for c,r in p]))
    dev=pairs("development");y=labels(dev);abl={}
    with torch.no_grad():
        for mask in (None,"enemy","cards","player"):
            logits=net(torch.from_numpy(np.stack([features(c,"mechanism",mask) for c,r in dev])))
            abl[str(mask)]=summarize(logits,y)
    prior=(labels(pairs("train")).bincount(minlength=1+len(CENTERS))+.5)
    prior/=prior.sum()
    conf=labels(pairs("confirmation"))
    report=dict(ablation=abl,prior_confirmation=summarize(prior.log().expand(len(conf),-1),conf),
        labeled={k:len(pairs(k)) for k in ("train","development","confirmation")})
    differences=defaultdict(list);per=[];agreement=[];margins=[]
    for path in sorted(out.glob("*audit*.gz")):
        audit=json.load(gzip.open(path))
        for row in audit["rows"]:
            if "error" in row:per.append(dict(family=row["family"],error=row["error"]));continue
            block=row["blocks"];names=row["actions"];did=len(names)>1
            def means(worlds):
                valid=[w for w in worlds if all(w["outcomes"][k]["utility"] is not None for k in names)]
                return {k:mean(w["outcomes"][k]["utility"] for w in valid) for k in names} if valid else {}
            if "reference" in block:
                a,b=means(block["selection"]),means(block["reference"])
                if not a or not b:continue
                teacher=max(names,key=a.get)
                differences["teacher"].append(b[teacher]-b["G2"])
                pred={str(k):v for k,c,v in row["options"] if c>=1-1e-9}
                hits=[int((pred[k]-pred[j])*(b[k]-b[j])>0) for k,j in combinations(names[1:],2) if b[k]!=b[j] and pred[k]!=pred[j]]
                agreement.extend(hits)
                diff=b[names[1] if did else "G2"]-b["G2"]
                differences["dev_model"].append(diff)
                margins.append(max(b.values())-b["G2"])
                per.append(dict(family=row["family"],split="development",selection=a,reference=b,chosen=teacher,model_delta=diff))
            else:
                b=means(block["deployment"])
                if not b:continue
                diff=b[names[1] if did else "G2"]-b["G2"]
                differences["confirmation_model"].append(diff)
                per.append(dict(family=row["family"],split="confirmation",values=b,model_delta=diff))
    full=read(out/"deploy.json");by_id={r["ordinal"]:r for r in fights};wins=Counter()
    for r in full["rows"]:
        base=by_id[r["ordinal"]]
        if r.get("utility") is None or not base.get("terminal"):continue
        spec=next(j[1] for split,j in jobs() if j[0]==r["ordinal"])
        base_u=-50 if base["status"]=="death" else payoff(torch.tensor(spec["hp"]-base["terminal"]["hp"]),torch.tensor(spec["max_hp"])).item()
        differences["full_deployment"].append(r["utility"]-base_u)
        wins.update(["model_"+r["status"],"G2_"+base["status"]])
    report.update(results={k:interval(v) for k,v in differences.items()},rank_agreement=[sum(agreement),len(agreement)],
                  hindsight_margin=interval(margins),families=per,full_wins=wins,seconds=perf_counter()-t)
    (out/"results.json").write_text(json.dumps(report,indent=2))
if __name__=="__main__":score_all(Path(sys.argv[1]))
