"""Enumerate the pinned native catalog and audit cross-character complete routes."""
import argparse
from collections import Counter
from contextlib import ExitStack
import json
from pathlib import Path

from engine import BANK, bind, open_worker
from qualify_native import qualify


def scan(output, solver, natural_hp=False):
    versions = bind(output, solver)
    with ExitStack() as stack:
        catalog = open_worker(output, stack, versions).request("synthetic_catalog")
    base = json.loads((Path(__file__).parent / "integration.json").read_bytes())["batches"][0][0]
    cards = {}
    encounters = {}
    for character in catalog["characters"]:
        for card in character["cards"]:
            cards[(character["name"], card["id"])] = dict(character=character["name"], card=card["id"],
                native="in_catalog", solver="unverified", nosl="unverified", native_steps=0,
                complete=0, training="unqualified", reason="No representative route examined")
    for act in catalog["acts"]:
        for encounter in act["encounters"]:
            encounters[(act["act"], act["variant"], encounter["id"])] = dict(act=act["act"],
                variant=act["variant"], encounter=encounter["id"], room=encounter["room"],
                native="in_catalog", solver="unverified", nosl="unverified", native_steps=0,
                complete=0, training="unqualified",
                reason="Only ordinary encounters are admitted by the synthetic host" if encounter["room"] != "Monster"
                else "No representative route examined")

    routes = []
    for act_number in (1, 2, 3):
        variants = [a for a in catalog["acts"] if a["act"] == act_number]
        preferred = {1: "SHRINKER_BEETLE_WEAK", 2: "THIEVING_HOPPER_WEAK", 3: "DEVOTED_SCULPTOR_WEAK"}
        variant, encounter = next((a["variant"], e["id"]) for a in variants for e in a["encounters"]
                                  if e["room"] == "Monster" and (natural_hp or e["id"] == preferred[act_number]))
        for character in catalog["characters"]:
            role = character["name"]
            strike = "STRIKE_" + role.upper()
            # Give later-act qualification fixtures room to exercise a full route.
            # These roots are independent of the training manifest.
            hp = character["max_hp"] if natural_hp or act_number == 1 else 240
            spec = base | dict(character=role, hp=hp, max_hp=hp,
                               act=act_number, act_variant=variant, encounter=encounter,
                               seed=f"IIBSCAN{act_number}{role.upper()}",
                               deck=[dict(id=strike, upgrade=i % 2) for i in range(5)])
            try:
                result = qualify(output, versions, spec, strike)
            except (AssertionError, ValueError, StopIteration, BANK.f1.i2.StopRun) as error:
                result = dict(terminal="unqualified", detail=str(error))
            routes.append(dict(spec=spec, **result))
            for row in (cards[(role, strike)], encounters[(act_number, variant, encounter)]):
                if result.get("native_terminal") and result["terminal"] in ("predicted_win", "death"):
                    row["solver"] = row["nosl"] = "passed_fixture"
                    row["native_steps"] += result["exact_boundaries"]
                    row["complete"] += 1
                    row["reason"] = "Fixture evidence; broader mechanism mix unverified"
                elif not row["complete"]:
                    row["reason"] = result.get("detail") or result["terminal"]
            status = Counter(r["terminal"] for r in routes)
            BANK.atomic(output / "coverage.json", dict(schema="sts2.nosl.iib.coverage.v1", versions=versions, natural_hp=natural_hp,
                totals=dict(character_card_pairs=len(cards), encounters=len(encounters), routes=len(routes),
                            route_status=dict(status)),
                cards=list(cards.values()), encounters=list(encounters.values()), routes=routes))
            print(act_number, role, result["terminal"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", required=True, type=Path)
    parser.add_argument("--natural-hp", action="store_true", help="Audit each act's first ordinary encounter at character HP")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    scan(output, args.solver, args.natural_hp)
