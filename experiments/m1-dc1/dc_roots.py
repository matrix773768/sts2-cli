"""Build legal combat recipes, with isolated deck compositions and repeatable worlds."""
from collections import Counter
import random

from dc_common import PRIOR, checksum, digest, frozen, read
from loop_roots import composition, reserved

BASIC = {"STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH"}
DRAW = frozenset("POMMEL_STRIKE SHRUG_IT_OFF BATTLE_TRANCE BURNING_PACT SETUP_STRIKE OFFERING DARK_EMBRACE PILLAGE".split())
ENERGY = frozenset("BLOODLETTING OFFERING FORGOTTEN_RITUAL EXPECT_A_FIGHT PYRE".split())
COST = frozenset("CORRUPTION JUGGLING INFERNAL_BLADE ARMAMENTS".split()) - {"ARMAMENTS"}
GROWTH = frozenset("INFLAME DEMON_FORM RUPTURE FIGHT_ME BRAND FEED RAMPAGE ASHEN_STRIKE TEAR_ASUNDER STONE_ARMOR".split())
MULTIHIT = frozenset("TWIN_STRIKE SWORD_BOOMERANG WHIRLWIND FIEND_FIRE TEAR_ASUNDER".split())
EXHAUST = frozenset("BURNING_PACT TRUE_GRIT SECOND_WIND FIEND_FIRE OFFERING IMPERVIOUS CORRUPTION STOKE".split())
PAYOFF = frozenset("FEEL_NO_PAIN DARK_EMBRACE ASHEN_STRIKE FORGOTTEN_RITUAL".split())
PILE = frozenset("HEADBUTT WARCRY HAVOC BURNING_PACT STOKE".split())
REPEAT = frozenset("ANGER HEADBUTT RAMPAGE OUTRAGE HOWL_FROM_BEYOND ONE_TWO_PUNCH AGGRESSION".split())
BLOCK = frozenset("SHRUG_IT_OFF IRON_WAVE FLAME_BARRIER TRUE_GRIT BLOOD_WALL SECOND_WIND IMPERVIOUS COLOSSUS STONE_ARMOR RAGE UNMOVABLE TREMBLE".split())
ATTACK = "IRON_WAVE TWIN_STRIKE UPPERCUT THUNDERCLAP POMMEL_STRIKE HEADBUTT MOLTEN_FIST SWORD_BOOMERANG HEMOKINESIS WHIRLWIND CINDER FIGHT_ME".split()
DEFENSE = "SHRUG_IT_OFF FLAME_BARRIER TRUE_GRIT BLOOD_WALL COLOSSUS STONE_ARMOR IRON_WAVE UNMOVABLE".split()
SUPPORT = "ARMAMENTS BATTLE_TRANCE BURNING_PACT BLOODLETTING INFLAME SETUP_STRIKE RAMPAGE EXPECT_A_FIGHT".split()
PACKAGES = {
    "exhaust-draw": "DARK_EMBRACE BURNING_PACT SECOND_WIND FEEL_NO_PAIN ASHEN_STRIKE",
    "draw-energy": "OFFERING BLOODLETTING BATTLE_TRANCE WHIRLWIND POMMEL_STRIKE",
    "block-carry": "BARRICADE BODY_SLAM IMPERVIOUS FLAME_BARRIER SHRUG_IT_OFF",
    "hp-strength-multihit": "RUPTURE HEMOKINESIS BLOODLETTING BLOOD_WALL SWORD_BOOMERANG",
    "exhaust-energy": "FORGOTTEN_RITUAL TRUE_GRIT STOKE WHIRLWIND EVIL_EYE",
    "topdeck-repeat": "HEADBUTT RAMPAGE HAVOC POMMEL_STRIKE ONE_TWO_PUNCH",
    "zero-cost-exhaust": "CORRUPTION BURNING_PACT FEEL_NO_PAIN ASHEN_STRIKE SECOND_WIND",
    "strength-multihit": "DEMON_FORM TWIN_STRIKE SWORD_BOOMERANG SHRUG_IT_OFF EXPECT_A_FIGHT",
}
MECHANICS = dict(draw=DRAW, energy=ENERGY, cost_change=COST, growth=GROWTH, multihit=MULTIHIT,
                 exhaust=EXHAUST, exhaust_payoff=PAYOFF, pile_control=PILE, repeat=REPEAT, block=BLOCK)
