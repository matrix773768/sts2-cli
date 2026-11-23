"""Read-only root-level Actor gradient diagnostics for frozen A2 batches."""
import argparse
import importlib.util
import json
from pathlib import Path
from statistics import mean, median
from time import perf_counter

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("a3", HERE.parent / "m1-nosl3c-iii-a3/analyze.py")
a3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a3)
torch, v4, read, save = a3.torch, a3.v4, a3.read, a3.save
OPS = a3.TRAINING
STEPS = (1, 6, 12, 24, 36, 48, 60, 72, 84)
ARMS = ("zero", "v4", "leave_one_out")


def root_gradients(policy, rows, cfg):
    objective = v4.Objective(**cfg["objective"])
    params = tuple(policy.parameters())
    rewards = [objective.reward(row["feedback"], row["hp_accounting"]["initial_hp"]) for row in rows]
    assert all(value is not None for value in rewards) and len(rewards) > 1
    others = [mean(value for j, value in enumerate(rewards) if i != j)
              for i in range(len(rewards))]
    result = {}
    for start in range(0, len(rows), cfg["microbatch"]):
        group = sorted(range(start, min(start+cfg["microbatch"],len(rows))),
                       key=lambda i: -len(rows[i]["transitions"]))
        history = torch.zeros(len(group), OPS["WIDTH"])
        scores = {i: [] for i in group}
        v4_terms = {i: [] for i in group}
        for t in range(len(rows[group[0]]["transitions"])):
            active = [i for i in group if t < len(rows[i]["transitions"])]
            steps = [rows[i]["transitions"][t] for i in active]
            decisions = [OPS["decision"](json.dumps(step["observation"], sort_keys=True)) for step in steps]
            chosen = torch.tensor([step["action"]["index"] for step in steps])
            logits, value, state, actions, _ = OPS["forward"](policy, decisions, history[:len(active)])
            positions = torch.arange(len(active))
            logp = logits.log_softmax(-1)[positions,chosen]
            advantage = value.new_tensor([rewards[i] for i in active])-value.detach()
            for j,i in enumerate(active):
                scores[i].append(-logp[j])
                v4_terms[i].append(-logp[j]*advantage[j])
            history = policy.history(torch.cat((state,actions[positions,chosen]),dim=1), history[:len(active)])

        def flatten(loss, retain):
            grad = torch.autograd.grad(loss, params, retain_graph=retain, allow_unused=True)
            return torch.cat([(torch.zeros_like(p) if g is None else g).reshape(-1).double()
                              for p,g in zip(params,grad,strict=True)])

        for j,i in enumerate(group):
            score = flatten(torch.stack(scores[i]).sum(), True)
            current = flatten(torch.stack(v4_terms[i]).sum(), j < len(group)-1)
            result[i] = dict(zero=rewards[i]*score, v4=current,
                             leave_one_out=(rewards[i]-others[i])*score)
    return {name:torch.stack([result[i][name] for i in range(len(rows))]) for name in ARMS}, rewards, others


def norm(v):
    return v.norm().item()


def cosine(a,b):
    denominator = norm(a)*norm(b)
    return torch.dot(a,b).item()/denominator if denominator else None


def rank(values):
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = torch.empty(len(values),dtype=torch.float64)
    start = 0
    while start < len(order):
        end = start+1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = (start+end-1)/2
        start = end
    return ranks-ranks.mean()


