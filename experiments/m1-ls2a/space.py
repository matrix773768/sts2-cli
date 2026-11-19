"""Catalog-driven stratified synthetic roots and admitted native history imports."""
from collections import Counter, defaultdict
from hashlib import sha256
import random
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "m1-ls1"))
from ls1_design import digest, read, recipe_key

SCHEMA = "sts2.m1-ls2a.manifest.v1"
VERSION = "catalog-strata-v1"


def key(value):
    return int(digest(value)[:16], 16)


def split_for(encounter, config):
    bucket = key(["encounter-holdout-v1", encounter]) % 100
    train, selection = config["split_percent"][:2]
    return "train" if bucket < train else "selection" if bucket < train + selection else "test"


def inventory(native):
    return {card["id"]: card for c in native["characters"] for card in c["cards"]}


def draw_cards(char, rng, config, act):
    size = rng.randint(*config["deck_size"])
    starter = char["starter"]
    pool = [c for c in char["cards"] if c["rarity"] in config["card_rarities"]]
    attacks = [c for c in pool if c["type"] == "Attack"]
    blocks = [c for c in pool if any(v.lower() == "block" for v in c["variables"])]
    if not attacks or not blocks:
        raise ValueError(f"Insufficient configured card pool for {char['name']}")
    # Two starter slots, two distinct additions with structural roles, then sample the native pool.
    kept = rng.sample(starter, min(len(starter), rng.randint(*config["starter_count"])))
    chosen = [rng.choice(attacks)["id"], rng.choice(blocks)["id"]]
    while len(kept) + len(chosen) < size:
        eligible = [c for c in pool if chosen.count(c["id"]) < config["max_added_copies"]]
        if not eligible:
            raise ValueError("Configured deck size exceeds the native pool constraints")
        chosen.append(rng.choice(eligible)["id"])
    names = kept + chosen
    rng.shuffle(names)
    card_by_id = {c["id"]: c for c in char["cards"]}
    eligible = [i for i, name in enumerate(names) if card_by_id[name]["upgradable"]]
    cap = min(len(eligible), config["upgrade_max_by_act"][str(act)])
    upgraded = set(rng.sample(eligible, rng.randint(0, cap)))
    components = sorted(set(chosen))
    family = digest([char["name"], components])
    return [dict(id=name, upgrade=int(i in upgraded)) for i, name in enumerate(names)], family


