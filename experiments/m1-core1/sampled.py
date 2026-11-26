"""Public-history conditional turn policies on the resident SV prediction host."""
from collections import Counter
from pathlib import Path
import random
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-n4b"))
from design import cohort, digest, extract, prepared, step
from policy import address

CAP = 16
COMBAT = "combat"


def card_type(card):
    return card["id"], card["upgrade"]


def proposal(deck, opening, guess, seed):
    """Balance mixture with full support. Guess can be wrong after retain/shuffle."""
    order = cohort.permutation(deck, opening, seed)
    free = order[len(opening):]
    matching = list(free)
    guided = []
    probability = 1.
    for token in guess:
        options = [i for i in matching if card_type(deck[i]) == token]
        if not options:
            return order, 1.
        probability *= len(options) / len(matching)
        chosen = options[0]  # first in uniformly shuffled order within this type
        guided.append(chosen)
        matching.remove(chosen)
    if guess and random.Random("mixture/" + seed).random() < .5:
        random.Random("conditional-tail/" + seed).shuffle(matching)
        order = order[:len(opening)] + guided + matching
    hit = [card_type(deck[i]) for i in order[len(opening):len(opening)+len(guess)]] == guess
    ratio = .5 + (.5 / probability if hit else 0.)
    return order, 1. / ratio


def boundary(st, h, turn):
    if st["status"] != "active":
        if st["status"] in ("death", "predicted_win") and st.get("terminal_observation"):
            return st["status"]
        return "incomplete/" + st["status"]
    if h["turn"] == turn + 1 and h["decision"]["phase"] == COMBAT and h["enemies"]:
        return "B"
    if h["turn"] > turn + 1:
        return "incomplete/skipped_boundary"
    return None


def opening(lane, spec, world, history, metrics):
    seed, order = world
    st = cohort.start(lane, spec | dict(seed=seed), order)
    metrics["root_restores"] += 1
    for prior, action in history:
        if st["status"] != "active" or lane.host.project(st["observation"]) != prior:
            return None
        st = step(lane, st, action)
        metrics["prefix_steps"] += 1
    return st


def worlds(lane, spec, history, h, k, cap, metrics):
    first = history[0][0] if history else h
    if len(first["hand"]) != 5 or first["draw_count"] + 5 != len(spec["deck"]):
        metrics["unsupported_opening_zones"] += 1
        return []
    if Counter(map(card_type,first["hand"])) - Counter(map(card_type,spec["deck"])):
        metrics["unsupported_opening_instances"] += 1
        return []
    # This proposal hint only affects efficiency. Replays and importance weights
    # remain required, including on paths that changed deck order.
    guess = []
    sequence = [o for o,_ in history] + [h]
    for before,after in zip(sequence,sequence[1:]):
        used = before["draw_count"] - after["draw_count"]
        if used < 0 or used > len(after["hand"]):
            break
        if used:
            guess.extend(card_type(c) for c in after["hand"][-used:])
    tag = digest(["core1/donor", history, h])
    accepted = []
    for i in range(cap):
        seed = cohort.seed(tag, "engine", i)
        order, weight = proposal(spec["deck"], first["hand"], guess, cohort.seed(tag, "draw", i))
        st = opening(lane, spec, (seed,order), history, metrics)
        metrics["proposals"] += 1
        match = st and st["status"] == "active" and lane.host.project(st["observation"]) == h
        lane.reset()
        if match:
            accepted.append(((seed,order),weight))
        if len(accepted) == k:
            break
    return accepted


def candidates(lane, model, h, history, metrics):
    """All root actions plus public multi-action witnesses from SV1. G2 fills unseen menus."""
    root = digest(h)
    plans = [((root, a["index"]),) for a in h["actions"]]
    graph = lane.request("i1_sv1_graph", mode="tree", public_run=True, transitions=24,
                         depth=8, wall_ms=1500, memory_bytes=512*2**20)
    metrics["sv1_transitions"] += graph["transitions"]
    metrics["sv1_" + (graph.get("stop") or "exhausted")] += 1
    if graph.get("stop") not in ("wall_cap","managed_memory_cap"):
        c = prepared(model,h,history)
        _,_,ends,_ = extract(graph,lane.host.project,model.encoder,h,c.history)
        for _, route in ends:
            plans.append(tuple((digest(s.observation),s.index) for s in route))
    return list(dict.fromkeys(plans))


