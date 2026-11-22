"""Compare frozen decomposed value estimates against direct regression."""
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("a6", HERE.parent / "m1-nosl3c-iii-a6/diagnose.py")
a6 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a6)
torch, nn, a4 = a6.torch, a6.nn, a6.a4
read, save, digest = a6.read, a6.save, a6.digest
SCALE = 100
BOOTSTRAPS = 2000
BOOT_SEED = 73192701


def estimate_offset(logits, labels):
    """Fit a single log-odds intercept by validation likelihood."""
    lo, hi = -20., 20.
    target = labels.mean().item()
    for _ in range(50):
        mid = (lo+hi)/2
        if (logits+mid).sigmoid().mean().item() < target:
            lo = mid
        else:
            hi = mid
    return (lo+hi)/2


def fit(x, target, kind):
    torch.manual_seed(a6.SEED)
    model = (nn.Sequential(nn.Linear(x.shape[1], 8), nn.Tanh(), nn.Linear(8, 1))
             if kind == "mlp" else nn.Linear(x.shape[1],1))
    opt = torch.optim.Adam(model.parameters(), lr=a6.LR)
    for _ in range(a6.PROBE_STEPS):
        predicted = model(x).flatten()
        error = ((predicted-target/SCALE).square().mean() if kind == "direct_mse" else
                 nn.functional.binary_cross_entropy_with_logits(predicted,target))
        loss = error + a6.L2/2*sum(p.square().sum() for p in model.parameters() if p.ndim > 1)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
    return model


def metrics(p, value, y, target):
    e = value-target
    result = dict(n=len(y), wins=int(y.sum()), mean_value=value.mean().item(),
                  actual_mean=target.mean().item(), bias=e.mean().item(), mae=e.abs().mean().item(),
                  rmse=e.square().mean().sqrt().item())
    if p is not None:
        result.update(a6.score(p,y.bool(),.5), probability_bias=(p-y).mean().item())
    if y.unique().numel() == 2:
        result["outcomes"] = {name: metrics(None,value[mask],y[mask],target[mask])
                              for name,mask in (("win",y.bool()),("death",~y.bool()))}
    return result


def paired(value, comparator, p, constant, y, target):
    generator = torch.Generator().manual_seed(BOOT_SEED)
    ids = torch.randint(len(y),(BOOTSTRAPS,len(y)),generator=generator)
    e, b = value-target, comparator-target
    diffs = dict(mae=(e.abs()[ids]-b.abs()[ids]).mean(1),
                 rmse=e.square()[ids].mean(1).sqrt()-b.square()[ids].mean(1).sqrt())
    if p is not None:
        diffs["brier"] = ((p-y).square()[ids]-(constant-y).square()[ids]).mean(1)
    return {k: torch.quantile(v,torch.tensor([.025,.975])).tolist() for k,v in diffs.items()}


