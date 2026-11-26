"""Bounded paired episodes. Private recipes are used only to initialize the simulator."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import random
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent/"m1-dc2b"))
from value import checksum, expected, load, torch
from battle import Controller, Policy
from dc_common import config, digest
from loop_battle import Host, collect
from sv_runtime import tensors

PARENT = ROOT/"logs/inf1/jobs/dc2b-night1-hf1/g2-fit/best.pt"
PARENT_SHA = "1077c191586885c49173afe5801849b3ea6a4535425731e27226fe1978abf084"
CFG = config() | dict(workers=1, direct_stop_margin=0., search_depth=8, search_wall_ms=1500)
CFG["action_cap"] = 128


def project(base, wire):
    obs = base(wire)
    mech = wire["mechanism"]
    n = len(obs["enemies"])
    if len(mech["species"]) != n or any(not -1 <= p["owner"] < n for p in mech["stacks"]):
        raise ValueError("Entity alignment")
    obs["mechanism"] = {k: mech[k] for k in ("played", "attacks", "skills", "species")}
    obs["mechanism"]["stacks"] = [{k: p[k] for k in ("owner", "id", "amount")} for p in mech["stacks"]]
    return obs


def manifest(fresh=False):
    jobs = []
    decks, families = set(), set()
    for source, split, limit in (("train", "train", 192), ("development", "report", 40)):
        plan = json.loads((ROOT/f"logs/m1-dc1-formal/roots/{source}.json").read_bytes())
        unique = {j[3]: j for j in plan["jobs"]}
        offset = limit if fresh and split == "report" else 0
        for local, family in enumerate(sorted(unique, key=lambda k: digest(["N1BC-v1", k]))[offset:offset+limit]):
            _, spec, _, _, room = unique[family]
            cards = tuple(sorted(c["id"] for c in spec["deck"]))
            if cards in decks or family in families:
                raise ValueError("Repeated deck or family")
            decks.add(cards)
            families.add(family)
            spec = spec | dict(seed=digest(["N1BC-world-v1", family])[:16].upper(),
                               hp=(35, 55, 80, 110)[local % 4], max_hp=(80, 80, 80, 110)[local % 4],
                               relics=spec["relics"])
            jobs.append([len(jobs), spec, split, family, room])
    return dict(purpose="open_n1bc_pilot", config=dict(action_cap=128, version="n1bc-v1"), jobs=jobs)


def run(out, arm, budget, host_path, trained=None, limit=None, fresh=False, qualified=False):
    if bool(trained) != (arm in ("base", "mechanism")):
        raise ValueError("A fitted arm requires its own checkpoint")
    out.mkdir(parents=True, exist_ok=False)
    if checksum(PARENT) != PARENT_SHA:
        raise ValueError("Unexpected parent checkpoint")
    plan = manifest(fresh)
    if qualified:
        plan["jobs"] = [j for j in plan["jobs"] if j[1]["encounter"] != "KNOWLEDGE_DEMON_BOSS"]
    (out/"manifest.json").write_text(json.dumps(plan))
    host = Host(out, host_path, CFG)
    original = host.project
    host.project = lambda wire: project(original, wire)
    _, saved = load(PARENT)
    model = Policy(PARENT, saved["deployment"], budget, .10 if arm == "teacher" else 0., host.version, CFG)
    if trained:
        from learn import restore
        model.net, model.encoder, model.slot = restore(trained)
        if model.encoder.enabled != (arm == "mechanism"):
            raise ValueError("Checkpoint and requested feature treatment disagree")
    definition = model.definition | dict(arm=arm, trained=checksum(trained) if trained else None,
                                         interface=checksum(Path(__file__)))
    jobs = plan["jobs"] if arm == "teacher" else [j for j in plan["jobs"] if j[2] == "report"]
    if limit:
        jobs = jobs[:limit]
    status = Counter()
    start = perf_counter()
    try:
        for job in jobs:
            lane = host.lane()
            policy = Controller(model, host.project, lambda rows: next(model.forward([(rows,)])),
                                random.Random(int(digest(["N1BC-action", job[0]]), 16)))
            result = collect(lane, policy, definition, plan, job, digest([definition, job[0]]))
            with gzip.open(out/f"{job[0]:03}.json.gz", "wt", encoding="utf-8", compresslevel=3) as stream:
                json.dump(result, stream, separators=(",", ":"))
            row = result["row"]
            status[row["status"]] += 1
            if status["error"] >= 3 or result["counts"].get("terminal_mismatch") or perf_counter()-start > 1400:
                raise RuntimeError((status, row["reason"]))
            if len(list(out.glob("*.gz"))) % 40 == 0:
                print(job[0], status, flush=True)
    finally:
        host.close()
        (out/"run.json").write_text(json.dumps(dict(seconds=perf_counter()-start, counts=status,
                                                    definition=definition), indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("output", type=Path)
    p.add_argument("arm", choices=("teacher","frozen","base","mechanism"))
    p.add_argument("--budget", type=int, default=0)
    p.add_argument("--model", type=Path)
    p.add_argument("--limit", type=int)
    p.add_argument("--host", type=Path, default=ROOT/"logs/n1bc-host")
    p.add_argument("--fresh",action="store_true")
    p.add_argument("--qualified",action="store_true")
    a = p.parse_args()
    run(a.output, a.arm, a.budget, a.host.resolve(), a.model, a.limit, a.fresh, a.qualified)
