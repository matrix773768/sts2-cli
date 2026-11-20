"""Rebuild a versioned catalogue and exact-route coverage index from a sealed run."""
import argparse
from collections import Counter
from contextlib import ExitStack, closing
import gzip
import json
from pathlib import Path
import sqlite3

from admission import VERSION, digest
from engine import bind, open_worker
from nosl_experience import save_json


def index(output, versions, catalog):
    cards = {(c["name"], card["id"]): Counter(catalogued=1)
             for c in catalog["characters"] for card in c["cards"]}
    encounters = {(a["act"], a["variant"], e["id"]): Counter(catalogued=1)
                  for a in catalog["acts"] for e in a["encounters"]}
    attempts, paths = [], {}
    with closing(sqlite3.connect(output / "training.sqlite")) as db:
        identity = json.loads(db.execute("SELECT value FROM identity WHERE id=1").fetchone()[0])
        if identity["engine"] != versions or identity["protocol"] != VERSION:
            raise ValueError("Coverage index does not match audited engine")
        for step, key, raw, seal in db.execute(
                "SELECT step, root, rows, sha FROM roots JOIN root_hashes USING(phase,step,root) ORDER BY step,root"):
            from hashlib import sha256
            if sha256(raw).hexdigest() != seal:
                raise ValueError("Root batch checksum mismatch")
            batch = json.loads(gzip.decompress(raw))
            audit = json.loads((output / "audit" / f"{step:06d}-{key}.json").read_bytes())
            if digest(audit) != batch["evidence_sha256"]:
                raise ValueError("Audit record checksum mismatch")
            spec = batch["spec"]
            encountered = encounters[(spec["act"], spec["act_variant"], spec["encounter"])]
            path = audit.get("path", [])
            levels = {
                "attempted": True,
                "constructible": batch["constructed"],
                "executable": any(row["transitions"] for row in batch["rows"]),
                "terminal_verified": audit["terminal_verified"],
                "training_admissible": any(row["feedback"]["eligible"] for row in batch["rows"]),
            }
            for level, passed in levels.items():
                encountered[level] += int(passed)
            encountered[batch["status"]] += 1
            played = {action["card"] for action in path if action["card"]}
            for card in {c["id"] for c in spec["deck"]}:
                counts = cards[(spec["character"],card)]
                counts["in_deck"] += 1
                counts["observed_in_audit_path"] += int(card in played)
                counts["on_verified_route"] += int(card in played and levels["terminal_verified"])
            for entry in path:
                mechanism = entry["effect"] or entry["kind"]
                paths.setdefault(mechanism, Counter())[batch["status"]] += 1
            attempts.append(dict(step=step, position=key, root=digest(spec), spec=spec, levels=levels,
                                 status=batch["status"], reason=audit.get("reason"),
                                 first_difference=audit.get("position"), route=audit.get("route"),
                                 native_verified_boundaries=audit.get("boundaries",0),
                                 evidence_sha256=batch["evidence_sha256"]))
    return dict(schema=VERSION, catalogue_sha256=digest(catalog), engine=versions,
                counts=dict(cards=len(cards), encounters=len(encounters), attempts=len(attempts)),
                cards=[dict(character=k[0],card=k[1],counts=v) for k,v in sorted(cards.items())],
                encounters=[dict(act=k[0],variant=k[1],encounter=k[2],counts=v) for k,v in sorted(encounters.items())],
                mechanisms=paths, attempts=attempts)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    parser.add_argument("--solver",type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve()
    versions=bind(output,args.solver.resolve())
    with ExitStack() as stack:
        catalog=open_worker(output,stack,versions).request("synthetic_catalog")
    save_json(output/"coverage.json",index(output,versions,catalog))
