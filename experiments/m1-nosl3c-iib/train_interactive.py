"""Collect and update a transactional v3 policy using the frozen no-resource objective."""
import argparse
from contextlib import ExitStack, closing
from hashlib import sha256
import json
from pathlib import Path
import random
from time import perf_counter

import torch

from engine import BANK, CAPTURE, bind, open_worker
from interactive_contract import HERE, Decision, MODEL, OBSERVATION, Policy, TRANSITION, WIDTH, project
from nosl_experience import digest, save_json, terminal

import sys
sys.path.insert(0, str(HERE.parent / "m1-nosl3c"))
from journal import Journal
from learning import train as update
from nosl_model import checkpoint

PROTOCOL = "sts2.nosl3c.interactive.no-resources.v3"


def checkpoint_policy(policy):
    return checkpoint(policy) | {"version": MODEL, "observation": OBSERVATION}


def optimize(policy, optimizer, rows, config, model_hash):
    # Reuse the frozen loss, masking, replay and gradient checks in a private
    # function namespace rather than changing the v1 research entry point.
    from types import FunctionType
    dependencies = update.__globals__ | dict(Decision=Decision, MODEL_VERSION=MODEL, checkpoint=checkpoint_policy)
    return FunctionType(update.__code__, dependencies)(policy, optimizer, rows, config, model_hash)


@torch.no_grad()
def collect(output, versions, spec, policy, model_hash, seed, cap):
    start = perf_counter()
    rng = random.Random(seed)
    history = torch.zeros(WIDTH)
    rows = []
    previous_combat_action = None
    with ExitStack() as stack:
        game = open_worker(output, stack, versions)
        CAPTURE(game, spec)
        source = game.request("f1_audit")
        state = game.request("i1_n2_reset", arm="A", cap=cap, potions=False, rejected=[])["episode"]
        while state["status"] == "active":
            obs = project(state["observation"])
            if any(obs["potions"]) or obs["relics"]:
                raise ValueError("Unexpected active inventory in v3")
            decision = Decision(obs)
            logits, value, embedding, actions = policy(decision, history)
            if not torch.isfinite(logits).all() or not torch.isfinite(value).all():
                raise FloatingPointError("Nonfinite policy output")
            logp = logits.log_softmax(0)
            index = rng.choices(range(len(actions)), weights=logp.exp().tolist(), k=1)[0]
            action = decision.actions[index]
            if obs["decision"]["phase"] == "combat":
                previous_combat_action = action
            position = state["actions"]
            state = game.request("i1_n2_step", position=position, index=index)["episode"]
            if state["status"] == "invalid_action":
                raise ValueError("Engine rejected its own menu")
            advanced = state["actions"] == position + 1
            rows.append(dict(schema=TRANSITION, observation=obs, action=action, position=position,
                             behavior_logp=logp[index].item(), value=value.tolist(), advanced=advanced))
            history = policy.remember(history, embedding, actions[index])
        game.request("i1_n2_close")
        if game.request("f1_audit") != source:
            raise ValueError("Prediction changed its source")
    feedback = terminal(state, previous_combat_action)
    if feedback["eligible"] and any(not row["advanced"] for row in rows):
        raise ValueError("Terminal feedback followed an uncommitted decision")
    row = dict(model_version=MODEL, split="train", mode="sample",
               behavior=dict(model_sha256=model_hash, seed=seed), transitions=rows, feedback=feedback)
    return dict(rows=[row], timing=dict(total_ms=(perf_counter() - start) * 1000))


def fit(output, config, build, through):
    if config["schema"] != PROTOCOL or not config["batches"]:
        raise ValueError("Expected nonempty v3 training manifest")
    if not 0 <= through <= len(config["batches"]):
        raise ValueError("Update limit is outside the manifest")
    for batch in config["batches"]:
        if not batch or any(r["schema"] != 3 or r["relics"] or any(r["potions"]) for r in batch):
            raise ValueError("Expected resource-free schema-3 roots in each update")
    versions = bind(output, build)
    source_files = (*HERE.glob("*.py"), *HERE.glob("*.cs"),
                    HERE.parent / "m1-nosl3c/learning.py", HERE.parent / "m1-nosl3c-iia/contract.py")
    identity = dict(protocol=PROTOCOL, config=digest(config), engine=versions,
                    source={p.name: sha256(p.read_bytes()).hexdigest() for p in source_files})
    torch.manual_seed(config["initialization_seed"])
    policy = Policy().eval()
    optimizer = torch.optim.Adam(policy.parameters(), lr=config["learning_rate"])

    def save(store, step, stats):
        store.save(step, dict(model=policy.state_dict(), adam=optimizer.state_dict(), rng=torch.get_rng_state(),
                              model_sha256=digest(checkpoint_policy(policy))), stats)

    with BANK.writer(output), closing(Journal(output / "training.sqlite", identity)) as store:
        step = store.latest()
        if step is None:
            step = 0
            save(store, step, {})
        saved, stats = store.load(step)
        policy.load_state_dict(saved["model"])
        optimizer.load_state_dict(saved["adam"])
        torch.set_rng_state(saved["rng"])
        if digest(checkpoint_policy(policy)) != saved["model_sha256"]:
            raise ValueError("Restored policy hash differs")
        while step < through and not (output / "STOP").exists():
            model_hash = digest(checkpoint_policy(policy))
            done = store.done("train", step)
            for i, spec in enumerate(config["batches"][step]):
                if (output / "STOP").exists():
                    return
                key = f"{i:06d}"
                if key in done:
                    continue
                seed = int(digest([config["policy_seed"], step, i])[:16], 16)
                row = collect(output, versions, spec, policy, model_hash, seed, config["action_cap"])
                store.commit_root("train", step, row | {"root": key})
            if (output / "STOP").exists():
                return
            rows = list(store.rows("train", step))
            stats = optimize(policy, optimizer, rows, config, model_hash)
            stats["choice_decisions"] = sum(t["observation"]["decision"]["phase"] == "choice"
                                            for r in rows for t in r["transitions"])
            stats["terminal_counts"] = {status: sum(r["feedback"]["status"] == status for r in rows)
                                        for status in sorted({r["feedback"]["status"] for r in rows})}
            step += 1
            save(store, step, stats)
        save_json(output / "review-summary.json", dict(update=step, model_sha256=digest(checkpoint_policy(policy)),
                                                       engine=versions, stats=stats))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--through-update", type=int)
    args = parser.parse_args()
    config = json.loads(args.config.read_bytes())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    fit(output, config, args.solver.resolve(),
        len(config["batches"]) if args.through_update is None else args.through_update)
