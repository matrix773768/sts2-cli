"""Freeze a synthetic crossed-deck manifest before any label generation."""
from collections import Counter
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "m1-n2e"))
from semantics import load_catalog, deck_from_root, digest

DOMAIN = "STS2-N2FA-OPEN-SYNTHETIC-V1"
FAMILIES = {
    "strength": ("Ironclad", ("INFLAME", "TWIN_STRIKE"), ("POMMEL_STRIKE", "SHRUG_IT_OFF", "IRON_WAVE", "BASH")),
    "shiv": ("Silent", ("ACCURACY", "BLADE_DANCE"), ("BACKFLIP", "FOOTWORK", "LEG_SWEEP", "SLICE")),
}
# Six background slots. Cross-split composition distance is checked across all arms.
RECIPES = {
    "train": [(3, 2, 1, 0), (2, 3, 1, 0), (3, 1, 2, 0), (2, 2, 2, 0), (1, 3, 2, 0)],
    "selection": [(0, 0, 3, 3), (0, 1, 2, 3)],
    "report": [(3, 0, 0, 3), (2, 0, 0, 4)],
}
ENCOUNTERS = ("BOWLBUGS_WEAK", "CHOMPERS_NORMAL")
IDENTITY_KEYS = ("game_sha256", "solver_sha256", "headless_sha256", "coreclr")
SEEDS = (17, 43, 101)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def file_hash(path):
    return sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def manifest():
    catalog = load_catalog()
    cases = []
    for (family, (character, mechanisms, background)), (split, recipes) in product(FAMILIES.items(), RECIPES.items()):
        suffix = character.upper()
        strike, defend = f"STRIKE_{suffix}", f"DEFEND_{suffix}"
        for i, counts in enumerate(recipes):
            group = f"{family}-{split}-{i}"
            cards = [dict(id=card, upgrade=int(j == 0 and count >= 2))
                     for card, count in zip(background, counts) for j in range(count)]
            armor = [dict(id=defend, upgrade=0)] * 4
            attacks = [dict(id=strike, upgrade=0)] * 3
            for e, encounter in enumerate(ENCOUNTERS):
                for seed_index in range(4):
                    # Four native replays reserve one entire report seed block.
                    if family == "shiv" and split == "report" and i == 1 and e == 1 and seed_index == 3:
                        continue
                    block = digest([DOMAIN, group, encounter, seed_index])
                    for a, b in product(range(2), repeat=2):
                        recipe = attacks + [dict(id=mechanisms[0] if a else defend, upgrade=0),
                                            dict(id=mechanisms[1] if b else strike, upgrade=0)] + cards + armor
                        hp = (35, 43, 51)[(i + e) % 3]
                        spec = dict(schema=2, character=character, ascension=0, act=2, act_variant="HIVE",
                                    encounter=encounter, seed=block[:12].upper(), hp=hp,
                                    max_hp=80 if family == "strength" else 70,
                                    relics=["BURNING_BLOOD" if family == "strength" else "RING_OF_THE_SNAKE"],
                                    potions=[None]*3, deck=recipe)
                        deck = deck_from_root(character, recipe)
                        encoded = catalog.encode_deck(deck, "identity")
                        for card in deck.cards:
                            if catalog.encode_card_instance(card)["qualification"] != "static_described":
                                raise ValueError(f"Unqualified deck member {card}")
                        case = dict(id=digest([block, a, b])[:16], split="development", cohort=split,
                                    template=group, family=family, slot_a=a, slot_b=b, pair=block,
                                    spec_sha256=digest(spec), deck_sha256=encoded["content_sha256"], spec=spec)
                        cases.append(dict(case=case, synthetic=True, natural_reachability="unknown"))
    verify(cases)
    return cases


def verify(cases):
    counts = Counter(item["case"]["cohort"] for item in cases)
    if counts != {"train": 320, "selection": 128, "report": 124}:
        raise ValueError(counts)
    seen = {}
    unique = {}
    for item in cases:
        c = item["case"]
        for field in ("template", "pair", "deck_sha256"):
            key = field, c[field]
            if seen.setdefault(key, c["cohort"]) != c["cohort"]:
                raise ValueError(f"Split overlap: {key}")
        key = c["template"], c["slot_a"], c["slot_b"]
        unique[key] = (c, Counter(card["id"] for card in c["spec"]["deck"]))
    for a, a_cards in unique.values():
        for b, b_cards in unique.values():
            if a["family"] == b["family"] and a["cohort"] != b["cohort"]:
                if sum((a_cards - b_cards).values()) < 2:
                    raise ValueError("Near-neighbor recipes cross splits")


def freeze():
    evidence = read(HERE.parent / "m1-n2d/native-audit.json")["versions"]
    model_path = HERE.parent / "m1-n2c/models.json"
    models = read(model_path)
    mean = next(model for model in models["models"] if model["id"] == "initial-mean")
    cases = manifest()
    protocol = dict(
        domain=DOMAIN, versions={key: evidence[key] for key in IDENTITY_KEYS},
        source_hashes={str(p.relative_to(ROOT)): file_hash(p) for p in
                       (model_path, HERE.parent / "m1-n2b/policy.py",
                        HERE.parent / "m1-n2e/cards.json", HERE.parent / "m1-n2e/schema.json",
                        HERE.parent / "m1-n2e/semantics.py", Path(__file__))},
        manifest_sha256=digest(cases), catalog_sha256=load_catalog().content_sha256,
        policy=mean, action_cap=96, potions=False, execution_budget=576, audit_roots=4,
        split_counts={"train": 320, "selection": 128, "report": 124},
        input_context=["hp", "max_hp", "character", "encounter", "ascension", "act", "relics", "potions"],
        input_deck={"statistics": "counts, upgrades, mean cost, aggregate immediate node amounts",
                    "identity": "ID, upgrade and counts",
                    "mechanics": "ordered node kind, amount, count, target, power, duration, family, qualification"},
        training=dict(engine="NumPy CPU full-batch Adam", hidden=12, card_dim=128, seeds=SEEDS,
                      epochs=[30, 90, 180], learning_rate=.015, l2=.002, subsample_groups=[2, 4, 10],
                      selection="Brier on selection groups, then shorter epoch; average three seeds",
                      training_wall_limit_seconds=120),
        metrics=["Brier", "log loss", "calibration bins", "paired factorial contrast", "group bootstrap",
                 "P50/P95 inference", "coverage", "winning locked HP descriptive"],
        stop={"min_train_coverage": .85, "min_class_fraction": .10,
              "known_major_label_mismatch": "stop before model fit",
              "no_replays": True, "audit": "first train D00 and D11 per family, first encounter, seed 0"},
    )
    save(HERE / "protocol.json", protocol)
    save(HERE / "manifest.json", cases)


if __name__ == "__main__":
    freeze()
