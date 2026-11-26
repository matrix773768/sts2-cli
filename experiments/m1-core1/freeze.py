"""Freeze shared CORE evaluation units before search. No challenge input."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def key(text):
    return hashlib.sha256(text.encode()).hexdigest()


def recipe(job,domain,ordinal):
    spec=job["spec"]
    if domain=="natural":
        return spec
    if domain=="hard":
        return spec | dict(hp=min(24,spec["hp"]))
    if domain!="cross":
        raise ValueError(domain)
    encounter,act,variant=[
        ("FOSSIL_STALKER_NORMAL",1,"UNDERDOCKS"),("PUNCH_CONSTRUCT_NORMAL",1,"UNDERDOCKS"),
        ("SNAPPING_JAXFRUIT_NORMAL",1,"OVERGROWTH"),("TUNNELER_WEAK",2,"HIVE")][ordinal%4]
    return spec | dict(encounter=encounter,act=act,act_variant=variant)


def freeze():
    source = ROOT / "logs/m1-dc1-formal/roots/development.json"
    jobs = json.loads(source.read_bytes())["jobs"]
    used = set()
    rows = []
    for j in sorted(jobs, key=lambda j: key("core0-v1/" + j[3] + "/" + str(j[0]))):
        _, spec, _, family, room = j
        deck = tuple(sorted(c["id"] for c in spec["deck"]))
        if family in used or deck in used:
            continue
        used.update([family, deck])
        i = len(rows)
        spec = spec | dict(seed=key("core0-anchor/" + family)[:16].upper())
        rows.append(dict(family=family, split="development" if i % 2 == 0 else "confirmation",
                         source_row=j[0], room=room, spec=spec))
        if len(rows) == 48:
            break
    assert len(rows) == 48
    return dict(version="core0-v1", source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                model_sha256="1077c191586885c49173afe5801849b3ea6a4535425731e27226fe1978abf084",
                baselines={"g2":0,"g2-search":24}, search_depth=8, action_cap=128,
                domains={"natural":"unchanged recipe", "hard":"same recipe hp=min(hp,24)",
                         "cross":"same deck and resources, rotate across the frozen transfer encounters"},
                transfer=["FOSSIL_STALKER_NORMAL","PUNCH_CONSTRUCT_NORMAL","SNAPPING_JAXFRUIT_NORMAL","TUNNELER_WEAK"],
                jobs=rows)


if __name__ == "__main__":
    with (HERE/"benchmark.json").open("x") as f:
        json.dump(freeze(), f, indent=1)
