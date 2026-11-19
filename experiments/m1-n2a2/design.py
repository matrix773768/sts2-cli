"""Generate the fixed, development-only N2A.2 factorial design."""
import hashlib
import json
from pathlib import Path
import random

HERE = Path(__file__).resolve().parent
DOMAIN = "STS2-N2A2-OPEN-V1"
ENCOUNTERS = (
    ("train", 1, "OVERGROWTH", "SHRINKER_BEETLE_WEAK"),
    ("train", 1, "UNDERDOCKS", "CORPSE_SLUGS_WEAK"),
    ("train", 2, "HIVE", "BOWLBUGS_NORMAL"),
    ("train", 2, "HIVE", "MYTES_NORMAL"),
    ("selection", 1, "OVERGROWTH", "NIBBITS_WEAK"),
    ("selection", 2, "HIVE", "EXOSKELETONS_NORMAL"),
    ("report", 2, "HIVE", "BOWLBUGS_WEAK"),
    ("report", 2, "HIVE", "CHOMPERS_NORMAL"),
)
BUILDS = {
    "strength": ("Ironclad", "BASH INFLAME TWIN_STRIKE TWIN_STRIKE POMMEL_STRIKE SHRUG_IT_OFF"),
    "barrier": ("Ironclad", "BASH FLAME_BARRIER FLAME_BARRIER TWIN_STRIKE SHRUG_IT_OFF IRON_WAVE"),
    "shiv": ("Silent", "SURVIVOR BLADE_DANCE BLADE_DANCE ACCURACY CLOAK_AND_DAGGER SLICE"),
    "dexterity": ("Silent", "SURVIVOR FOOTWORK DODGE_AND_ROLL LEG_SWEEP PREDATOR SLICE"),
}


def stamp(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def generate():
    for split, act, variant, encounter in ENCOUNTERS:
        for build, (character, core) in BUILDS.items():
            for pressure, hp in (("low_hp", 30), ("mid_hp", 46), ("stocked", 62)):
                key = stamp([DOMAIN, split, encounter, build, pressure])
                rng = random.Random(int(key, 16))
                suffix = character.upper()
                cards = core.split() + [f"STRIKE_{suffix}"] * 4 + [f"DEFEND_{suffix}"] * 4
                deck = [dict(id=card, upgrade=int(i == 2)) for i, card in enumerate(cards)]
                rng.shuffle(deck)
                relic = "BURNING_BLOOD" if character == "Ironclad" else "RING_OF_THE_SNAKE"
                spec = dict(schema=2, character=character, ascension=0, act=act,
                            act_variant=variant, encounter=encounter, seed=key[:12].upper(),
                            hp=hp, max_hp=80 if character == "Ironclad" else 70,
                            relics=[relic] if pressure == "stocked" else [], potions=[None] * 3, deck=deck)
                case = dict(id=key[:16], spec_sha256=stamp(spec), split="development",
                            cohort=split, template=build, complexity=pressure, spec=spec)
                yield dict(case=case, synthetic=True, natural_reachability="unknown")


if __name__ == "__main__":
    print(json.dumps(dict(domain=DOMAIN, cases=list(generate())), indent=2))