def synthetic(native, config, count, namespace, consumed=()):
    strata = [
        (char, a["act"], a["variant"], enc)
        for char in native["characters"]
        for a in native["acts"] if a["act"] in config["acts"]
        for enc in a["encounters"] if enc["room"] in config["rooms"]
    ]
    if not strata:
        raise ValueError("No native strata match the configuration")
    consumed = list(consumed)
    recipes = {c["recipe"] for c in consumed}
    families = {c["family"]: c["split"] for c in consumed}
    blocked = [c for c in read(HERE.parent / "m1-ls1/evidence/contract.json")["manifest"]
               if c["split"] in {"report", "reachable"}]
    recipes.update(c["recipe"] for c in blocked)
    batch_rng = random.Random(key([VERSION, namespace]))
    # Balanced rounds traverse kinds and act/character first. Prioritize each stratum independently.
    groups = defaultdict(list)
    for item in strata:
        groups[item[0]["name"], item[1], item[3]["room"]].append(item)
    jobs = []
    drawn = Counter()
    while len(jobs) < count:
        weights = config.get("room_weights", {})
        round_keys = [g for g in sorted(groups) for _ in range(weights.get(g[2], 1))]
        round_mass = len(round_keys)
        batch_rng.shuffle(round_keys)
        for group_key in round_keys:
            if len(jobs) >= count:
                break
            options = groups[group_key]
            # Draw without replacement within each character/act/room stratum pass.
            seen = drawn[group_key]
            drawn[group_key] += 1
            if seen % len(options) == 0:
                batch_rng.shuffle(options)
            char, act, variant, encounter = options[seen % len(options)]
            token = digest([VERSION, namespace, len(jobs)])
            rng = random.Random(int(token, 16))
            split = split_for(encounter["id"], config)
            for _ in range(200):
                deck, family = draw_cards(char, rng, config, act)
                recipe = recipe_key(char["name"], deck)
                if recipe not in recipes and families.get(family, split) == split:
                    break
            else:
                raise ValueError("Requested draw cannot satisfy composition/holdout constraints")
            recipes.add(recipe)
            families[family] = split
            band = rng.choice(config["hp_percent"])
            hp = max(1, char["max_hp"] * rng.randint(*band) // 100)
            relics = char["relics"] if rng.random() < config["starter_relic_probability"] else []
            ascension = rng.choice(config["ascension"])
            # Use the verified first two slots on ascended runs. Null padding is added by capture.
            slots = min(2, char["slots"]) if ascension else char["slots"]
            potions = [None] * slots
            if potions and native["synthetic_potions"] and rng.random() < config["potion_probability"]:
                potions[rng.randrange(len(potions))] = rng.choice(native["synthetic_potions"])
            while potions and potions[-1] is None:
                potions.pop()
            spec = dict(schema=2, character=char["name"], act=act, act_variant=variant,
                        encounter=encounter["id"], ascension=ascension,
                        seed=("LS" + token[:12]).upper(), hp=hp, max_hp=char["max_hp"],
                        relics=relics, potions=potions, deck=deck)
            jobs.append(dict(id=token[:20], source="synthetic", natural_reachability="unknown",
                             spec=spec, split=split, seed=spec["seed"], pair=token, recipe=recipe,
                             family=family, history=None, room=encounter["room"],
                             sampling=dict(group=list(group_key), encounter_options=len(options),
                                           initial_round_weight=weights.get(group_key[2], 1)/round_mass,
                                           proposal="balanced_without_replacement", hp_band=band)))
    return jobs


def native_cases(banks, excluded):
    result = []
    seen = set(excluded)
    blocked = read(HERE.parent / "m1-ls1/evidence/contract.json")["manifest"]
    blocked_history = {c["seed"] for c in blocked if c["split"] == "reachable"}
    for base in banks:
        source = read(base / "manifest.json")
        runs = {r["id"]: r for r in source["runs"]}
        restored = {r["root_id"] for r in source.get("validations", []) if r["status"] == "pass"}
        output = []
        for root in source["roots"]:
            if root["partition"] != "development" or root["id"] not in restored or root["seed"] in blocked_history:
                continue
            if root["identity"]["live"] in seen:
                continue
            checkpoint = base / root["checkpoint"]
            if checkpoint.parent != base or not checkpoint.is_file():
                raise ValueError("History bank checkpoint missing or outside its source")
            if sha256(checkpoint.read_bytes()).hexdigest() != root["checkpoint_sha256"]:
                raise ValueError("History bank checkpoint bytes differ")
            cards = [dict(id=c["id"].removeprefix("CARD."), upgrade=int(c["upgraded"]))
                     for c in root["public_root"]["player"]["deck"]]
            recipe = recipe_key(root["character"], cards)
            seen.add(root["identity"]["live"])
            spec = dict(character=root["character"], act=root["context"]["act"], act_variant=None,
                        encounter=root["identity"]["encounter"], seed=root["seed"], ascension=root["ascension"])
            output.append(dict(id=digest(["native", root["identity"]["live"]])[:20], source="native",
                               natural_reachability="assisted_history" if root["offline_teacher_assisted"] else "native_history",
                               split="development", seed=root["seed"], pair=root["history"], history=root["history"],
                               recipe=recipe, family=recipe, room=root["context"]["room_type"], spec=spec,
                               sampling=dict(proposal="admitted_development_history", probability=None,
                                             history_policy=runs[root["run_id"]]["spec"]),
                               restore=dict(bank=str(base), root=root, run=runs[root["run_id"]])))
        result.extend(output)
    return result


def check_splits(cases):
    seen = {}
    for c in cases:
        for field in ("recipe", "family", "seed", "pair", "history", "exact"):
            value = c.get(field)
            if value is not None and seen.setdefault((field, value), c["split"]) != c["split"]:
                raise ValueError(f"Split overlap: {field}")
    by_encounter = defaultdict(set)
    for case in cases:
        if case["source"] == "synthetic":
            by_encounter[case["spec"]["encounter"]].add(case["split"])
    if any(len(splits) != 1 for splits in by_encounter.values()):
        raise ValueError("Synthetic encounter crossed partitions")
