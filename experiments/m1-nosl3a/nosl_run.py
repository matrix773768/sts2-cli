"""Collect complete single-path battles, train on policy, then evaluate frozen arms."""
import argparse
from collections import Counter
from contextlib import ExitStack
import gzip
import json
import math
from pathlib import Path
import random
import runpy
import statistics
from time import perf_counter

import torch

from nosl_experience import (EPISODE, OBSERVATION, TRANSITION, digest, public_observation, save_json,
                             targets, terminal)
from nosl_model import CATALOG, Decision, Policy, VERSION, WIDTH, checkpoint, restore

HERE = Path(__file__).resolve().parent
ARMS = {"mechanism": (True, True), "id": (False, True), "no_relation": (True, False)}
HOST = "m1-nosl3a-build"


def roots(config, group, round_index, pilot):
    count = config["reps_per_family" if group == "train" else "report_reps_per_family"]
    for family, character, variant, encounter, hp, cards, stocked in config[group]:
        for rep in range(1 if pilot else count):
            key = digest([config["domain"], "pilot" if pilot else "formal", group, round_index, family, rep])
            rng = random.Random(key)
            deck = [dict(id=card, upgrade=int(i == 2 and rep % 2 == 0))
                    for i, card in enumerate(cards.split())]
            rng.shuffle(deck)
            yield dict(id=key[:16], group=group, family=family, encounter=encounter,
                       character=character, act=1, rep=rep, round=round_index,
                       spec=dict(schema=2, character=character, ascension=0, act=1, act_variant=variant,
                                 encounter=encounter, seed=key[16:28].upper(),
                                 hp=hp + config[f"{group}_hp_offsets"][rep],
                                 max_hp=80 if character == "Ironclad" else 70,
                                 relics=[], potions=["FLEX_POTION" if stocked else None], deck=deck))


def draw(log_probs, rng):
    # Sampling uses the same log-softmax whose selected log probability is stored.
    return rng.choices(range(len(log_probs)), weights=log_probs.exp().tolist(), k=1)[0]


class Prediction:
    def __init__(self, output):
        self.output = output
        self.s3a = runpy.run_path(str(HERE.parent / "m1-s3a/produce.py"))
        self.b1b = self.s3a["b1b"]
        self.s3a["solver_binding"].__globals__["HOST"] = HOST
        self.versions = self.s3a["solver_binding"](output, self.s3a["FROZEN"], None)
        self.versions.update(model=VERSION, observation=OBSERVATION, catalog=CATALOG.content_sha256,
                             torch=str(torch.__version__),
                             adapter=digest([(HERE / p).read_text(encoding="utf-8") for p in
                                             ("PublicEpisode.cs", "build.py", "nosl_experience.py")]))
        if self.versions["game_sha256"] != CATALOG.rule_version:
            raise ValueError("Native DLL and N2E rules differ")
        self.rpc_error = self.b1b.bank.f1.i2.StopRun

    def open(self, stack, root):
        game, _ = self.s3a["attested"](self.output, stack, self.versions)
        surfaces, timing = self.b1b.synth.capture(game, root["spec"])
        audit = dict(exact_root_sha256=digest(surfaces), root_spec=root["spec"])
        return game, timing, audit


def failed(error):
    detail = str(error)
    if isinstance(error, TimeoutError) or getattr(error, "status", None) in ("engine_timeout", "time_limit"):
        return dict(status="timeout", public_reason="engine_timeout")
    if "PredictionUnsupportedException" in detail or "NotSupportedException" in detail:
        return dict(status="unsupported")
    return dict(status="error", public_reason="engine_or_contract_error")


def record(root, arm, model_hash, environment, seed, iteration):
    return dict(schema=EPISODE, root=root["id"], split=root["group"], group=root["family"],
                character=root["character"], encounter=root["encounter"], act=root["act"],
                source="native_constructed_synthetic", reachability="unknown", engine=environment,
                arm=arm, iteration=iteration, behavior={"kind": "categorical", "seed": seed,
                                                       "model_sha256": model_hash}, transitions=[])