SOURCES = ("foundation", "synthetic-normal", "synthetic-synergy", "mechanism-pressure")
ROOMS = ("Monster", "Elite", "Boss")


def static(deck, catalog):
    counts = Counter(c["id"] for c in deck)
    by_type, rarity = Counter(), Counter()
    for card, count in counts.items():
        by_type[catalog.get(card, {}).get("type", "unknown")] += count
        rarity[catalog.get(card, {}).get("rarity", "unknown")] += count
    flags = {name: sum(counts[k] for k in card_ids) for name, card_ids in MECHANICS.items()}
    links = [name for name, left, right in (
        ("draw-energy", "draw", "energy"), ("exhaust-trigger", "exhaust", "exhaust_payoff"),
        ("growth-multihit", "growth", "multihit"), ("pile-repeat", "pile_control", "repeat"),
        ("cost-exhaust", "cost_change", "exhaust"))
        if flags[left] and flags[right]]
    if counts["BARRICADE"] and counts["BODY_SLAM"] and flags["block"]:
        links.append("block-carry")
    return dict(size=len(deck), unique=len(counts), card_types=by_type, rarity=rarity, basics=sum(counts[k] for k in BASIC),
                strikes=counts["STRIKE_IRONCLAD"], defends=counts["DEFEND_IRONCLAD"], bash=counts["BASH"],
                upgraded=sum(bool(c["upgrade"]) for c in deck), mechanics=flags, interactions=links)


def world(spec, cfg, family, repeat, channel="main"):
    return spec | {"seed": digest([cfg["version"], cfg["seed"], channel, family, repeat])[:16].upper()}


def manifest(cfg, name, jobs):
    return dict(config={"version": cfg["version"], "action_cap": cfg["action_cap"], "policy_seed": cfg["seed"]},
                purpose=name, jobs=jobs)


def deck_for(role, pool, act, source, package, rng):
    starter = list(role["starter"])
    if source == "foundation":
        historical = [card for card, row in pool.items() if row["rarity"] != "Ancient"]
        return rng.choices(historical, k=rng.randint(12, 20)), .25
    strikes = rng.randint(0, min(4, act + 1))
    defends = rng.randint(0, act)
    for card, count in (("STRIKE_IRONCLAD", strikes), ("DEFEND_IRONCLAD", defends)):
        for _ in range(min(count, starter.count(card))):
            starter.remove(card)
    core = PACKAGES[package].split() if package else [rng.choice(SUPPORT)]
    if package == "zero-cost-exhaust":
        # Corruption is an Ancient card. It stays in the synthetic pressure stratum.
        if source != "mechanism-pressure":
            raise ValueError("Ancient card outside pressure stratum")
    cards = starter + core + [rng.choice(ATTACK), rng.choice(DEFENSE)]
    if act > 1:
        cards += [rng.choice(ATTACK), rng.choice(DEFENSE), rng.choice(SUPPORT)]
    rare_cap = (1, 2, 3)[act - 1] + (source == "mechanism-pressure")
    if sum(pool[card]["rarity"] == "Rare" for card in cards) > rare_cap:
        # An engine that needs two rare cards is reserved for later acts.
        return [], 0
    target = rng.randint(*((13, 17), (17, 22), (20, 25))[act-1])
    while len(cards) < target:
        candidates = [c for c in ATTACK + DEFENSE + SUPPORT
                      if cards.count(c) < 3]
        cards.append(rng.choice(candidates))
    return cards, (.18, .30, .42)[act-1]


