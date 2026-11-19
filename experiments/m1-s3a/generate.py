"""Generate only the frozen development pilot from the versioned recipe."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import random

HERE = Path(__file__).resolve().parent
TEMPLATES = {
    "growth": ("Ironclad", ["RAMPAGE", "RAMPAGE", "SHRUG_IT_OFF", "POMMEL_STRIKE", "BASH"]),
    "strength": ("Ironclad", ["INFLAME", "TWIN_STRIKE", "TWIN_STRIKE", "POMMEL_STRIKE", "BASH"]),
    "special_defense": ("Ironclad", ["FLAME_BARRIER", "FLAME_BARRIER", "SHRUG_IT_OFF", "BASH", "TWIN_STRIKE"]),
    "cycle": ("Silent", ["ACROBATICS", "BACKFLIP", "BACKFLIP", "PREDATOR", "SURVIVOR"]),
    "poison": ("Silent", ["NOXIOUS_FUMES", "DEADLY_POISON", "BOUNCING_FLASK", "POISONED_STAB", "BACKFLIP"]),
    "opening": ("Silent", ["BACKSTAB", "BACKSTAB", "PREDATOR", "BLADE_DANCE", "DODGE_AND_ROLL"]),
}


def generate(plan, catalog, replicates=None):
    chars = {c["name"]: c for c in catalog["characters"]}
    encounters = next(a["encounters"] for a in catalog["acts"]
                      if (a["act"], a["variant"]) == (plan["act"], plan["variant"]))
    ordinary = {e["id"] for e in encounters if e["room"] == "Monster"}
    names = [e for es in plan["splits"].values() for e in es]
    if len(names) != len(set(names)) or set(names) - ordinary:
        raise ValueError("Plan encounters must be disjoint native ordinary encounters")
    if len(names) * len(TEMPLATES) * plan["replicates_per_template_encounter"] != plan["planned_total"]:
        raise ValueError("Plan cardinality differs")
    cases = []
    if replicates is None:
        replicates = [plan["pilot_replicate"]]
    if len(set(replicates)) != len(replicates) or any(
            not 0 <= replicate < plan["replicates_per_template_encounter"] for replicate in replicates):
        raise ValueError("Invalid development replicate indices")
    pressures = tuple(plan["pressure"])
    for replicate in replicates:
        for e, encounter in enumerate(plan["splits"]["development"]):
            for t, (template, (character, anchors)) in enumerate(TEMPLATES.items()):
                key = f"{plan['seed_namespace']}:{plan['generator_seed']}:{encounter}:{template}:{replicate}"
                token = hashlib.sha256(key.encode()).hexdigest()
                rng = random.Random(int(token, 16))
                tier = pressures[(e + t + replicate) % len(pressures)]
                char = chars[character]
                entries = {c["id"]: c for c in char["cards"]}
                base = character.upper()
                cards = list(anchors)
                for i in range(rng.randint(*plan["deck_size"]) - len(cards)):
                    cards.append(f"{'STRIKE' if i % 2 == 0 else 'DEFEND'}_{base}")
                rng.shuffle(cards)
                pool = [i for i, name in enumerate(cards) if entries[name]["upgradable"]]
                upgrades = set(rng.sample(pool, rng.randint(0, plan["upgrade_max"])))
                stocked = tier == "control"
                spec = dict(schema=2, act=plan["act"], act_variant=plan["variant"], character=character,
                            encounter=encounter, ascension=rng.choice(plan["ascension"]), seed="S3A" + token[:12].upper(),
                            hp=rng.randint(*plan["pressure"][tier]), max_hp=char["max_hp"],
                            deck=[dict(id=name, upgrade=int(i in upgrades)) for i, name in enumerate(cards)],
                            relics=char["relics"] if stocked else [],
                            potions=["FLEX_POTION", None, None] if stocked else [None, None, None])
                cases.append(dict(id=token[:16], split="development", complexity=tier, template=template,
                                  generation_source="s3a_independent_synthetic", replicate=replicate,
                                  refine=(e == t % len(plan["splits"]["development"])), spec=spec))
    return dict(input_schema=1, cases=cases, sequence=[c["id"] for c in cases])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--replicates", nargs="+", type=int)
    args = parser.parse_args()
    plan = json.loads((HERE / "plan.json").read_text(encoding="utf-8-sig"))
    if args.catalog.suffix == ".gz":
        with gzip.open(args.catalog, "rt", encoding="utf-8") as stream:
            catalog = json.load(stream)
    else:
        catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    data = generate(plan, catalog, args.replicates)
    args.output.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
