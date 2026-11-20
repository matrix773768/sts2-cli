"""Report clustered values, paired learning curves, and observable behavior."""
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import random
import sqlite3
from statistics import mean, pstdev

import torch

from nosl3b_protocol import HERE, digest
from nosl3b_store import restore, tensors, unpack
from nosl3b_episode import baseline
from nosl_experience import save_json, targets
from nosl_model import CATALOG, Decision, WIDTH, token
from semantics import CardInstance


def grouped(rows, key):
    result = defaultdict(list)
    for row in rows:
        result[key(row)].append(row)
    return result


def avg(values):
    values = list(values)
    return mean(values) if values else None


def win(row):
    return row["feedback"]["status"] == "predicted_win"


def card_for(obs, action):
    return (next(c["id"] for c in obs["hand"] if c["index"] == action["card"])
            if action["card"] is not None else None)


def path(row):
    return [(step["observation"]["turn"], step["action"]["kind"],
             card_for(step["observation"], step["action"]), step["action"]["card"],
             step["action"]["choice"], step["action"]["target"], step["action"]["potion"])
            for step in row["transitions"]]


def episode_entropy(row):
    values = [-sum(math.exp(lp) * lp for lp in step["policy_logp"])
              for step in row["transitions"] if len(step["policy_logp"]) > 1]
    return avg(values)


def values_by_root(rows):
    # One decision per encounter attempt; average all repeated policy draws at each root.
    audit = []
    for root, group in grouped(rows, lambda r: r["root"]).items():
        items = [(e["transitions"][0]["value"], targets(e["feedback"])) for e in group
                 if e["transitions"] and e["feedback"]["eligible"]]
        if not items:
            continue
        prediction = [mean(p[k] for p, _ in items) for k in range(3)]
        observed = [mean(y[k] for _, y in items) for k in range(3)]
        audit.append((root, prediction, observed,
                      mean((p[0] - y[0]) ** 2 for p, y in items),
                      mean(-math.log(max(1e-9, p[0] if y[0] else 1 - p[0])) for p, y in items),
                      [mean(abs(p[k] - y[k]) for p, y in items) for k in (1, 2)]))
    bins = grouped(audit, lambda item: min(4, int(item[1][0] * 5)))
    return dict(roots=len(audit), p_mean=avg(x[1][0] for x in audit), wins=avg(x[2][0] for x in audit),
                brier=avg(x[3] for x in audit), log_loss=avg(x[4] for x in audit),
                hp_mae=avg(x[5][0] for x in audit), potion_mae=avg(x[5][1] for x in audit),
                calibration=[dict(bin=i, roots=len(data), prediction=avg(x[1][0] for x in data),
                                  actual=avg(x[2][0] for x in data)) for i, data in sorted(bins.items())])


def estimate(rows):
    counts = Counter(e["feedback"]["status"] for e in rows)
    eligible = [e for e in rows if e["feedback"]["eligible"]]
    victories = [e for e in eligible if win(e)]
    stocked = [e for e in victories if e["stocked"]]
    ys = [targets(e["feedback"]) for e in eligible]
    entropy = [episode_entropy(e) for e in rows]
    return dict(attempts=len(rows), roots=len({e["root"] for e in rows}), statuses=dict(counts),
                wins=len(victories), eligible=len(eligible), wins_per_attempt=len(victories) / len(rows),
                wins_per_eligible=len(victories) / len(eligible) if eligible else None,
                raw_win_hp=sorted(e["feedback"]["observation"]["hp"] for e in victories),
                win_hp_mean=avg(e["feedback"]["observation"]["hp"] for e in victories),
                win_stocked=len(stocked), win_retained=sum(any(e["feedback"]["observation"]["potions"]) for e in stocked),
                joint_stocked=[dict(hp=e["feedback"]["observation"]["hp"],
                                    potions=e["feedback"]["observation"]["potions"]) for e in stocked],
                weighted_hp=avg(y[1] for y in ys), weighted_potion=avg(y[2] for y in ys),
                entropy=avg(x for x in entropy if x is not None), values=values_by_root(rows),
                env_replays=sum(e["feedback"]["replays"] for e in rows),
                actions=baseline.quantiles([e["feedback"]["actions"] for e in rows]),
                inference_ms=baseline.quantiles([ms for e in rows for ms in e["inference_ms"]]),
                warm_rollout_ms=baseline.quantiles([e["rollout_ms"] for e in rows if "rollout_ms" in e and not e["cold_first"]]),
                charged_total_ms=baseline.quantiles([e["total_ms"] for e in rows]))


