"""Fixed recipes, group separation, and reproducible stratified root construction."""
from collections import Counter
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3a"))
from nosl_experience import digest

PARTITIONS = ("train", "regular", "combination")
PRESSURES = ("easy", "medium", "hard")


def validate(config):
    if config["schema"] != "sts2.nosl3b.protocol.v1":
        raise ValueError("Unexpected protocol version")
    seeds = config["initialization_seeds"]
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("Initialization seeds must be nonempty and unique")
    recipes = [recipe for split in PARTITIONS for recipe in config[split]]
    if len({r["family"] for r in recipes}) != len(recipes):
        raise ValueError("Family identifiers overlap")
    if len({(r["character"], tuple(sorted(Counter(r["cards"]).items()))) for r in recipes}) != len(recipes):
        raise ValueError("Card multisets overlap")
    train = [set(r["cards"]) for r in config["train"]]
    for recipe in config["combination"]:
        pair = set(recipe["pair"])
        if len(pair) != 2 or not pair <= set(recipe["cards"]):
            raise ValueError("Invalid held-out interaction")
        if not pair <= set.union(*train) or any(pair <= cards for cards in train):
            raise ValueError("Interaction must be represented separately in training")
    if "schedule" in config:
        schedule = config["schedule"]
        if schedule["checkpoints"] != sorted(set(schedule["checkpoints"])):
            raise ValueError("Checkpoints must be unique and increasing")
        if (schedule["checkpoints"][0] != 0 or schedule["checkpoints"][-1] != schedule["updates"]
                or schedule["attempts_per_family_per_update"] < 1):
            raise ValueError("Invalid stage coverage")


def roots(config, split, update=0, pilot=False):
    reps = 2 if pilot else (config["schedule"]["attempts_per_family_per_update"] if split == "train"
                             else config["report_reps_per_family"])
    for index, recipe in enumerate(config[split]):
        for rep in range(reps):
            ordinal = update * reps + rep
            if pilot:
                band = ("easy", "hard")[rep]
            elif split == "train":
                band = PRESSURES[(index + ordinal) % len(PRESSURES)]
            else:
                band = PRESSURES[(index + rep) % len(PRESSURES)]
            stocked = (index + (rep if pilot or split != "train" else ordinal // 3)) % 2 == 0
            character = recipe["character"]
            key = digest([config["domain"], "pilot" if pilot else "formal", split, recipe["family"], update, rep])
            deck = [dict(id=card, upgrade=int(slot == 2 and (index + ordinal) % 2 == 0))
                    for slot, card in enumerate(recipe["cards"])]
            random.Random(key).shuffle(deck)
            spec = dict(schema=2, character=character, ascension=0, act=recipe["act"],
                        act_variant=recipe["zone"], encounter=recipe["encounter"],
                        seed=key[16:28].upper(), hp=config["pressure"][band][character],
                        max_hp=80 if character == "Ironclad" else 70, relics=[],
                        potions=["FLEX_POTION" if stocked else None], deck=deck)
            yield dict(id=key[:16], group="pilot" if pilot else split, recipe_split=split, family=recipe["family"],
                       character=character, encounter=recipe["encounter"], act=recipe["act"],
                       pressure=band, stocked=stocked, pair=recipe.get("pair"), spec=spec)