def stats(matrix, lengths, wins):
    center = matrix.mean(0)
    root_norms = matrix.norm(dim=1).tolist()
    dispersion = (matrix-center).square().sum(1).mean().sqrt().item()
    length_order = sorted(range(len(lengths)),key=lengths.__getitem__)
    quartile = max(1,len(length_order)//4)
    outcomes = {}
    for key,mask in (("win",wins),("death",~wins)):
        part = matrix[mask].sum(0)/len(matrix)
        outcomes[key] = dict(n=int(mask.sum()), norm=norm(part), cosine_to_batch=cosine(part,center),
                             projection_share=torch.dot(part,center).item()/norm(center)**2 if norm(center) else None,
                             root_norm_mean=matrix[mask].norm(dim=1).mean().item() if mask.any() else None)
    return dict(root_norm_mean=mean(root_norms), batch_norm=norm(center), rms_dispersion=dispersion,
                snr_proxy=norm(center)/dispersion,
                spearman_length=cosine(rank(lengths),rank(root_norms)),
                short_norm_mean=mean(root_norms[i] for i in length_order[:quartile]),
                long_norm_mean=mean(root_norms[i] for i in length_order[-quartile:]),
                outcomes=outcomes), center


def measure(source, step, cfg):
    payload, _, stamp, _, rows = a3.fixtures(source,step)
    policy = v4.Policy().eval()
    policy.load_state_dict(payload["model"])
    model_hash = a3.digest(v4.checkpoint_policy(policy))
    assert model_hash == payload["model_sha256"]
    historical = read(source / "training" / f"metrics-{step:02d}.json")["stats"]
    original, raw, _ = a3.original_gradients(policy,rows,cfg,model_hash)
    for key in ("grad_norm","actor_loss","critic_loss","entropy","logp_error","qualified","decisions"):
        assert original[key] == historical[key]
    components,_,_ = a3.decompose(policy,rows,cfg)
    matrix, rewards, baselines = root_gradients(policy,rows,cfg)
    names = [name for name,_ in policy.named_parameters()]
    sizes = [p.numel() for p in policy.parameters()]
    full = list(range(len(names)))
    official = a3.flat(raw,full)
    actor = a3.flat(components["actor"],full)
    fixed = sum(a3.flat(components[key],full) for key in ("critic_weighted","entropy_weighted"))
    reconstruction = norm(matrix["v4"].mean(0)-actor)/norm(actor)
    joint_error = norm(matrix["v4"].mean(0)+fixed-official)/norm(official)
    assert reconstruction < 1e-5 and joint_error < 1e-5
    spaces = {
        "actor_head": [i for i,n in enumerate(names) if n.startswith("actor.")],
        "shared": [i for i,n in enumerate(names) if not n.startswith(("actor.","return_head.","relation."))],
    }
    column_ranges = []
    offset = 0
    for size in sizes:
        column_ranges.append(slice(offset,offset+size))
        offset += size
    lengths = [len(row["transitions"]) for row in rows]
    wins = torch.tensor([row["feedback"]["status"]=="predicted_win" for row in rows])
    detail = [dict(seed=row["behavior"]["seed"], outcome=row["feedback"]["status"], length=length,
                   reward=rewards[i], leave_one_out_baseline=baselines[i], gradients={})
              for i,(row,length) in enumerate(zip(rows,lengths,strict=True))]
    results = {}
    current = matrix["v4"].mean(0)
    for name,vectors in matrix.items():
        report,center = stats(vectors,lengths,wins)
        joint = center+fixed
        clip = min(1,cfg["grad_clip"]/(norm(joint)+1e-6))
        subspaces = {}
        for key,group in spaces.items():
            sliced = torch.cat([vectors[:,column_ranges[i]] for i in group],dim=1)
            subspaces[key], _ = stats(sliced,lengths,wins)
        report.update(subspaces=subspaces,
                      cosine_actor_to_v4=cosine(center,current), cosine_joint_to_v4=cosine(joint,official),
                      joint_norm=norm(joint), clip_factor=clip, clipped_joint_norm=norm(joint)*clip,
                      clipped_actor_norm=norm(center)*clip)
        results[name] = report
        for i,row in enumerate(detail):
            vector = vectors[i]
            row["gradients"][name] = dict(norm=norm(vector), cosine_to_batch=cosine(vector,center),
                                          cosine_to_root_v4=cosine(vector,matrix["v4"][i]))
    assert a3.digest(v4.checkpoint_policy(policy)) == model_hash
    return dict(update=step, model=model_hash, snapshot=stamp, historical=historical,
                actor_residual=reconstruction, joint_residual=joint_error, roots=detail, arms=results)


def summarize(records):
    current = [r["arms"]["v4"] for r in records]
    return {name:dict(
        median_dispersion_ratio_to_v4=median(r["arms"][name]["rms_dispersion"]/v["rms_dispersion"]
                                           for r,v in zip(records,current,strict=True)),
        median_snr=median(r["arms"][name]["snr_proxy"] for r in records),
        median_length_spearman=median(r["arms"][name]["spearman_length"] for r in records),
        median_long_short_ratio=median(r["arms"][name]["long_norm_mean"]/r["arms"][name]["short_norm_mean"]
                                       for r in records),
        median_death_projection=median(r["arms"][name]["outcomes"]["death"]["projection_share"] for r in records),
        median_cosine_to_v4=median(r["arms"][name]["cosine_actor_to_v4"] for r in records),
    ) for name in ARMS}


def main(source,out):
    out.mkdir(parents=True)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    cfg = read(source/"protocol.json")["config"]
    save(out/"protocol.json",dict(updates=STEPS,objective=cfg["objective"],clip=cfg["grad_clip"],
                                  microbatch=cfg["microbatch"],arms=ARMS))
    records = []
    for step in STEPS:
        start = perf_counter()
        records.append(measure(source,step,cfg))
        save(out/f"update-{step:02d}.json",records[-1])
        print(f"Verified update {step} ({perf_counter()-start:.1f} s)",flush=True)
    save(out/"summary.json",summarize(records))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path)
    parser.add_argument("out",type=Path)
    args = parser.parse_args()
    main(args.source,args.out)