def freeze(host, output, cfg):
    output.mkdir(parents=True, exist_ok=True)
    index = output / "identity.json"
    if index.exists():
        value = read(index)
        if value["config"] != cfg or value["host"] != host.version:
            raise ValueError("Frozen DC1 identity differs")
        for name, signature in value["files"].items():
            if checksum(output / name) != signature:
                raise ValueError(f"Frozen root asset differs: {name}")
        return value
    try:
        lane = host.lane()
        lane.open()
        catalog = lane.request("synthetic_catalog")
    finally:
        host.close()
    frozen(output / "catalog.json", catalog)
    role, = (row for row in catalog["characters"] if row["name"] == "Ironclad")
    cards = {c["id"]: c for c in role["cards"]}
    deck_pool = {k: v for k, v in cards.items() if k not in {"DEMONIC_SHIELD", "TAG_TEAM", "TANK"}}
    rooms = {(act, room): [(a["variant"], e["id"]) for a in catalog["acts"] if a["act"] == act
                          for e in a["encounters"] if e["room"] == room]
             for act in (1, 2, 3) for room in ROOMS}
    old_decks, seeds, excluded = reserved()
    for path in sorted((PRIOR / "roots").glob("*.json")):
        for _, spec, *_ in read(path).get("jobs", []):
            old_decks.add(composition(spec))
            seeds.add(spec["seed"])
        excluded[path.relative_to(PRIOR.parent.parent).as_posix()] = checksum(path)
    families, files, examined = [], ["catalog.json"], []
    for split, (size, repeats) in cfg["pools"].items():
        jobs, controls = [], []
        control_slots = {int(i * size / cfg["control_families_per_pool"]) + i % 4
                         for i in range(cfg["control_families_per_pool"])}
        for i in range(size):
            decade = i // 4
            source = SOURCES[i % 4]
            act = 1 + decade % 3
            room = ROOMS[(decade // 3) % 3]
            advance = decade // 9
            for retry in range(2000):
                rng = random.Random(digest([cfg["seed"], split, i, retry]))
                package = None
                if source in ("synthetic-synergy", "mechanism-pressure"):
                    allowed = [key for key in PACKAGES if (key != "zero-cost-exhaust" or source == "mechanism-pressure")
                               and (act > 1 or key != "block-carry")]
                    package = allowed[(advance + decade % 3 + (source == "mechanism-pressure")) % len(allowed)]
                names, rate = deck_for(role, deck_pool, act, source, package, rng)
                if not names:
                    continue
                comp = tuple(sorted(names))
                if comp in old_decks:
                    continue
                detailed = Counter(name for name in names if name not in BASIC)
                if any(split != owner and sum((detailed & previous).values()) >
                       cfg["near_duplicate_jaccard"] * sum((detailed | previous).values())
                       for owner, previous in examined if detailed.keys() & previous.keys()):
                    continue
                break
            else:
                raise RuntimeError(f"Could not construct isolated deck {split}/{i}")
            examined.append((split, detailed))
            old_decks.add(comp)
            rng.shuffle(names)
            deck = [dict(id=name, upgrade=int(deck_pool[name]["upgradable"] and rng.random() < rate)) for name in names]
            variant, encounter = rng.choice(rooms[act, room])
            max_hp = role["max_hp"]
            hp_band = (decade // 3 + i % 4) % 3
            hp = (max_hp, round(.8 * max_hp), round(.55 * max_hp))[hp_band]
            if source == "mechanism-pressure":
                hp = max_hp = (160, 999)[advance % 2]
            spec = dict(schema=3, character="Ironclad", ascension=0, act=act, act_variant=variant,
                        encounter=encounter, hp=hp, max_hp=max_hp, relics=[], potions=[], deck=deck)
            deck_id, family = digest(comp), digest(spec)
            family_jobs = []
            for repeat in range(repeats):
                private = world(spec, cfg, family, repeat)
                if private["seed"] in seeds:
                    raise ValueError("A world seed is reused")
                seeds.add(private["seed"])
                job = [len(jobs), private, split, family, room]
                jobs.append(job)
                family_jobs.append(job[0])
                if i in control_slots:
                    controls.append(job)
            families.append(dict(id=family, deck_family=deck_id, split=split, source=source,
                                 package=package, room=room, spec=spec, worlds=family_jobs,
                                 static=static(deck, cards)))
        for name, subset in ((split, jobs), (f"{split}-controls", controls)):
            frozen(output / f"{name}.json", manifest(cfg, name, subset))
            files.append(f"{name}.json")
    # Postcondition covers unordered deck identity, HP/encounter conditions, and worlds.
    for key in ("id", "deck_family"):
        if len({row[key] for row in families}) != len(families):
            raise ValueError(f"Duplicate {key}")
    frozen(output / "families.json", families)
    files.append("families.json")
    value = dict(config=cfg, host=host.version, excluded=excluded,
                 files={name: checksum(output/name) for name in files})
    frozen(index, value)
    return value