def advantage(rows, config):
    trajectory = []
    for row in rows:
        y = targets(row["feedback"])
        if y is None:
            continue
        weights = (1, config["hp_weight"], config["potion_weight"])
        values = [sum(w * (t - v) for w, t, v in zip(weights, y, step["value"], strict=True))
                  for step in row["transitions"]]
        trajectory.append(mean(values))
    if not trajectory:
        return None
    return dict(episodes=len(trajectory), mean=mean(trajectory), stdev=pstdev(trajectory),
                minimum=min(trajectory), maximum=max(trajectory),
                positive=sum(v > 0 for v in trajectory), negative=sum(v < 0 for v in trajectory))


def pressure_context(obs):
    incoming = sum(sum(e["attack_hits"]) for e in obs["enemies"])
    projected_loss = max(0, incoming - obs["block"])
    enemies = {e["index"]: e for e in obs["enemies"]}
    lethal = False
    for a in obs["actions"]:
        p = a["preview"] or {}
        target = enemies.get(a["target"])
        if p.get("damage_per_hit") is not None and p.get("hits") and target:
            if p["damage_per_hit"] * p["hits"] >= target["hp"] + target["block"]:
                lethal = True
                break
    return dict(known_target_lethal=lethal, known_combat_lethal=lethal and len(enemies) == 1,
                incoming=incoming, lethal_incoming_proxy=projected_loss >= obs["hp"])


def potion_stats(rows):
    buckets = defaultdict(lambda: dict(decisions=0, selected=0, top=0, mass=0.))
    use_turn = Counter()
    advances = []
    witnesses = []
    episode_mass = []
    for row in rows:
        if not row["stocked"]:
            continue
        masses = []
        for step in row["transitions"]:
            obs = step["observation"]
            potions = [a["index"] for a in obs["actions"] if a["kind"] == "use_potion"]
            if not potions:
                continue
            lp = step["policy_logp"]
            best_potion = max(lp[i] for i in potions)
            used = step["action"]["kind"] == "use_potion"
            context = pressure_context(obs)
            turn = str(min(4, obs["turn"]))
            keys = ["all", f"turn_{turn}", "known_combat_lethal" if context["known_combat_lethal"]
                    else "no_verified_combat_lethal", "lethal_incoming_proxy" if context["lethal_incoming_proxy"]
                    else "no_lethal_incoming_proxy"]
            mass = sum(math.exp(lp[i]) for i in potions)
            masses.append(mass)
            for key in keys:
                b = buckets[key]
                b["decisions"] += 1
                b["selected"] += int(used)
                b["top"] += int(step["policy_argmax"] in potions)
                b["mass"] += mass
            if not used or not step["advanced"]:
                continue
            use_turn[turn] += 1
            nxt = step["next_observation"]
            if nxt and "actions" in nxt:
                def attacks(state):
                    return {(a["card"], a["target"]): a["preview"]["damage_per_hit"]
                            for a in state["actions"] if (a["preview"] or {}).get("damage_per_hit") is not None}
                old, new = attacks(obs), attacks(nxt)
                result = dict(delta_energy=nxt["energy"] - obs["energy"],
                              delta_block=nxt["block"] - obs["block"],
                              delta_hp=nxt["hp"] - obs["hp"],
                              incoming_after=pressure_context(nxt)["incoming"],
                              preview_deltas=sorted(new[k] - old[k] for k in old.keys() & new.keys()))
                advances.append(result)
                if context["known_combat_lethal"] and len(witnesses) < 4:
                    witnesses.append(dict(root=row["root"], initialization=row["initialization"], turn=obs["turn"],
                                          position=step["position"], enemy_hp=[e["hp"] for e in obs["enemies"]],
                                          hp=obs["hp"], rank=1 + sum(q > best_potion for q in lp),
                                          potion_probability=mass, win=win(row), **context, **result))
        if masses:
            episode_mass.append(mean(masses))
    for b in buckets.values():
        b["mean_mass"] = b.pop("mass") / b["decisions"]
    return dict(buckets=dict(buckets), use_turn=dict(use_turn), equal_episode_mass=avg(episode_mass),
                effect_count=len(advances), effect_preview_pairs=sum(len(x["preview_deltas"]) for x in advances),
                preview_deltas=dict(Counter(str(d) for x in advances for d in x["preview_deltas"])),
                delta_hp=dict(Counter(str(x["delta_hp"]) for x in advances)),
                delta_energy=dict(Counter(str(x["delta_energy"]) for x in advances)),
                delta_block=dict(Counter(str(x["delta_block"]) for x in advances)), witnesses=witnesses)