@torch.no_grad()
def rollout(game, episode, policy, rng, cap, rpc_error):
    steps = episode["transitions"]
    inference = []
    audit = []
    clock = perf_counter()
    issued = 0
    try:
        reply = game.request("i1_n2_reset", arm="A", cap=cap, potions=True, rejected=[])
        state = reply.get("episode", reply)
        history = torch.zeros(WIDTH)
        while state["status"] == "active":
            observation = public_observation(state["observation"])
            start = perf_counter()
            decision = Decision(observation)
            logits, _, embedding, candidates = policy(decision, history)
            log_probs = logits.log_softmax(dim=0)
            i = draw(log_probs, rng)
            history = policy.remember(history, embedding, candidates[i])
            inference.append((perf_counter() - start) * 1000)
            action = decision.actions[i]
            step = dict(schema=TRANSITION, position=state["actions"], observation=observation,
                        action=action, behavior_logp=log_probs[i].item(), next_observation=None,
                        advanced=False)
            steps.append(step)
            issued += 1
            state = game.request("i1_n2_step", position=step["position"], index=action["index"])["episode"]
            audit.append({k: state.get(k) for k in ("audit_action", "audit_stamp", "detail")})
            step["advanced"] = state.get("actions", 0) == step["position"] + 1
            if state["status"] == "active":
                step["next_observation"] = public_observation(state["observation"])
        episode["feedback"] = terminal(state, steps[-1]["action"] if steps else None)
        if steps and step["advanced"]:
            step["next_observation"] = episode["feedback"]["observation"]
        audit.append({"status": state["status"], "result": state.get("result"), "detail": state.get("detail")})
        game.request("i1_n2_close")
    except (rpc_error, TimeoutError, RuntimeError, OSError) as error:
        episode["feedback"] = terminal(failed(error) | dict(actions=sum(s["advanced"] for s in steps),
                                                             transitions=issued), None)
        audit.append({"fault": str(error)})
    episode.update(rollout_ms=(perf_counter() - clock) * 1000, inference_ms=inference,
                   prepare_ms=reply.get("root_prepare_ms") if "reply" in locals() else None)
    return audit


