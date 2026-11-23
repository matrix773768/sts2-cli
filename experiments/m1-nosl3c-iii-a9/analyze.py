"""Verify A9 transactions and compare fixed evaluation slices and Actor gradients."""
from collections import Counter
import importlib.util
from pathlib import Path
import sys
from unittest.mock import patch

from weighted import A2, HERE, a3, a8, checkpoint_policy, harness, optimizer, read, save, torch, v4, weights

spec = importlib.util.spec_from_file_location("a5_analysis", HERE.parent / "m1-nosl3c-iii-a5/analyze.py")
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
a1 = harness.a1


def status_counts(outcomes):
    return Counter(item["status"] for item in outcomes)


def paired(left,right):
    result = shared.eval_metrics.compare(left,right)
    for key,items in (("baseline",left),("candidate",right)):
        counts = status_counts(items)
        result[key] = dict(statuses=counts, certified=sum(x["eligible"] for x in items),
                           wins=counts["admissible_predicted_win"], defeats=counts["admissible_death"])
    return result


def compare(out, protocol, roots):
    groups = read(out / "baseline-length-groups.json")
    objective = v4.Objective(**protocol["config"]["objective"])
    seeds = protocol["evaluation_policy_seeds"]
    result = {}
    for step in (12,36):
        before, _ = harness.load_step(A2/"training/training.sqlite",step)
        after, _ = harness.load_step(out/"training/training.sqlite",step)
        for arm in ("sample","greedy"):
            name = f"eval-{step:02d}-{arm}"
            left, a = shared.eval_metrics.evaluate(A2/name,objective,roots,seeds,before["model_sha256"],arm)
            right,b = shared.eval_metrics.evaluate(out/name,objective,roots,seeds,after["model_sha256"],arm)
            strata = {label:[item["index"] for item in entries] for label,entries in groups[name].items()}
            assert sorted(i for ids in strata.values() for i in ids)==list(range(48))
            for kind,entries in groups[name].items():
                for item in entries:
                    archived = read(A2/name/f"root-{item['index']:03d}.json")
                    assert sum(len(row["transitions"]) for row in archived["rows"]) == item["baseline_actions"]
            comparisons = {}
            for index,root in enumerate(roots):
                encounter = root["encounter"]
                category = encounter.split("_")[-1]
                for key in (f"character:{root['character']}",f"act:{root['act']}",
                            f"encounter:{encounter}",f"category:{category}"):
                    comparisons.setdefault(key,[]).append(index)
            by_slice = {key:paired([left[i] for i in ids],[right[i] for i in ids])
                        for key,ids in (strata|comparisons).items()}
            table = [dict(root=i,spec=root,baseline=left[i],candidate=right[i],
                          length_group=next(k for k,ids in strata.items() if i in ids))
                     for i,root in enumerate(roots)]
            result[name] = dict(baseline=a,candidate=b,overall=paired(left,right),
                                groups=by_slice,roots=table)
    return result


def gradient(out,cfg,step):
    pre,_,stamp,_,rows = a3.fixtures(out,step)
    policy = v4.Policy().eval()
    policy.load_state_dict(pre["model"])
    model_hash = harness.digest(checkpoint_policy(policy))
    assert model_hash == pre["model_sha256"]
    with patch.multiple(v4,optimize=optimizer(),checkpoint_policy=checkpoint_policy):
        got,raw,_ = a3.original_gradients(policy,rows,cfg,model_hash)
    historical = read(out/"training"/f"metrics-{step:02d}.json")["stats"]
    for key in ("actor_loss","critic_loss","entropy","grad_norm","logp_error","qualified","decisions"):
        assert got[key] == historical[key]
    pieces,_,_ = a3.decompose(policy,rows,cfg)
    raw_actor,returns,_ = a8.root_gradients(policy,rows,cfg)
    lengths = [len(r["transitions"]) for r in rows]
    wins = torch.tensor([r["feedback"]["status"]=="predicted_win" for r in rows])
    values = weights(lengths)
    weighted = raw_actor["v4"]*torch.tensor(values,dtype=torch.float64)[:,None]
    stats,center = a8.stats(weighted,lengths,wins)
    control,_ = a8.stats(raw_actor["v4"],lengths,wins)
    ids = list(range(len(tuple(policy.parameters()))))
    fixed = sum(a3.flat(pieces[k],ids) for k in ("critic_weighted","entropy_weighted"))
    joint = fixed+center
    residual = (joint-a3.flat(raw,ids)).norm().item()/got["grad_norm"]
    assert residual<1e-5
    return dict(snapshot=stamp, histor=historical,rms_comparison={"weighted":stats,"same_routes_unweighted":control},
                clip_factor=min(1,cfg["grad_clip"]/(joint.norm().item()+1e-6)), residual=residual,
                roots=[dict(seed=row["behavior"]["seed"],length=lengths[i],weight=values[i],
                            reward=returns[i],outcome=row["feedback"]["status"],
                            norm=weighted[i].norm().item(),unweighted_norm=raw_actor["v4"][i].norm().item())
                       for i,row in enumerate(rows)])


def check_microbatch(cfg):
    pre, _, _, _, rows = a3.fixtures(A2,12)
    policy = v4.Policy().eval()
    policy.load_state_dict(pre["model"])
    expected = [len(row["transitions"]) for row in rows]
    checked = {}
    for width in (1,4,7,24):
        observed = []

        def observe(lengths):
            observed.append(list(lengths))
            return weights(lengths)

        replay = optimizer(base_identity=True)
        with patch.dict(replay.__globals__, {"route_weights":observe}), patch.object(v4,"optimize",replay):
            a3.original_gradients(policy,rows,cfg | {"microbatch":width},pre["model_sha256"])
        assert observed == [expected]
        checked[width] = weights(observed[0])
    assert all(items == checked[4] for items in checked.values())
    return checked


def main(out):
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    protocol = read(out/"protocol.json")
    cfg = protocol["config"]
    batches,roots = harness.manifests(A2)
    assert harness.digest(batches[:36])==protocol["train_sha256"] and harness.digest(roots)==protocol["eval_sha256"]
    assert not read(out/"first-batch-gate.json")["differences"]
    metrics = shared.training(out,batches[:36])
    evaluations = compare(out,protocol,roots)
    grads = {step:gradient(out,cfg,step) for step in (1,12,36)}
    baseline = {step:read(Path("logs/nosl3c-iii-a8-01")/f"update-{step:02d}.json") for step in grads}
    snapshots = {}
    for step in (0,12,36):
        state, stamp = harness.load_step(out/"training/training.sqlite",step)
        policy = v4.Policy()
        policy.load_state_dict(state["model"])
        assert harness.digest(checkpoint_policy(policy))==state["model_sha256"]
        snapshots[step] = dict(model=state["model_sha256"],snapshot=stamp)
    exits = Counter(str(read(p)["exit_code"]) for p in out.glob("*/engine/game-*/lifecycle.json"))
    save(out/"results.json",dict(curve=metrics,evaluation=evaluations,gradients=grads,
                                 baseline_gradients=baseline,snapshots=snapshots,exits=exits,
                                 checked_microbatch_weights=check_microbatch(cfg)))


if __name__=="__main__":
    main(Path(sys.argv[1]).resolve())