def combos(rows):
    counts = Counter()
    for row in rows:
        if not row["transitions"]:
            continue
        deck = {c["id"] for c in row["transitions"][0]["observation"]["deck"]}
        for buff, attack, generator in (("INFLAME", "TWIN_STRIKE", None),
                                       ("ACCURACY", "SHIV", "CLOAK_AND_DAGGER")):
            key = buff + "_then_" + (generator + "_then_" if generator else "") + attack
            if not {buff, generator or attack} <= deck:
                continue
            counts[key + "_eligible_deck"] += 1
            steps = [(o["turn"], name) for o, name in
                     ((s["observation"], card_for(s["observation"], s["action"]))
                      for s in row["transitions"] if s["advanced"])]
            primed = False
            generator_turn = None
            buff_turn = None
            for turn, name in steps:
                if name == buff:
                    buff_turn = turn
                if generator and name == generator and buff_turn is not None:
                    generator_turn = turn
                if name == attack and (generator_turn if generator else buff_turn) == turn:
                    primed = True
            counts[key + "_observed"] += int(primed)
    return dict(counts)


@torch.no_grad()
def verify_policy_scores(connection, rows, config):
    """Recover pre-softmax rankings and independently verify the frozen public action ledger."""
    torch.set_num_threads(1)
    counters = Counter()
    for stage, episodes in grouped((r for r in rows if r["mode"] in ("sample", "greedy")),
                                   lambda r: r["iteration"]).items():
        payload, = connection.execute("SELECT payload FROM snapshots WHERE step=?", (stage,)).fetchone()
        models, _ = restore(tensors(payload), config, resume=False)
        for row in episodes:
            p = models[f'{row["initialization"]}:{row["arm"]}']
            history = torch.zeros(WIDTH)
            for step in row["transitions"]:
                d = Decision(step["observation"])
                logits, _, state, actions = p(d, history)
                chosen = step["action"]["index"]
                recomputed = logits.log_softmax(0).tolist()
                recorded = step["policy_logp"]
                if len(recomputed) != len(recorded) or max(
                        abs(a - b) for a, b in zip(recorded, recomputed, strict=True)) > 2e-5:
                    raise ValueError("Archived model did not reproduce the public scores")
                top = int(logits.argmax())
                if step.get("policy_argmax", top) != top or d.actions[chosen] != step["action"]:
                    raise ValueError("Archived ranking or legal action binding changed")
                if row["mode"] == "greedy":
                    if chosen != top or step["behavior_logp"] != 0:
                        raise ValueError("Recorded Greedy action was not the raw-logit maximum")
                    counters["greedy_rounded_ties"] += int(chosen != max(range(len(recorded)), key=recorded.__getitem__))
                    counters["greedy_steps"] += 1
                elif abs(step["behavior_logp"] - recomputed[chosen]) > 2e-5:
                    raise ValueError("Recorded Sample probability changed")
                step["policy_argmax"] = top
                counters["steps"] += 1
                history = p.remember(history, state, actions[chosen])
    return dict(counters)


