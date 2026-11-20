"""Generate reproducible, resource-free schema-3 roots from the current native catalog."""
import random

from nosl_experience import digest

DISTRIBUTION = "sts2.nosl.random-roots.v1"


def generate(catalog, seed, count, deck_min, deck_max, upgrade_rate, hp, max_hp=None):
    if not 1 <= deck_min <= deck_max or not 0 <= upgrade_rate <= 1 or count < 1:
        raise ValueError("Invalid root distribution")
    rng = random.Random(seed)
    acts = [(a["act"], a["variant"], e["id"]) for a in catalog["acts"] if a["act"] in (1, 2, 3)
            for e in a["encounters"] if e["room"] == "Monster"]
    for i in range(count):
        role = rng.choice(catalog["characters"])
        act, variant, encounter = rng.choice(acts)
        maximum = role["max_hp"] if max_hp is None else max_hp
        current = maximum if hp is None else hp
        if not 1 <= current <= maximum <= 999:
            raise ValueError("HP violates native schema-3 bounds")
        cards = rng.choices(role["cards"], k=rng.randint(deck_min, deck_max))
        spec = dict(schema=3, character=role["name"], act=act, act_variant=variant, encounter=encounter,
                    ascension=0, hp=current, max_hp=maximum, relics=[], potions=[],
                    seed=digest([DISTRIBUTION, seed, i])[:16].upper(),
                    deck=[dict(id=c["id"], upgrade=int(c["upgradable"] and rng.random() < upgrade_rate))
                          for c in cards])
        yield dict(distribution=DISTRIBUTION, generation_seed=seed, position=i, spec=spec,
                   catalogue_sha256=digest(catalog), status="catalogued")