def follow(lane, model, st, history, h, plan, metrics, cache):
    c = prepared(model,h,history)
    path = []
    prefix = []
    turn = h["turn"]
    on_prefix = True
    for depth in range(CAP + 1):
        if st["status"] == "active":
            o = lane.host.project(st["observation"])
        else:
            o = None
        kind = boundary(st,o,turn)
        if kind or depth == CAP:
            leaf = o if kind == "B" else st.get("terminal_observation")
            if leaf is not None and kind in ("predicted_win","death"):
                leaf = leaf | {"gold":(st.get("result") or {}).get("gold")}
            return path,kind or "incomplete/depth",leaf
        key = digest(o)
        rule = plan["rules"].get(address(prefix,key)) if isinstance(plan,dict) else None
        if rule is not None:
            a = rule
        elif on_prefix and not isinstance(plan,dict) and depth < len(plan) and key == plan[depth][0]:
            a = plan[depth][1]
        else:
            on_prefix = False
            # Full public path protects recurrent information and conditional belief.
            ident = (tuple(prefix),key)
            if ident not in cache:
                tick = perf_counter()
                cache[ident] = int(c.score([(o,c.history)])[0][0].argmax())
                metrics["inference_seconds"] += perf_counter()-tick
                metrics["inferences"] += 1
            a = cache[ident]
        if o["actions"][a]["index"] != a:
            raise ValueError("Stale public menu")
        c.history = model.encoder.update(c.history,o,o["actions"][a])
        path.append((o,a))
        prefix.append((key,a))
        st = step(lane,st,a)
        metrics["steps"] += 1


def cached_rollout(plan,previous,greedy):
    """Reuse only within one simulated donor and after checking every prescribed move."""
    for branch in previous:
        prefix=[]
        guarded=True
        for depth,(key,a) in enumerate(branch["witness"]):
            if guarded and depth<len(plan) and plan[depth][0]==key:
                expected=plan[depth][1]
            else:
                guarded=False
                expected=greedy.get((tuple(prefix),key))
            if expected!=a:
                break
            prefix.append((key,a))
        else:
            return branch.copy()
    return None


def search(lane, model, spec, history, h, k=3, cap=96, reuse=True):
    """Real-world snapshot/seed is absent. Fresh empirical measures per public root."""
    if not 1 <= k <= cap:
        raise ValueError("Require 1 <= worlds <= proposal cap")
    metrics = Counter()
    started = perf_counter()
    spec = spec | dict(deck=sorted(spec["deck"],key=card_type))
    samples = worlds(lane,spec,history,h,k,cap,metrics)
    policies, observations, cache = [], {}, {}
    plans = []
    if samples:
        opening(lane,spec,samples[0][0],history,metrics)
        plans = candidates(lane,model,h,history,metrics)
        lane.reset()
    initial = len(plans)
    previous=[[] for _ in samples]
    deviations = set()
    visited = set(plans)
    for index,plan in enumerate(plans):
        branches = []
        for i,(world, weight) in enumerate(samples):
            hit = cached_rollout(plan,previous[i],cache) if reuse else None
            if hit is not None:
                branches.append(hit)
                metrics["cached_rollouts"] += 1
                continue
            st = opening(lane,spec,world,history,metrics)
            if not st or lane.host.project(st["observation"]) != h:
                raise ValueError("Conditional replay drift")
            path,kind,leaf = follow(lane,model,st,history,h,plan,metrics,cache)
            lane.reset()
            witness = []
            for o,a in path:
                key = digest(o)
                observations[key] = o
                if index < initial and witness:
                    for move in o["actions"]:
                        alt = (*witness,(key,move["index"]))
                        if move["index"] != a and alt not in visited:
                            deviations.add(alt)
                witness.append((key,a))
            leaf_id = digest(leaf) if leaf is not None else None
            if leaf is not None:
                observations[leaf_id] = leaf
            branches.append(dict(witness=witness,kind=kind,state=leaf_id,weight=weight))
            previous[i].append(branches[-1])
        policies.append(dict(plan=plan,otherwise="frozen_g2",branches=branches))
        if index+1 == initial:
            # Public candidate budget, including deviations after newly observed menus.
            # Re-evaluate each guarded plan in the entire paired block.
            extra = sorted(deviations,key=digest)[:12]
            plans.extend(extra)
            metrics.update(public_deviations=len(deviations),expanded_deviations=len(extra))
    total = sum(w for _,w in samples)
    for p in policies:
        for b in p["branches"]:
            b["probability"] = b.pop("weight") / total
    metrics["seconds"] = perf_counter()-started
    return dict(schema="core1.turn.v1",measure="self_normalized_conditional_samples",
                public_history=digest([history,h]),history=history,root=h,observations=observations,policies=policies,
                draws=len(samples),requested=k,ess=total**2/sum(w*w for _,w in samples) if samples else 0,
                metrics=dict(metrics))