def train(policy, optimizer, episodes, config):
    qualified = [e for e in episodes if targets(e["feedback"]) is not None]
    if not qualified:
        return dict(updated=False, qualified=0)
    previous = {k: v.detach().clone() for k, v in policy.state_dict().items()}
    optimizer.zero_grad(set_to_none=True)
    actor_total = critic_total = entropy_total = 0.
    replay_error = 0.
    policy_gradient = [torch.zeros_like(p) for p in policy.actor.parameters()]
    decisions = 0
    witnesses = {}
    for e in qualified:
        target = torch.tensor(targets(e["feedback"]))
        weights = torch.tensor([1., config["hp_weight"], config["potion_weight"]])
        utility = target @ weights
        history = torch.zeros(WIDTH)
        episode_actor, episode_critic, episode_entropy = [], [], []
        for step in e["transitions"]:
            d = Decision(step["observation"])
            logits, value, state, actions = policy(d, history)
            i = step["action"]["index"]
            lp = logits.log_softmax(0)
            replay_error = max(replay_error, abs(lp[i].item() - step["behavior_logp"]))
            episode_actor.append(-lp[i] * (utility - value.detach() @ weights))
            episode_critic.append(torch.nn.functional.binary_cross_entropy(value[0], target[0])
                                  + (value[1:] - target[1:]).square().sum())
            episode_entropy.append(-(lp.exp() * lp).sum())
            if len(d.actions) > 1 and not witnesses:
                witnesses.update(decision=d, index=i, p=lp[i].exp().item(),
                                 history=history.detach().clone(), value=value.detach().tolist())
            history = policy.remember(history, state, actions[i])
        if not episode_actor or not all(s["advanced"] for s in e["transitions"]):
            raise ValueError("Qualified episode lacks completed transitions")
        actor = torch.stack(episode_actor).sum()
        critic = torch.stack(episode_critic).mean()
        entropy = torch.stack(episode_entropy).sum()
        loss = actor + config["critic_weight"] * critic - config["entropy_weight"] * entropy
        if not torch.isfinite(loss):
            raise FloatingPointError("Nonfinite on-policy loss")
        pure = torch.autograd.grad(actor, tuple(policy.actor.parameters()), retain_graph=True)
        for total, gradient in zip(policy_gradient, pure, strict=True):
            total.add_(gradient / len(qualified))
        (loss / len(qualified)).backward()
        actor_total += actor.item()
        critic_total += critic.item()
        entropy_total += entropy.item()
        decisions += len(episode_actor)
    if replay_error > 2e-5 or not witnesses:
        raise ValueError(f"Unreplayable on-policy probabilities or empty witness: {replay_error}")
    norms = {key: float(torch.linalg.vector_norm(torch.cat([
        p.grad.flatten() for name, p in policy.named_parameters() if name.startswith(key) and p.grad is not None
    ]))) for key in ("actor", "critic")}
    policy_norm = float(torch.linalg.vector_norm(torch.cat([g.flatten() for g in policy_gradient])))
    if not all(math.isfinite(v) and v > 0 for v in (*norms.values(), policy_norm)):
        raise FloatingPointError(f"Expected finite nonzero actor and critic gradients: {norms}")
    gradient = torch.nn.utils.clip_grad_norm_(policy.parameters(), config["grad_clip"], error_if_nonfinite=True)
    optimizer.step()
    deltas = {k: float((v - previous[k]).abs().max()) for k, v in policy.state_dict().items()}
    if not all(math.isfinite(v) for v in deltas.values()):
        raise FloatingPointError("Nonfinite trained parameters")
    payload = checkpoint(policy)
    reloaded = restore(payload)
    with torch.no_grad():
        d, i = witnesses["decision"], witnesses["index"]
        args = d, witnesses["history"]
        logits, value, *_ = policy(*args)
        cloned_logits, cloned_value, *_ = reloaded(*args)
        if not (torch.equal(logits, cloned_logits) and torch.equal(value, cloned_value)):
            raise ValueError("Model round-trip changed inference")
        p = logits.softmax(0)[i].item()
    if p == witnesses["p"] or any(max(v for k, v in deltas.items() if k.startswith(key)) == 0 for key in norms):
        raise ValueError("Optimizer did not update policy probability and both heads")
    return dict(updated=True, qualified=len(qualified), decisions=decisions,
                gradient=float(gradient), head_gradients=norms, policy_gradient=policy_norm, parameter_deltas=deltas,
                actor_loss=actor_total / len(qualified), critic_loss=critic_total / len(qualified),
                entropy=entropy_total / len(qualified), behavior_logp_error=replay_error,
                witness=dict(before=witnesses["p"], after=p, value_before=witnesses["value"],
                             value_after=value.tolist()), restore_exact=True)


def q1(game, cap):
    result = game.request("i1_f3b", arm="C", cap=cap, potions=True, rejected=[], ls2_trajectory="Q1")["search"]
    r = result["resource"]
    state = dict(status=result["status"], detail=result.get("detail"),
                 result={"boundary": result["boundary"], "gaps": result["gaps"]},
                 actions=len(result["actions"]), transitions=result["transitions"],
                 terminal_observation=dict(hp=r["hp"], max_hp=r["max_hp"], potions=r["potions"]))
    last = result["actions"][-1]["kind"] if result["actions"] else None
    end = "end_turn" if last in ("EndTurn", 2) else "other"
    return terminal(state, {"kind": end}), result