def evaluate(groups, cache, index):
    x,y,returns = {},{},{}
    for name,rows in groups.items():
        x[name] = torch.stack([cache[r["key"]][index] for r in rows])
        y[name] = torch.tensor([float(r["outcome"]=="predicted_win") for r in rows])
        returns[name] = torch.tensor([r["reward"] for r in rows])
    center, spread = x["fit"].mean(0),x["fit"].std(0,unbiased=False).clamp_min(1e-6)
    x = {k:(v-center)/spread for k,v in x.items()}
    win = y["fit"].bool()
    hi,lo = returns["fit"][win].mean(),returns["fit"][~win].mean()
    prevalence,mean = y["fit"].mean(),returns["fit"].mean()
    models = {k:fit(x["fit"],returns["fit"] if k=="direct_mse" else y["fit"],k)
              for k in ("direct_mse","logistic","mlp")}
    with torch.no_grad():
        logits = {k:{g:m(features).flatten() for g,features in x.items()} for k,m in models.items()}
    offsets = {k:estimate_offset(logits[k]["validation"],y["validation"]) for k in ("logistic","mlp")}
    # Fix the selection before scoring any time-test outcomes.
    validation = {}
    for k,offset in offsets.items():
        for method,delta in (("raw",0.),("intercept",offset)):
            p = (logits[k]["validation"]+delta).sigmoid()
            validation[k+"_"+method] = (p-y["validation"]).square().mean().item()
    selected = min(validation,key=validation.get)
    all_metrics,predictions = {},{}
    for group,rows in groups.items():
        labels,target = y[group],returns[group]
        constant = torch.full_like(target,prevalence)
        average = torch.full_like(target,mean)
        direct = SCALE*logits["direct_mse"][group]
        options = {"mean":(constant,average), "direct_mse":(None,direct)}
        for k,offset in offsets.items():
            for method,delta in (("raw",0.),("intercept",offset)):
                p = (logits[k][group]+delta).sigmoid()
                options[k+"_"+method] = (p,p*hi+(1-p)*lo)
        summaries = {k:metrics(p,v,labels,target) for k,(p,v) in options.items()}
        if group=="time_test":
            for k,(p,v) in options.items():
                if k=="mean":
                    continue
                summaries[k]["paired_95_vs_mean"] = paired(v,average,p,constant,labels,target)
                if k!="direct_mse":
                    summaries[k]["paired_95_vs_direct"] = paired(v,direct,None,constant,labels,target)
                summaries[k]["slices"] = {}
                for field in ("character","act","stage"):
                    for level in sorted({r[field] for r in rows}):
                        mask = torch.tensor([r[field]==level for r in rows])
                        part = metrics(p[mask] if p is not None else None,v[mask],labels[mask],target[mask])
                        base = metrics(constant[mask],average[mask],labels[mask],target[mask])
                        summaries[k]["slices"][f"{field}:{level}"] = part | {
                            "mean_baseline_rmse":base["rmse"],"constant_brier":base["brier"]}
        all_metrics[group] = summaries
        predictions[group] = {r["key"]:dict(actual=float(target[i]),win=bool(labels[i]),
                                            arms={k:dict(value=float(v[i]),p_win=float(p[i]) if p is not None else None)
                                                  for k,(p,v) in options.items()})
                              for i,r in enumerate(rows)}
    states = {k:{n:v.detach().tolist() for n,v in model.state_dict().items()} for k,model in models.items()}
    return dict(selected=selected, validation_brier=validation, offsets=offsets,
                fit_prior=float(prevalence), fit_win_return=float(hi),fit_death_return=float(lo),
                metrics=all_metrics,predictions=predictions,weights=states,
                feature_center=center.tolist(),feature_scale=spread.tolist())


def main(source,a6_output,out):
    out.mkdir(parents=True)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    old = read(a6_output / "protocol.json")
    cfg = read(source / "protocol.json")["config"]
    state,stamp = a4.load_step(source / "training/training.sqlite",36)
    policy = a4.v4.Policy().eval().requires_grad_(False)
    policy.load_state_dict(state["model"])
    assert digest(a4.v4.checkpoint_policy(policy)) == old["model_sha256"]
    assert stamp == old["snapshot_sha256"]
    records = a4.bank(source,a4.v4.Objective(**cfg["objective"]))
    groups = a6.partition(records)
    manifest = {k:[{n:v for n,v in r.items() if n not in ("route","reward")} for r in rows]
                for k,rows in groups.items()}
    assert manifest == old["splits"] and digest(manifest) == old["split_hash"]
    save(out / "protocol.json",dict(splits=manifest, split_hash=old["split_hash"],
                                    model_sha256=old["model_sha256"], snapshot_sha256=stamp,
                                    seed=a6.SEED, steps=a6.PROBE_STEPS, lr=a6.LR,l2=a6.L2,
                                    mlp_hidden=8, mse_scale=SCALE, mid_zero_based=a6.MID,
                                    bootstraps=BOOTSTRAPS, boot_seed=BOOT_SEED,
                                    calibration="validation likelihood intercept, raw vs corrected selected by validation Brier",
                                    model_selection="minimum internal validation Brier across factorized candidates"))
    cache = a4.cache(policy,[r | {"route":r["route"][:a6.MID+1]} for r in records])
    common = {k:[r for r in rows if len(cache[r["key"]])>a6.MID] for k,rows in groups.items()}
    results = {}
    for name,chosen,index in (("first",groups,0),("common_first",common,0),("mid",common,a6.MID)):
        results[name] = evaluate(chosen,cache,index)
        print(name, results[name]["selected"],flush=True)
    save(out / "results.json",results)


if __name__=="__main__":
    main(*(Path(x).resolve() for x in sys.argv[1:]))
