"""A9 isolated trajectory-weighted Actor, with an A2 replay gate."""
import argparse
from copy import deepcopy
from hashlib import sha256
import importlib.util
from inspect import getsource
from pathlib import Path
import sys
from textwrap import dedent
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iii-a5"))
import joint as harness

spec = importlib.util.spec_from_file_location("actor_replay", HERE.parent / "m1-nosl3c-iii-a8/diagnose.py")
a8 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a8)
a3 = a8.a3
torch, v4, A2, read, save = harness.torch, harness.v4, harness.A2, harness.read, harness.save
VERSION = v4.MODEL + ".a9-length-inverse-sqrt"
OPS = harness.OPS


def checkpoint_policy(policy):
    return OPS["checkpoint_policy"](policy) | {"version": VERSION}


def weights(lengths):
    raw = [length ** -.5 for length in lengths]
    average = sum(raw)/len(raw)
    return [weight/average for weight in raw]


def optimizer(*, unit=False, base_identity=False):
    src = dedent(getsource(harness.BASE_OPTIMIZE))
    substitutions = {
        "    optimizer.zero_grad(set_to_none=True)":
        """    batch_weights = route_weights([len(route) for route, _ in prepared])
    by_route = {id(route): weight for (route, _), weight in zip(prepared, batch_weights, strict=True)}
    optimizer.zero_grad(set_to_none=True)""",
        "actor = -(chosen * advantage).sum()":
        """weight = value.new_tensor([by_route[id(route)] for route, _ in active])
            actor = -(chosen * advantage * weight).sum()""",
    }
    for old,new in substitutions.items():
        assert src.count(old) == 1
        src = src.replace(old,new)
    scope = OPS | {"route_weights": (lambda lengths:[1.] * len(lengths)) if unit else weights}
    if not base_identity:
        scope.update(MODEL=VERSION, checkpoint_policy=checkpoint_policy)
    exec(compile(src,"<A9 v4 Actor weight adapter>","exec"),scope)
    return scope["optimize"]


def same(a,b):
    if isinstance(a,torch.Tensor):
        return a.dtype == b.dtype and a.shape == b.shape and a.flatten().view(torch.uint8).equal(b.flatten().view(torch.uint8))
    if isinstance(a,dict):
        return a.keys() == b.keys() and all(same(a[k],b[k]) for k in a)
    if isinstance(a,(tuple,list)):
        return len(a)==len(b) and all(same(x,y) for x,y in zip(a,b,strict=True))
    return a==b


def replay_check(out,cfg):
    step = 12
    before,after,stamp,_,rows = a3.fixtures(A2,step)
    params = v4.Policy().eval()
    params.load_state_dict(before["model"])
    params_hash = before["model_sha256"]
    original, raw, _ = a3.original_gradients(params, rows, cfg, params_hash)
    with patch.object(v4,"optimize",optimizer(unit=True,base_identity=True)):
        checked, replay, _ = a3.original_gradients(params,rows,cfg,params_hash)
    assert original == checked and same(raw,replay)
    adam = torch.optim.Adam(params.parameters(),lr=cfg["learning_rate"])
    adam.load_state_dict(deepcopy(before["adam"]))
    optimizer(unit=True,base_identity=True)(params,adam,rows,cfg,params_hash)
    assert same(after["model"],params.state_dict()) and same(after["adam"],adam.state_dict())
    params.load_state_dict(before["model"])
    lengths = [len(row["transitions"]) for row in rows]
    values = weights(lengths)
    assert abs(sum(values)/len(values)-1) < 1e-12
    pieces, scalars, _ = a3.decompose(params,rows,cfg)
    vectors,_,_ = a8.root_gradients(params,rows,cfg)
    index = list(range(len(tuple(params.parameters()))))
    fixed = sum(a3.flat(pieces[key],index) for key in ("critic_weighted","entropy_weighted"))
    weighted = (vectors["v4"]*torch.tensor(values,dtype=torch.float64)[:,None]).mean(0)
    with patch.object(v4,"optimize",optimizer(base_identity=True)):
        candidate,full,_ = a3.original_gradients(params,rows,cfg,params_hash)
    residual = (a3.flat(full,index)-weighted-fixed).norm().item()/candidate["grad_norm"]
    assert residual < 1e-5
    assert all(candidate[key]==scalars[key] for key in ("critic_loss","entropy"))
    for micro in (1,4,7,24):
        blocks = [values[i:i+micro] for i in range(0,len(values),micro)]
        assert [value for block in blocks for value in block] == values
    save(out/"offline-check.json",dict(update=step,snapshot=stamp,lengths=lengths,weights=values,
                  unit_gradient_exact=True,unit_model_and_adam_exact=True,weighted_relative_residual=residual,
                  original_actor=original["actor_loss"],weighted_actor=candidate["actor_loss"],
                  critic=candidate["critic_loss"],entropy=candidate["entropy"],microbatch_partitions=[1,4,7,24]))
    print("Offline unit-weight replay and weighted gradient verified",flush=True)


def freeze_groups(out):
    groups = {}
    for step in (12,36):
        for mode in ("sample","greedy"):
            name = f"eval-{step:02d}-{mode}"
            records = [read(A2/name/f"root-{i:03d}.json") for i in range(48)]
            lengths = [sum(len(row["transitions"]) for row in r["rows"]) for r in records]
            ranked = sorted(range(48),key=lambda i:(lengths[i],i))
            groups[name] = {key:[dict(index=i,baseline_actions=lengths[i]) for i in ranked[start:start+16]]
                            for key,start in (("short",0),("middle",16),("long",32))}
    save(out/"baseline-length-groups.json",groups)


def before_training(out,cfg):
    freeze_groups(out)
    replay_check(out,cfg)


def main(out):
    intervention = {"a9":dict(model=VERSION, exponent=-.5, batch_normalization="mean",
                              adapter_sha256=sha256(Path(__file__).read_bytes()).hexdigest())}
    with patch.multiple(harness,VERSION=VERSION,SCALE=1,Policy=harness.BASE,
                        checkpoint_policy=checkpoint_policy,candidate_optimize=optimizer):
        harness.main(out,intervention=intervention,before_training=before_training)


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out",type=Path)
    main(parser.parse_args().out.resolve())
