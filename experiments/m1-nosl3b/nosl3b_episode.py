"""Single-path deployment and instrumentation atop the frozen NOSL3A worker."""
from contextlib import ExitStack
from dataclasses import dataclass
from time import perf_counter
import random

import torch

from nosl3b_protocol import digest
from nosl_experience import TRANSITION, public_observation, terminal
from nosl_model import CATALOG, Decision, WIDTH
from semantics import CardInstance
import nosl_run as baseline


@dataclass(frozen=True)
class Arm:
    name: str
    model: object
    model_hash: str | None
    initialization: int | None
    mode: str
    replicate: int = 0
    stage: int | str | None = None


def choose(scores, mode, rng, actions):
    if mode == "greedy":
        return int(scores.argmax()), 0.
    if mode == "without_potion":
        allowed = torch.tensor([a["kind"] != "use_potion" for a in actions])
        scores = scores.masked_fill(~allowed, -torch.inf)
    elif mode == "uniform":
        scores = torch.zeros_like(scores)
    elif mode != "sample":
        raise ValueError(f"Unknown mode {mode}")
    logp = scores.log_softmax(0)
    i = baseline.draw(logp, rng)
    return i, float(logp[i])


@torch.no_grad()
def rollout(game, episode, arm, cap):
    steps, times, audit = episode["transitions"], [], []
    clock = perf_counter()
    rng = random.Random(episode["behavior"]["seed"] or 0)
    reply = game.request("i1_n2_reset", arm="A", cap=cap, potions=True, rejected=[])
    state = reply.get("episode", reply)
    history = torch.zeros(WIDTH)
    while state["status"] == "active":
        obs = public_observation(state["observation"])
        start = perf_counter()
        decision = Decision(obs)
        logits, value, embedding, candidates = arm.model(decision, history)
        logp = logits.log_softmax(0)
        i, behavior_logp = choose(logits, arm.mode, rng, decision.actions)
        history = arm.model.remember(history, embedding, candidates[i])
        times.append((perf_counter() - start) * 1000)
        action = decision.actions[i]
        step = dict(schema=TRANSITION, position=state["actions"], observation=obs,
                    action=action, behavior_logp=behavior_logp, policy_logp=logp.tolist(),
                    policy_argmax=int(logits.argmax()),
                    value=value.tolist(), next_observation=None, advanced=False)
        steps.append(step)
        state = game.request("i1_n2_step", position=step["position"], index=action["index"])["episode"]
        audit.append({k: state.get(k) for k in ("audit_action", "audit_stamp", "detail")})
        step["advanced"] = state.get("actions", 0) == step["position"] + 1
        if state["status"] == "active":
            step["next_observation"] = public_observation(state["observation"])
    result = terminal(state, steps[-1]["action"] if steps else None)
    if steps and steps[-1]["advanced"]:
        steps[-1]["next_observation"] = result["observation"]
    audit.append({"status": state["status"], "result": state.get("result"), "detail": state.get("detail")})
    game.request("i1_n2_close")
    episode.update(feedback=result, rollout_ms=(perf_counter() - clock) * 1000,
                   inference_ms=times, prepare_ms=reply.get("root_prepare_ms"))
    return audit


def coverage(root):
    items = root["spec"]["deck"]
    missing = {c["id"] for c in items if CATALOG.encode_card_instance(
        CardInstance(c["id"], c["upgrade"]))["qualification"] != "static_described"}
    return sorted(missing)


def attempt(environment, root, specs, config, stage):
    """Share only the unmodified cold root across attempts, with independent policy memory."""
    started = perf_counter()
    missing = coverage(root)
    episodes = []
    for arm in specs:
        seed = None if arm.mode in ("greedy", "q1") else digest(
            [config["domain"], root["id"], "policy-stream", arm.replicate])
        row = baseline.record(root, arm.name, arm.model_hash, environment.versions, seed, stage if arm.stage is None else arm.stage)
        row.update(experiment="sts2.nosl3b.episode.v1", mode=arm.mode, replicate=arm.replicate,
                   initialization=arm.initialization, pressure=root["pressure"], stocked=root["stocked"],
                   recipe_split=root["recipe_split"], held_pair=root["pair"], missing_cards=missing,
                   start_hp=root["spec"]["hp"], inference_ms=[])
        row["behavior"]["kind"] = {"sample": "categorical", "greedy": "argmax",
                                   "uniform": "uniform", "q1": "frozen_ls2a_q1",
                                   "without_potion": "audit_categorical_masked"}[arm.mode]
        episodes.append(row)
    audit = {}
    try:
        with ExitStack() as stack:
            game, timing, exact = environment.open(stack, root)
            audit.update(exact, timing=timing, attempts=[])
            before = game.request("f1_audit")
            # Rotate the cold-first slot using only the predeclared root identifier.
            offset = int(root["id"], 16) % len(specs)
            for j in range(len(specs)):
                i = (j + offset) % len(specs)
                row, arm = episodes[i], specs[i]
                tick = perf_counter()
                if arm.mode == "q1":
                    row["feedback"], private = baseline.q1(game, config["action_cap"])
                    row["rollout_ms"] = (perf_counter() - tick) * 1000
                else:
                    private = rollout(game, row, arm, config["action_cap"])
                audit["attempts"].append(dict(initialization=arm.initialization, arm=arm.name,
                                              mode=arm.mode, replicate=arm.replicate, stage=row["iteration"], trace=private))
                row.update(root_ms=timing["root_ms"], total_ms=timing["root_ms"] + (perf_counter() - tick) * 1000,
                           cold_first=j == 0)
            if game.request("f1_audit") != before:
                raise ValueError("Source root mutated")
    except (environment.rpc_error, TimeoutError, RuntimeError, OSError) as error:
        audit["error"] = str(error)
        for row in episodes:
            if "feedback" not in row:
                transitions = row["transitions"]
                state = baseline.failed(error) | dict(actions=sum(s["advanced"] for s in transitions),
                                                       transitions=len(transitions))
                row.update(feedback=terminal(state, None), total_ms=(perf_counter() - started) * 1000)
    return episodes, audit
