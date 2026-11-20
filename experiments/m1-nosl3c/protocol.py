"""No-potion, no-relic stratified synthetic protocol."""
from collections import Counter
import json
from pathlib import Path
import math
import random
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "m1-nosl3b"))
from nosl3b_protocol import digest

VERSION = "sts2.nosl3c.no_resources.v1"
DATA_VERSION = "sts2.nosl3c.episode.v1"
MODEL_VERSION = "nosl3c.mechanism-actor-critic.no-resources.v1"
BANDS = ("easy", "medium", "hard")


def read(path):
    data = json.loads(Path(path).read_bytes())
    if data["schema"] != VERSION:
        raise ValueError("Unknown NOSL3C protocol")
    for group in ("train", "selection", "report"):
        if not data[group]:
            raise ValueError(f"Empty recipe partition: {group}")
    sets = [data[k] for k in ("train", "selection", "report")]
    recipes = [recipe for group in sets for recipe in group]
    if len(recipes) != len({r["family"] for r in recipes}):
        raise ValueError("Recipe families must be disjoint")
    decks = {(r["character"], tuple(sorted(Counter(r["cards"]).items()))) for r in recipes}
    if len(decks) != len(recipes):
        raise ValueError("Recipe decks must be disjoint")
    for key, maximum in (("updates", 1000000), ("roots_per_update", 1024), ("traces_per_root", 32),
                         ("review_interval", 10000), ("workers", 16), ("worker_root_limit", 1000),
                         ("action_cap", 2048), ("evaluation_reps", 64), ("decision_cache", 2048)):
        if type(data[key]) is not int or not 1 <= data[key] <= maximum:
            raise ValueError(f"Invalid {key}")
    if (data["hp_weight"], data["potion_weight"]) != (.12, 0):
        raise ValueError("No-resource utility requires fixed terminal weights")
    if not all(math.isfinite(data[k]) and 0 < data[k] <= 1 for k in ("min_qualified", "max_fault_fraction")):
        raise ValueError("Invalid qualification thresholds")
    if type(data["resident"]) is not bool or not math.isfinite(data["max_train_seconds"]) or data["max_train_seconds"] < 0:
        raise ValueError("Invalid worker or time-budget configuration")
    return data


def root(config, partition, position):
    recipe_group = config["train"] if partition == "bench" else config[partition]
    index = position % len(recipe_group)
    cycle = position // len(recipe_group)
    recipe = recipe_group[index]
    band = BANDS[(index + cycle) % len(BANDS)]
    key = digest([config["domain"], partition, position, recipe["family"]])
    role = recipe["character"]
    deck = [dict(id=c, upgrade=int(i == 2 and (index + cycle) % 2 == 0)) for i, c in enumerate(recipe["cards"])]
    random.Random(key).shuffle(deck)
    return dict(id=key[:24], group=partition, family=recipe["family"], encounter=recipe["encounter"],
                character=role, act=recipe["act"], pressure=band, position=position,
                spec=dict(schema=2, character=role, ascension=0, act=recipe["act"],
                          act_variant=recipe["zone"], encounter=recipe["encounter"], seed=key[24:36].upper(),
                          hp=config["pressure"][band][role], max_hp=80 if role == "Ironclad" else 70,
                          relics=[], potions=[], deck=deck))


def policy_seed(config, item, mode, replicate, stage):
    # Counter-addressed RNG. Resume reproduces an uncommitted episode from its seed;
    # committed episodes are loaded from the ledger.
    return digest([config["policy_seed"], item["id"], mode, replicate,
                   stage if item["group"] == "train" else "paired-evaluation"])