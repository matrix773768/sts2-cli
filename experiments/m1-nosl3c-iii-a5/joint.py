"""Isolated normalized-Critic arm using the frozen A2 training prefix."""
import argparse
from hashlib import sha256
from inspect import getsource
import json
from pathlib import Path
import sys
from textwrap import dedent
from time import perf_counter
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iii-a2"))
from curve import a1, configure, digest, load_step, manifests, p0, read, save, torch, v4

A2 = Path("logs/nosl3c-iii-a2-01")
SCALE = 100
VERSION = v4.MODEL + ".a5-normalized-100"
BASE = v4.Policy
BASE_OPTIMIZE = v4.optimize
OPS = BASE_OPTIMIZE.__globals__


class Policy(BASE):
    def __init__(self):
        super().__init__()
        with torch.no_grad():
            self.return_head[-1].weight.div_(SCALE)
            self.return_head[-1].bias.div_(SCALE)

    def forward(self, decision, history):
        logits, value, state, actions = super().forward(decision, history)
        return logits, SCALE * value, state, actions


def checkpoint_policy(policy):
    return OPS["checkpoint_policy"](policy) | {"version": VERSION, "value_scale": SCALE}


def candidate_optimize():
    source = dedent(getsource(BASE_OPTIMIZE))
    substitutions = {
        "advantage = reward - value.detach()": "advantage = reward - SCALE * value.detach()",
        "(value - reward).square()": "(value - reward / SCALE).square()",
    }
    for old, new in substitutions.items():
        assert source.count(old) == 1
        source = source.replace(old, new)
    scope = OPS | dict(MODEL=VERSION, SCALE=SCALE, checkpoint_policy=checkpoint_policy)
    exec(compile(source, "<A5 v4 objective adapter>", "exec"), scope)
    return scope["optimize"]


def model_patch():
    return patch.multiple(v4, MODEL=VERSION, Policy=Policy, checkpoint_policy=checkpoint_policy,
                          optimize=candidate_optimize())


def cases(path):
    with a1.readonly(path / "training.sqlite") as db:
        query = ("SELECT rows,sha FROM roots JOIN root_hashes USING (phase,step,root) "
                 "WHERE phase='train' AND step=0 ORDER BY root")
        result = []
        for raw, stamp in db.execute(query):
            assert sha256(raw).hexdigest() == stamp
            row = p0["unpack"](raw)
            audit = read(path / "audit" / f"000000-{row['root']}.json")
            assert digest(audit) == row["evidence_sha256"]
            result.append((row, audit))
    assert len(result) == 24
    return result


@torch.no_grad()
def initial_preflight(cfg, baseline_cases, expected_roots):
    base, _ = load_step(A2 / "training/training.sqlite", 0)
    old = BASE().eval()
    old.load_state_dict(base["model"])
    assert OPS["checkpoint_policy"](old)["version"] != VERSION
    torch.manual_seed(cfg["initialization_seed"])
    new = Policy().eval()
    for key, value in old.state_dict().items():
        expected = value / SCALE if key in {"return_head.2.weight", "return_head.2.bias"} else value
        assert torch.equal(new.state_dict()[key], expected), key
    maximum = dict(logits=0., value=0., advantage=0.)
    decisions = 0
    objective = v4.Objective(**cfg["objective"])
    for i, (case, _) in enumerate(baseline_cases):
        assert case["spec"] == expected_roots[i]
        (row,) = case["rows"]
        assert row["behavior"]["seed"] == int(digest([cfg["policy_seed"], 0, i])[:16], 16)
        reward = objective.reward(row["feedback"], case["spec"]["hp"])
        history = torch.zeros(OPS["WIDTH"])
        for step in row["transitions"]:
            d = OPS["decision"](json.dumps(step["observation"], sort_keys=True))
            old_logits, old_value, state, actions = old(d, history)
            new_logits, new_value, _, _ = new(d, history)
            assert torch.equal(old_logits, new_logits)
            maximum["value"] = max(maximum["value"], (old_value-new_value).abs().item())
            if reward is not None:
                a, b = reward-old_value, reward-new_value
                maximum["advantage"] = max(maximum["advantage"], (a-b).abs().item())
            history = old.remember(history, state, actions[step["action"]["index"]])
            decisions += 1
    assert maximum["value"] < 1e-6 and maximum["advantage"] < 2e-5
    return dict(max_abs=maximum, decisions=decisions, candidate_model_sha256=digest(checkpoint_policy(new)))


