"""Public-only candidate ranking with matched identity and N2E set models."""
import sys
from collections import Counter
from time import perf_counter
import runpy

import numpy as np

from ls1_design import HERE, PROTOCOL, STRATEGIES, digest, file_hash
from semantics import CardInstance, DeckSpec, load_catalog

OLD = HERE.parent / "m1-n2f-a"
sys.path.insert(0, str(OLD))
network = runpy.run_path(str(OLD / "learning.py"))
CATALOG = load_catalog()
MODES = ("card_id", "mechanics")
RELICS = ("BURNING_BLOOD", "RING_OF_THE_SNAKE")
POTIONS = ("FLEX_POTION", "DEXTERITY_POTION")
ENCODER = digest([file_hash(HERE / "model.py", True), file_hash(OLD / "learning.py", True),
                  file_hash(HERE.parent / "m1-n2e/semantics.py", True), CATALOG.content_sha256])
MODEL_VERSIONS = ("game_sha256", "solver_sha256", "f3b_first_win", "f3b_route_search", "f4_quality",
                  "preprocess", "catalog", "coreclr", "adapter")


def public_input(public, visible_resources):
    """Allowlist at the native combat-play boundary. Accept no predictor object."""
    if public["decision"] != "combat_play":
        raise ValueError("Expected native combat-play Observation")
    player = public["player"]
    powers = lambda items: sorted(({"id": p["name"], "amount": p["amount"]} for p in items or []),
                                  key=lambda p: p["id"])
    character = {"IRONCLAD.title": "Ironclad", "SILENT.title": "Silent"}[player["name"]]
    # IDs are the slots already visible in the native menu. Exclude its continuation and deck keys.
    if (Counter(p["name"] for p in player["potions"]) != Counter(
            p + ".title" for p in visible_resources["potions"] if p)
            or Counter(r["name"] for r in player["relics"]) != Counter(
                r + ".title" for r in visible_resources["relics"])):
        raise ValueError("Visible inventory does not match ID binding")
    deck = DeckSpec(character, tuple(
        CardInstance(card["id"].removeprefix("CARD."), int(card["upgraded"])) for card in player["deck"]
    ), "visible_deck", True)
    identity = CATALOG.encode_deck(deck, "identity")
    mechanics = CATALOG.encode_deck(deck, "mechanics")
    modified = any("enchantment" in c or "affliction" in c for c in player["deck"] + public["hand"])
    unsupported = []
    if modified:
        unsupported.append("card_modification")
    if any(g["card"]["qualification"] != "static_described" for g in mechanics["cards"]):
        unsupported.append("card_mechanism")
    if set(visible_resources["relics"]) - set(RELICS):
        unsupported.append("relic_mechanism")
    if set(visible_resources["potions"]) - {None, *POTIONS}:
        unsupported.append("potion_mechanism")
    enemies = [
        dict(id=e["name"], hp=e["hp"], max_hp=e["max_hp"], block=e["block"], powers=powers(e.get("powers")),
             intents=[{k: intent[k] for k in ("type", "damage", "hits", "total_damage") if k in intent}
                      for intent in e.get("intents") or []])
        for e in public["enemies"]
    ]
    hand = [{k: c[k] for k in ("id", "type", "cost", "can_play", "target_type")} for c in public["hand"]]
    return dict(character=character, player={k: player[k] for k in ("hp", "max_hp", "block", "gold")},
                act=public["context"]["act"], round=public["round"], energy=public["energy"],
                max_energy=public["max_energy"], draw_count=public["draw_pile_count"],
                discard_count=public["discard_pile_count"], player_powers=powers(public.get("player_powers")),
                enemies=enemies, hand=hand, relics=sorted(visible_resources["relics"]),
                potions=visible_resources["potions"], identity_deck=identity, mechanics_deck=mechanics,
                candidates=[dict(strategy=s, action_limit=48, active_potions=False) for s in STRATEGIES]), unsupported


def incoming(state):
    return sum(i.get("total_damage", i.get("damage", 0)) for e in state["enemies"] for i in e["intents"])


def stats_scores(state):
    counts = Counter()
    for group in state["mechanics_deck"]["cards"]:
        for node in group["card"]["effects"]:
            counts[node["kind"]] += group["count"]
            if node["kind"] == "Damage":
                counts["extra_hits"] += group["count"] * max(0, node.get("hits", node.get("count", 1)) - 1)
    player = state["player"]
    threat = max(0, incoming(state) - player["block"]) / player["hp"]
    scaling = counts["GainPower"] + counts["GenerateCard"] + .5 * counts["extra_hits"]
    return (0.5, (counts["Damage"] - .5 * counts["Block"]) / 7 - threat,
            1.7 * threat + (counts["Block"] - counts["Damage"]) / 8, scaling / 4 - threat)


def features(state, mode, cfg):
    deck = state["identity_deck" if mode == "card_id" else "mechanics_deck"]
    cards = np.stack([network["vector"](group["card"], cfg["card_dim"])
                      for group in deck["cards"] for _ in range(group["count"])])
    p = state["player"]
    enemies = state["enemies"]
    hand = state["hand"]
    common = [p["hp"]/80, p["max_hp"]/80, p["block"]/30, p["gold"]/200,
              state["act"]/3, state["round"]/5, state["energy"]/4, state["max_energy"]/4,
              state["draw_count"]/20, state["discard_count"]/20,
              sum(e["hp"] for e in enemies)/120, sum(e["block"] for e in enemies)/30, len(enemies)/4,
              incoming(state)/30, sum(int(i["type"] == "Attack" and "damage" not in i)
                                      for e in enemies for i in e["intents"])/4,
              len(cards)/20, len(hand)/10,
              sum(c["can_play"] for c in hand)/10,
              *(sum(c["type"] == t and c["can_play"] for c in hand)/5 for t in ("Attack", "Skill", "Power")),
              *(sum(p["amount"] for p in state["player_powers"] if p["id"] == power + ".title") / 5
                for power in ("STRENGTH_POWER", "DEXTERITY_POWER", "WEAK_POWER", "FRAIL_POWER")),
              float(state["character"] == "Silent"),
              *(float(relic in state["relics"]) for relic in RELICS),
              *(state["potions"].count(potion)/3 for potion in POTIONS)]
    return np.asarray(common), cards