def attempt(environment, root, specs, config, iteration, output):
    started = perf_counter()
    episodes, audit = {}, {}
    seed = digest([root["id"], "policy-sampling-v1"])
    for arm, (policy, model_hash) in specs.items():
        episodes[arm] = record(root, arm, model_hash, environment.versions, seed, iteration)
        if policy is None:
            episodes[arm]["behavior"] = {"kind": "frozen_ls2a_q1"}
    try:
        with ExitStack() as stack:
            game, timing, exact = environment.open(stack, root)
            audit.update(exact)
            before = game.request("f1_audit")
            for arm, (policy, _) in specs.items():
                e = episodes[arm]
                tick = perf_counter()
                if policy is None:
                    e["feedback"], audit[arm] = q1(game, config["action_cap"])
                    e["inference_ms"] = []
                else:
                    audit[arm] = rollout(game, e, policy, random.Random(seed), config["action_cap"],
                                         environment.rpc_error)
                e.update(root_ms=timing["root_ms"], total_ms=timing["root_ms"] + (perf_counter() - tick) * 1000)
                after = game.request("f1_audit")
                if before != after:
                    raise RuntimeError("Source root mutated")
    except (environment.rpc_error, TimeoutError, RuntimeError, OSError) as error:
        audit["root_error"] = str(error)
        for e in episodes.values():
            if "feedback" not in e or "Source root mutated" in str(error):
                e.update(feedback=terminal(failed(error), None), inference_ms=[],
                         total_ms=(perf_counter() - started) * 1000)
    for arm, e in episodes.items():
        save_json(output / "public" / f"{root['id']}-{arm}.json.gz", e, compress=True)
    save_json(output / "audit-only" / f"{root['id']}.json.gz", audit, compress=True)
    return episodes


def quantiles(samples):
    if not samples:
        return None
    return {"n": len(samples), "p50": statistics.median(samples),
            "p95": sorted(samples)[math.ceil(.95 * len(samples)) - 1]}


def summarize(rows):
    counts = Counter(e["feedback"]["status"] for e in rows)
    normal = [e["feedback"] for e in rows if e["feedback"]["eligible"]]
    wins = [f["observation"] for f in normal if f["status"] == "predicted_win"]
    return dict(attempts=len(rows), statuses=counts, eligible=len(normal),
                reasons=Counter(e["feedback"]["reason"] for e in rows if e["feedback"]["reason"]),
                episodes_with_solver_notes=sum(e["feedback"]["solver_gap_count"] > 0 for e in rows),
                win_per_attempt=len(wins) / len(rows), win_per_eligible=len(wins) / len(normal) if normal else None,
                win_hp=sorted(o["hp"] for o in wins), normal_hp=sorted(f["observation"]["hp"] for f in normal),
                win_potions=dict(Counter(",".join(p or "-" for p in o["potions"]) for o in wins)),
                hp_and_potions=[dict(status=f["status"], hp=f["observation"]["hp"],
                                     max_hp=f["observation"]["max_hp"], potions=f["observation"]["potions"])
                                for f in normal],
                inference_ms=quantiles([x for e in rows for x in e["inference_ms"]]),
                total_ms=quantiles([e["total_ms"] for e in rows]),
                actions=quantiles([e["feedback"]["actions"] for e in rows]),
                replays=quantiles([e["feedback"]["replays"] for e in rows]),
                rollout_ms=quantiles([e["rollout_ms"] for e in rows if "rollout_ms" in e]))