def gate(out, cfg, baseline_cases, preflight, model_hash):
    current = cases(out / "training")
    assert model_hash == preflight["candidate_model_sha256"]
    adjusted = {"model_version", "behavior", "transitions"}
    objective = v4.Objective(**cfg["objective"])
    differences = []
    maxima = dict(value=0., advantage=0., logp=0.)
    for (a, x), (b, y) in zip(baseline_cases, current, strict=True):
        checks = dict(root=a["spec"] == b["spec"], status=a["status"] == b["status"],
                      audit=all(x.get(k) == y.get(k) for k in ("terminal_verified", "native_terminal_stamp",
                                                               "status", "reason", "boundaries")))
        if len(a["rows"]) != 1 or len(b["rows"]) != 1:
            differences.append(dict(root=a["root"], checks=checks, missing_route=True))
            continue
        left, right = a["rows"][0], b["rows"][0]
        checks["row"] = {k:v for k,v in left.items() if k not in adjusted} == {
            k:v for k,v in right.items() if k not in adjusted}
        checks["seed"] = left["behavior"]["seed"] == right["behavior"]["seed"]
        checks["reward"] = objective.reward(left["feedback"], a["spec"]["hp"]) == objective.reward(
            right["feedback"], b["spec"]["hp"])
        checks["route"] = len(left["transitions"]) == len(right["transitions"])
        if checks["route"]:
            reward = objective.reward(left["feedback"], a["spec"]["hp"])
            for src, dst in zip(left["transitions"], right["transitions"], strict=True):
                checks["route"] &= {k:v for k,v in src.items() if k != "value"} == {
                    k:v for k,v in dst.items() if k != "value"}
                maxima["value"] = max(maxima["value"], abs(src["value"] - dst["value"]))
                maxima["logp"] = max(maxima["logp"], abs(src["behavior_logp"] - dst["behavior_logp"]))
                if reward is not None:
                    maxima["advantage"] = max(maxima["advantage"], abs((reward-src["value"])-(reward-dst["value"])))
        if not all(checks.values()):
            differences.append(dict(root=a["root"], checks=checks))
    save(out / "first-batch-gate.json", dict(differences=differences, maxima=maxima, roots=len(current)))
    assert not differences and maxima["value"] < 1e-6 and maxima["advantage"] < 1e-6
    print("First-batch equivalence gate passed before optimization", flush=True)


def main(out):
    out.mkdir(parents=True)
    configure()
    cfg = read(A2 / "protocol.json")["config"]
    batches, roots = manifests(A2)
    base_protocol = read(A2 / "protocol.json")
    assert digest(batches) == base_protocol["train_sha256"] and digest(roots) == base_protocol["eval_sha256"]
    batches = batches[:36]
    assert len(batches) == 36 and all(len(batch) == 24 for batch in batches)
    cfg["stages"][0]["updates"] = 36
    cfg["a5"] = dict(model=VERSION, value_scale=SCALE, adapter_sha256=sha256(Path(__file__).read_bytes()).hexdigest())
    seeds = base_protocol["evaluation_policy_seeds"]
    save(out / "protocol.json", dict(config=cfg, train_sha256=digest(batches), eval_sha256=digest(roots),
                                     evaluation_policy_seeds=seeds))
    baseline_cases = cases(A2 / "training")
    preflight = initial_preflight(cfg, baseline_cases, batches[0])
    save(out / "initial-preflight.json", preflight)
    print("Frozen initial identity verified", flush=True)
    training = out / "training"
    training.mkdir()
    events = []
    passed = False
    optimize = candidate_optimize()

    def checked_optimize(policy, adam, rows, settings, model_hash):
        nonlocal passed
        if not passed:
            gate(out, cfg, baseline_cases, preflight, model_hash)
            passed = True
        return optimize(policy, adam, rows, settings, model_hash)

    with p0["Meter"]() as meter, p0["observe_workers"](meter, events), model_patch():
        try:
            with patch.object(v4, "optimize", checked_optimize):
                a1.train(training, cfg, batches, meter, events, through=36)
            load_step(training / "training.sqlite", 36)
            for step in (12, 36):
                payload, _ = load_step(training / "training.sqlite", step)
                policy = Policy().eval()
                policy.load_state_dict(payload["model"])
                assert digest(checkpoint_policy(policy)) == payload["model_sha256"]
                for arm in ("sample", "greedy"):
                    directory = out / f"eval-{step:02d}-{arm}"
                    tick, first = meter.start_phase(), len(events)
                    statuses = a1.evaluate(directory, cfg, roots, seeds, policy, arm)
                    save(directory / "summary.json", dict(statuses=statuses, resources=meter.end_phase(tick),
                                                          host_starts=len(events)-first))
                    print(directory.name, dict(statuses), flush=True)
        finally:
            save(out / "workers.json", events)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    main(args.output.resolve())