def inputs(encoded, strategy_indices, cap):
    common, cards = encoded
    indices = np.asarray(strategy_indices)
    candidate = np.eye(len(STRATEGIES))[indices]
    return (np.column_stack((np.broadcast_to(common, (len(indices), len(common))),
                             candidate, np.full(len(indices), cap / 128))),
            np.broadcast_to(cards, (len(indices), *cards.shape)))


def arrays(examples, mode, cfg):
    states = {}
    left, right = [], []
    for key, state, candidate, cap, _ in examples:
        if key not in states:
            states[key] = features(state, mode, cfg)
        common, cards = inputs(states[key], [STRATEGIES.index(candidate)], cap)
        left.append(common[0])
        right.append(cards[0])
    # The inherited mean-pooling layer has no padding mask. Group by exact deck length.
    sizes = np.array([len(c) for c in right])
    if not len(sizes):
        raise ValueError("No eligible training examples")
    return [(sel, (np.stack([left[i] for i in sel]), np.stack([right[i] for i in sel])))
            for size in sorted(set(sizes)) if len(sel := np.flatnonzero(sizes == size))]


def fit(examples, selection, versions, deadline, provenance):
    cfg = PROTOCOL["training"]
    y = np.asarray([e[-1] for e in examples])
    val_y = np.asarray([e[-1] for e in selection])
    models = {}
    for mode in MODES:
        train = arrays(examples, mode, cfg)
        val = arrays(selection, mode, cfg)
        checkpoints = {epoch: [] for epoch in cfg["epochs"]}
        for seed in cfg["seeds"]:
            params = network["init"](train[0][1], cfg["hidden"], seed)
            moments = {key: np.zeros_like(value) for key, value in params.items()}
            squares = {key: np.zeros_like(value) for key, value in params.items()}
            for epoch in range(1, max(cfg["epochs"]) + 1):
                if perf_counter() >= deadline:
                    raise TimeoutError("Training wall budget exhausted")
                grads = {key: np.zeros_like(value) for key, value in params.items()}
                for idx, batch in train:
                    for key, g in network["gradients"](params, batch, y[idx], cfg["l2"]).items():
                        grads[key] += g * (len(idx) / len(y))
                for key, g in grads.items():
                    moments[key] = .9 * moments[key] + .1 * g
                    squares[key] = .999 * squares[key] + .001 * g**2
                    params[key] -= (cfg["learning_rate"] * moments[key] / (1 - .9**epoch)
                                    / (np.sqrt(squares[key] / (1 - .999**epoch)) + 1e-8))
                if epoch in checkpoints:
                    predictions = np.empty_like(val_y)
                    for idx, batch in val:
                        predictions[idx] = network["forward"](params, batch)[0]
                    checkpoints[epoch].append(({k: v.tolist() for k, v in params.items()}, predictions))
        loss = {epoch: float(np.mean((np.mean([p for _, p in runs], axis=0) - val_y)**2))
                for epoch, runs in checkpoints.items()}
        epoch = min(loss, key=lambda e: (loss[e], e))
        models[mode] = dict(parameters=[p for p, _ in checkpoints[epoch]], epochs=epoch,
                            selection_mse={str(k): v for k, v in loss.items()},
                            parameters_per_seed=sum(v.size for v in params.values()))
    bundle = dict(encoder=ENCODER, protocol=digest(PROTOCOL), versions=model_versions(versions),
                  models=models, numpy=np.__version__, provenance=provenance)
    return bundle | {"sha256": digest(bundle)}


def model_versions(versions):
    return {key: versions[key] for key in MODEL_VERSIONS}


def order(state, gaps, mode, cap, bundle, versions):
    if mode == "baseline_search":
        return STRATEGIES, None, 0.0
    if gaps:
        return STRATEGIES, "unsupported_public_mechanism:" + ",".join(gaps), 0.0
    start = perf_counter()
    try:
        if mode == "statistics":
            scores = stats_scores(state)
        else:
            variant = {"learned_search": "mechanics", "card_id": "card_id"}[mode]
            if bundle is None:
                return STRATEGIES, "model_missing", (perf_counter()-start)*1000
            if bundle["encoder"] != ENCODER or bundle["versions"] != model_versions(versions):
                return STRATEGIES, "model_version_mismatch", (perf_counter()-start)*1000
            cfg = PROTOCOL["training"]
            batch = inputs(features(state, variant, cfg), range(len(STRATEGIES)), cap)
            scores = np.mean([network["forward"](params, batch)[0]
                              for params in bundle["models"][variant]], axis=0)
        if np.shape(scores) != (len(STRATEGIES),) or not np.isfinite(scores).all():
            raise ValueError("Invalid candidate scores")
        ranked = tuple(STRATEGIES[i] for i in sorted(range(len(scores)), key=lambda i: -scores[i]))
        return ranked, None, (perf_counter()-start)*1000
    except (KeyError, ValueError, TypeError, ArithmeticError, IndexError, AttributeError):
        return STRATEGIES, "model_error", (perf_counter()-start)*1000