def evaluate(env, config, summary, output):
    specs = {}
    for arm in ARMS:
        for phase in ("initial", "trained"):
            payload = json.loads(gzip.decompress((output / f"{arm}-{phase}.json.gz").read_bytes()))
            model_hash = digest(payload)
            if summary[phase].get(arm) != model_hash:
                raise ValueError(f"Frozen {arm} {phase} digest mismatch")
            specs[f"{arm}_{phase}"] = (restore(payload), model_hash)
    save_json(output / "summary.json", summary)
    specs["frozen_q1"] = (None, None)
    report = {arm: [] for arm in specs}
    for root in roots(config, "report", 0, False):
        for arm, result in attempt(env, root, specs, config, "report", output).items():
            report[arm].append(result)
    summary["evaluation"] = {arm: summarize(rows) for arm, rows in report.items()}
    summary["evaluation_by_family"] = {arm: {family: summarize([e for e in rows if e["group"] == family])
                                               for family in sorted({e["group"] for e in rows})}
                                       for arm, rows in report.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, default=HERE / "config.json")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--pilot", action="store_true")
    mode.add_argument("--resume-evaluation", action="store_true")
    args = parser.parse_args()
    torch.set_num_threads(1)
    output = args.output.resolve()
    if not args.resume_evaluation:
        output.mkdir(parents=True, exist_ok=False)
        for folder in ("public", "audit-only"):
            (output / folder).mkdir()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if config["schema"] != "sts2.nosl3a.experiment.v1" or config["evaluation"] != "sample":
        raise ValueError("Unsupported experiment configuration")
    started = perf_counter()
    env = Prediction(output)
    if args.resume_evaluation:
        summary = json.loads((output / "summary.json").read_bytes())
        if (summary["pilot"] or summary["config_sha256"] != digest(config)
                or env.versions != summary["engine"] or len(summary["training"]) != config["training_rounds"]):
            raise ValueError("Resume requires a compatible, completed formal training run")
        evaluate(env, config, summary, output)
        summary["evaluation_resume_seconds"] = perf_counter() - started
        save_json(output / "summary.json", summary)
        return
    summary = dict(config=config, config_sha256=digest(config), engine=env.versions, pilot=args.pilot,
                   initial={}, trained={}, training=[], evaluation={})
    models, optimizers = {}, {}
    for arm, (mechanics, relations) in ARMS.items():
        torch.manual_seed(config["initialization_seed"])
        models[arm] = Policy(mechanics, relations)
        optimizers[arm] = torch.optim.Adam(models[arm].parameters(), lr=config["learning_rate"])
        initial = checkpoint(models[arm])
        summary["initial"][arm] = digest(initial)
        save_json(output / f"{arm}-initial.json.gz", initial, compress=True)
    rounds = 1 if args.pilot else config["training_rounds"]
    for iteration in range(rounds):
        specs = {arm: (p, digest(checkpoint(p))) for arm, p in models.items()}
        batch = {arm: [] for arm in specs}
        tick = perf_counter()
        for root in roots(config, "train", iteration, args.pilot):
            for arm, result in attempt(env, root, specs, config, iteration, output).items():
                batch[arm].append(result)
        collection_seconds = perf_counter() - tick
        tick = perf_counter()
        updates = {arm: train(p, optimizers[arm], batch[arm], config) for arm, p in models.items()}
        training = dict(round=iteration, collection_seconds=collection_seconds,
                        optimizer_seconds=perf_counter() - tick, updates=updates,
                        samples={arm: summarize(rows) for arm, rows in batch.items()})
        summary["training"].append(training)
        print("training", iteration, {arm: sample["statuses"] for arm, sample in training["samples"].items()},
              flush=True)
        save_json(output / "summary.json", summary)
    for arm, model in models.items():
        payload = checkpoint(model)
        summary["trained"][arm] = digest(payload)
        save_json(output / f"{arm}-trained.json.gz", payload, compress=True)
    if any(not any(r["updates"][arm]["updated"] for r in summary["training"]) for arm in models):
        raise RuntimeError("No eligible on-policy update for one or more arms")
    summary["training_wall_seconds"] = perf_counter() - started
    save_json(output / "summary.json", summary)
    if not args.pilot:
        evaluate(env, config, summary, output)
    summary["wall_seconds"] = perf_counter() - started
    save_json(output / "summary.json", summary)


if __name__ == "__main__":
    main()
