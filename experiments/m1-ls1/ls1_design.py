"""Predeclared construction families and independently grouped research roots."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "m1-n2e"))
from semantics import digest

def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

PROTOCOL = read(HERE / "protocol.json")
STRATEGIES = tuple(PROTOCOL["initial_strategies"])
RECIPE = {
    "Ironclad": {
        "train": [
            "INFLAME TWIN_STRIKE TWIN_STRIKE IRON_WAVE",
            "INFLAME TWIN_STRIKE POMMEL_STRIKE POMMEL_STRIKE",
            "INFLAME INFLAME BASH TWIN_STRIKE",
            "BASH BASH IRON_WAVE SHRUG_IT_OFF",
        ],
        "selection": ["INFLAME SHRUG_IT_OFF SHRUG_IT_OFF TWIN_STRIKE"],
        "report": [
            "TWIN_STRIKE TWIN_STRIKE TWIN_STRIKE SHRUG_IT_OFF",
            "INFLAME INFLAME IRON_WAVE POMMEL_STRIKE",
            "BASH POMMEL_STRIKE SHRUG_IT_OFF SHRUG_IT_OFF",
        ],
        "feedback": ["IRON_WAVE IRON_WAVE IRON_WAVE POMMEL_STRIKE"],
        "pilot": ["INFLAME TWIN_STRIKE BASH SHRUG_IT_OFF"],
    },
    "Silent": {
        "train": [
            "ACCURACY BLADE_DANCE BLADE_DANCE SLICE",
            "ACCURACY BLADE_DANCE BACKFLIP BACKFLIP",
            "BLADE_DANCE CLOAK_AND_DAGGER CLOAK_AND_DAGGER SLICE",
            "FOOTWORK FOOTWORK LEG_SWEEP SLICE",
        ],
        "selection": ["ACCURACY ACCURACY CLOAK_AND_DAGGER CLOAK_AND_DAGGER"],
        "report": [
            "BLADE_DANCE BLADE_DANCE BLADE_DANCE CLOAK_AND_DAGGER",
            "ACCURACY ACCURACY BLADE_DANCE LEG_SWEEP",
            "FOOTWORK BACKFLIP BACKFLIP LEG_SWEEP",
        ],
        "feedback": ["ACCURACY SLICE SLICE CLOAK_AND_DAGGER"],
        "pilot": ["ACCURACY BLADE_DANCE CLOAK_AND_DAGGER BACKFLIP"],
    },
}
ENCOUNTERS = ("BOWLBUGS_WEAK", "CHOMPERS_NORMAL", "TUNNELER_WEAK", "EXOSKELETONS_WEAK")


def file_hash(path, normalize=False):
    data = path.read_bytes()
    return sha256(data.replace(b"\r\n", b"\n") if normalize else data).hexdigest()


def manifest():
    result = []
    for character, splits in RECIPE.items():
        iron = character == "Ironclad"
        for split, recipes in splits.items():
            encounters = {
                "train": (0, 1, 0, 1, 0, 1), "selection": (0, 1, 0, 1, 0, 1),
                "report": (0, 1, 2, 3), "feedback": (0, 1, 2, 3), "pilot": (0, 1),
            }[split]
            for recipe in recipes:
                core = recipe.split()
                family = digest([character, sorted(core)])
                for i, encounter_idx in enumerate(encounters):
                    key = digest([PROTOCOL["domain"], family, i])
                    deck = core + [f"STRIKE_{character.upper()}"] * (3 + i % 2)
                    deck += [f"DEFEND_{character.upper()}"] * (2 + i // 2)
                    spec = dict(schema=2, character=character, ascension=0, act=2, act_variant="HIVE",
                                encounter=ENCOUNTERS[encounter_idx], seed=key[:12].upper(),
                                hp=(30, 56, 40, 64, 34, 49)[i], max_hp=80 if iron else 70,
                                relics=(["BURNING_BLOOD" if iron else "RING_OF_THE_SNAKE"] if i % 3 != 0 else []),
                                potions=[None, "FLEX_POTION" if i % 2 else None,
                                         "DEXTERITY_POTION" if i % 3 == 2 else None],
                                deck=[dict(id=card, upgrade=int(i % 3 != 0 and j == i % len(core)))
                                      for j, card in enumerate(deck)])
                    result.append(dict(id=key[:16], split=split, family=family, pair=key,
                                       history=None, seed=spec["seed"], source="synthetic",
                                       natural_reachability="unknown", spec=spec,
                                       recipe=recipe_key(character, spec["deck"])))
    pinned = read(HERE.parent / "m1-f3a/manifest.json")["roots"]
    for root in pinned[:2]:
        deck = root["public_root"]["player"]["deck"]
        cards = [dict(id=card["id"].removeprefix("CARD."), upgrade=int(card["upgraded"])) for card in deck]
        result.append(dict(id=root["id"], split="reachable", family=root["source_group"],
                           pair=root["seed"], history=root["source_group"], seed=root["seed"],
                           source="F3A", natural_reachability="assisted_history",
                           checkpoint_sha256=root["checkpoint_sha256"],
                           recipe=recipe_key(root["character"], cards)))
    verify_groups(result)
    return result


def recipe_key(character, cards):
    return digest([character, sorted(Counter(c["id"] for c in cards).items())])


def verify_groups(items):
    membership = {}
    ids = set()
    for item in items:
        if item["id"] in ids:
            raise ValueError("Duplicate root id")
        ids.add(item["id"])
        for field in ("recipe", "family", "history", "seed", "pair", "checkpoint_sha256", "root_stamp"):
            value = item.get(field)
            if value is not None and membership.setdefault((field, value), item["split"]) != item["split"]:
                raise ValueError(f"Cross-split overlap: {field} {value}")
