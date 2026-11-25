"""Export mechanics for the frozen N2A.3 cohort, retaining per-fixture logs."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from dataset import HERE, read, write

sys.path.insert(0, str(HERE.parent / "reachability"))
from run import base_request, card, checksum, request as new_request


def export(identity, tree, output, name, request, *, required=True):
    folder = output / name
    folder.mkdir()
    source = folder / "request.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    target = folder / "result.json"
    with (folder / "run.log").open("wb") as log:
        child = subprocess.run(
            [identity["runtime"], identity["dll"], "--hotdraw", "mechanisms", str(source), str(target)],
            cwd=tree, stdout=log, stderr=subprocess.STDOUT, timeout=45,
        )
    if child.returncode == 0:
        return read(target)
    if required:
        child.check_returncode()
    return {"error": f"exit {child.returncode}"}


def run(manifest, output, existing=None):
    manifest = manifest.resolve()
    identity = read(manifest)
    for key, label in (("runtime", "runtime"), ("solver", "solver"), ("dll", "harness")):
        if checksum(Path(identity[key])) != identity[f"{label}_sha256"]:
            raise ValueError(f"Changed build component {key}")
    if checksum(HERE / "MechanismHarness.cs") != identity["mechanisms"]["MechanismHarness.cs"]:
        raise ValueError("Changed mechanism exporter")
    tree = manifest.parent / f"CombatSolver-{identity['upstream']}"
    cohort_path = HERE.parent / "reachability" / "fixtures.json"
    if checksum(cohort_path) != identity["reachability"]["fixtures.json"]:
        raise ValueError("Changed cohort")
    bases = read(HERE.parent / "structures" / "fixtures.json")["cases"]
    provenance = {key: identity[key] for key in ("upstream", "archive_sha256", "game_sha256", "harness_sha256",
                                                 "runtime_sha256", "mechanisms", "solver_sha256")}
    cases = read(cohort_path)["cases"]
    output = output.resolve()
    output.mkdir(parents=True)
    results = {}
    if existing:
        prior = read(existing)
        if prior["identity"] != provenance or prior["results"].keys() != cases.keys():
            raise ValueError("Prior cohort identity differs from selected build or fixtures")
        results = prior["results"]
    for name, spec in (() if existing else cases.items()):
        request = base_request(tree, spec["base"], bases[spec["base"]])
        for key, field in (("hp", "initialPlayerHp"), ("energy", "initialPlayerEnergy"), ("enemy", "enemyCurrentHp")):
            if key in spec:
                request[field] = spec[key]
        if "enemy" in spec:
            request["initialEnemyMaxHps"] = [max(50, spec["enemy"])]
        request["cards"].extend(card(row[0], row[1], count=row[2] if len(row) > 2 else 1)
                                for row in spec.get("add", []))
        results[name] = export(identity, tree, output, name, request)
        print(name, flush=True)
    probes = {}
    for encounter in ("TEST_SUBJECT_BOSS", "LAGAVULIN_MATRIARCH_BOSS", "SLUMBERING_BEETLE_NORMAL"):
        request = new_request(encounter, [card("STRIKE_IRONCLAD")], hp=100)
        request["encounterId"] = encounter
        request["clearAllPowers"] = False
        del request["enemyCurrentHp"], request["initialEnemyMaxHps"]
        probes[encounter] = export(identity, tree, output, encounter, request, required=False)
    write(output / "exports.json.gz", {
        "schema": 1, "results": results, "enemyProbes": probes,
        "identity": provenance,
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--existing-cohort", type=Path)
    args = parser.parse_args()
    run(args.manifest, args.output, args.existing_cohort)
