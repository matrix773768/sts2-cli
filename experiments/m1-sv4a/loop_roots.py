"""Freeze the two evaluation cohorts and four disjoint production reserves."""
from collections import Counter
from contextlib import closing
import json
from pathlib import Path

from loop_common import ROOT, checksum, digest, write_json
from sv_data import PRE1, db_for


def composition(spec):
    return tuple(sorted(card["id"] for card in spec["deck"]))


def reserved():
    previous = json.loads((ROOT / "experiments/m1-sv3a/config.json").read_bytes())
    combinations, seeds = set(), set()
    for relative in previous["sources"].values():
        with closing(db_for(ROOT / relative)) as db:
            for raw, in db.execute("SELECT recipe FROM private_tasks"):
                spec = json.loads(raw)
                combinations.add(composition(spec))
                seeds.add(spec["seed"])
    plans = [ROOT / "logs/m1-pre1-dev-freeze/dev.json",
             *(ROOT / "logs/m1-sv3a-roots" / f"{name}.json"
               for name in ("development", "confirmation", "experience"))]
    for path in plans:
        for _, spec, *_ in json.loads(path.read_bytes())["jobs"]:
            combinations.add(composition(spec))
            seeds.add(spec["seed"])
    return combinations, seeds, {path.relative_to(ROOT).as_posix():checksum(path) for path in plans}


def freeze(host, output, cfg):
    output.mkdir(parents=True, exist_ok=True)
    if (output / "identity.json").exists():
        identity = json.loads((output / "identity.json").read_bytes())
        if identity["config"] != cfg or identity["host"] != host.version:
            raise ValueError("Frozen cohort contract changed")
        for name, signature in identity["manifests"].items():
            if checksum(output / f"{name}.json") != signature:
                raise ValueError("Frozen cohort file changed")
        return identity
    lane = host.lane()
    try:
        lane.open()
        catalog = lane.request("synthetic_catalog")
    finally:
        host.close()
    combinations, seeds, excluded = reserved()
    base = json.loads((PRE1 / "dev-roots.json").read_bytes())
    frozen = {}
    for count, (name, size) in enumerate(dict(cfg["cohorts"], **cfg["experience_roots"]).items()):
        production = name in cfg["experience_roots"]
        rules = base | dict(version=f"ironclad.sv4a.{name}.v1", seed=cfg["seed"] + 100 + count,
                            policy_seed=cfg["seed"] + 200 + count, action_cap=cfg["action_cap"])
        jobs, ordinal = [], 0
        while len(jobs) < size:
            spec, _, family, room = host.runtime["root"](catalog, rules, ordinal)
            ordinal += 1
            comp = composition(spec)
            if comp in combinations or spec["seed"] in seeds:
                continue
            combinations.add(comp)
            seeds.add(spec["seed"])
            split = "validation" if int(family[:8],16) % cfg["validation_families"] == 0 else "train"
            jobs.append([len(jobs), spec, split if production else "evaluation", family, room])
        item = dict(config=rules, jobs=jobs, purpose=f"experience_{name}" if production else name,
                    host=host.version, split=dict(Counter(job[2] for job in jobs)), catalog=digest(catalog))
        path = output / f"{name}.json"
        write_json(path, item)
        frozen[name] = checksum(path)
    identity = dict(config=cfg, host=host.version, excluded=excluded, manifests=frozen)
    write_json(output / "identity.json", identity)
    return identity