def score_crossings(a, b):
    pairs = []
    for x, y in zip(a["transitions"], b["transitions"]):
        if x["position"] != y["position"] or x["observation"] != y["observation"]:
            break
        pairs.append((x, y))
        if x["action"] != y["action"]:
            break
    if not pairs:
        return dict(states=0, tv_sum=0., rank_changes=0)
    baseline_p = [(x["policy_logp"], y["policy_logp"]) for x, y in pairs]
    return dict(states=len(pairs), tv_sum=sum(sum(abs(math.exp(i) - math.exp(j)) for i, j in zip(x, y)) / 2
                                            for x, y in baseline_p),
                rank_changes=sum(x["policy_argmax"] != y["policy_argmax"] for x, y in pairs))


def contrast(rows, key_a, key_b):
    groups = {key: {(r["root"], r["initialization"], r["replicate"]): r for r in rows
                    if (r["iteration"], r["mode"], r["arm"]) == key} for key in (key_a, key_b)}
    a, b = (groups[key] for key in (key_a, key_b))
    if a.keys() != b.keys():
        raise ValueError("Unpaired contrast")
    families = defaultdict(list)
    differences, same, tv, n, rank = [], 0, 0., 0, 0
    for k, x in a.items():
        y = b[k]
        d = int(win(y)) - int(win(x))
        differences.append(d)
        families[x["group"]].append(d)
        same += path(x) == path(y)
        stats = score_crossings(x, y)
        tv += stats["tv_sum"]
        n += stats["states"]
        rank += stats["rank_changes"]
    clusters = [mean(v) for v in families.values()]
    rng = random.Random("nosl3b-cluster-bootstrap-v1")
    boot = sorted(mean(rng.choices(clusters, k=len(clusters))) for _ in range(2000))
    return dict(pairs=len(a), deck_clusters=len(clusters), changed_paths=len(a) - same,
                improvements=differences.count(1), declines=differences.count(-1), delta=mean(differences),
                cluster_interval=[boot[50], boot[1949]], exact_public_states=n,
                mean_common_tv=tv / n if n else None, argmax_changes=rank)


def collisions(rows):
    cards = {(c["id"], c["upgrade"]) for r in rows for s in r["transitions"]
             for zone in ("deck", "hand") for c in s["observation"][zone]}
    ids = grouped(sorted({cid for cid, _ in cards}), token)
    rule = set()
    for card_id, upgrade in cards:
        spec = CATALOG.encode_card_instance(CardInstance(card_id, upgrade))
        if spec["type"]:
            rule.add("type:" + spec["type"])
        if spec["targeting"]:
            rule.add("target:" + spec["targeting"])
        rule.add("qualification:" + spec["qualification"])
        for node in spec["effects"]:
            shape = {k: v for k, v in node.items() if not isinstance(v, (int, float))}
            rule.add("effect:" + json.dumps(shape, sort_keys=True))
    return dict(card_ids=len({cid for cid, _ in cards}), identity_collisions=[names for names in ids.values() if len(names) > 1],
                rule_tokens=len(rule), rule_collisions=[names for names in grouped(sorted(rule), token).values() if len(names) > 1])


def policy_sampling(rows):
    groups = grouped(rows, lambda r: (r["root"], r["initialization"], r["arm"], r["iteration"]))
    completed = [g for g in groups.values() if len(g) > 1]
    return dict(groups=len(completed), different_outcomes=sum(len({r["feedback"]["status"] for r in g}) > 1
                                                              for g in completed),
                different_paths=sum(any(path(x) != path(g[0]) for x in g[1:]) for g in completed))


def audit_pair(rows, counterfactual):
    last = max(r["iteration"] for r in rows if r["mode"] == "sample")
    originals = {(r["root"], r["initialization"]): r for r in rows if r["arm"] == "mechanism"
                 and r["mode"] == "sample" and r["replicate"] == 0 and r["iteration"] == last}
    results = Counter()
    enabled_hp, masked_hp = [], []
    for audited in counterfactual:
        original = originals[(audited["root"], audited["initialization"])]
        assert original["behavior"]["seed"] == audited["behavior"]["seed"]
        results[original["feedback"]["status"] + " -> " + audited["feedback"]["status"]] += 1
        if win(original) and win(audited):
            enabled_hp.append(original["feedback"]["observation"]["hp"])
            masked_hp.append(audited["feedback"]["observation"]["hp"])
    return dict(pairs=len(counterfactual), outcomes=dict(results), both_win_hp_enabled=avg(enabled_hp),
                both_win_hp_masked=avg(masked_hp), masked_wins=sum(win(r) for r in counterfactual))


def analyze(output, config):
    connection = sqlite3.connect(output / "training.sqlite")
    training, report, counterfactual = ([e for payload, in connection.execute(
        "SELECT rows FROM roots WHERE phase=? ORDER BY step, root", (phase,)) for e in unpack(payload)]
        for phase in ("train", "report", "counterfactual"))
    snapshots = {step: unpack(blob) for step, blob in connection.execute("SELECT step,stats FROM snapshots")}
    root_groups = {phase: dict(groups=count, worker_seconds=elapsed) for phase, count, elapsed in
                   connection.execute("SELECT phase,count(*),sum(elapsed) FROM roots GROUP BY phase")}
    rank_audit = verify_policy_scores(connection, report, config)
    connection.close()
    short = {}
    for (stage, arm, mode), rows in grouped(report, lambda r: (r["iteration"], r["arm"], r["mode"])).items():
        key = f"{stage}:{arm}:{mode}"
        short[key] = dict(overall=estimate(rows),
                          by_split={split: estimate(g) for split, g in grouped(rows, lambda r: r["split"]).items()},
                          by_coverage={name: estimate(g) for name, g in grouped(rows, lambda r: "partial" if r["missing_cards"] else "complete").items()},
                          by_seed={str(seed): estimate(g) for seed, g in grouped(rows, lambda r: r["initialization"]).items()},
                          combo=combos(rows), potion=potion_stats(rows))
    for (stage, seed, arm), rows in grouped(training, lambda r: (r["iteration"], r["initialization"], r["arm"])).items():
        report_entry = snapshots[stage + 1]["updates"][f"{seed}:{arm}"]
        report_entry.update(advantage=advantage(rows, config), attempt_stats=estimate(rows))
    last = config["schedule"]["updates"]
    contrasts = {}
    for subset in ("overall", "regular", "combination"):
        group = report if subset == "overall" else [r for r in report if r["split"] == subset]
        contrasts[subset] = {}
        for mode in ("sample", "greedy"):
            for arm in baseline.ARMS:
                contrasts[subset][f"{arm}:{mode}:learning"] = contrast(group, (0, mode, arm), (last, mode, arm))
            for other in ("id", "no_relation"):
                contrasts[subset][f"{other}:{mode}:vs_mechanism"] = contrast(group, (last, mode, other), (last, mode, "mechanism"))
                contrasts[subset][f"{other}:{mode}:init_vs_mechanism"] = contrast(group, (0, mode, other), (0, mode, "mechanism"))
    summary = dict(protocol=digest(config), root_groups=root_groups, score_replay=rank_audit,
                   report=short, train=snapshots, contrasts=contrasts,
                   policy_sampling=policy_sampling([r for r in report if r["mode"] == "sample"]),
                   collision_audit=collisions([*training, *report]),
                   offline_potion_audit=audit_pair(report, counterfactual),
                   clocks=json.loads((output / "last-evaluation-clock.json").read_bytes()))
    save_json(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, default=HERE / "formal.json")
    args = parser.parse_args()
    analyze(args.output, json.loads(args.config.read_bytes()))
