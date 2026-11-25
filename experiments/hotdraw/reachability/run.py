"""Run the frozen paired reachability cohort with isolated result directories."""
import argparse
import gzip
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from check import card, request
from build import checksum

STRUCTURES = HERE.parent / "structures"


def base_request(tree, name, spec):
    if spec.get("upstream"):
        fixture = tree / "coverage/fixtures/search/two-card-infinite-0170.json"
        return json.loads(fixture.read_text(encoding="utf-8"))
    cards = [card(row[0], row[1] if len(row) > 1 else "Hand",
                  count=row[2] if len(row) > 2 else 1) for row in spec["cards"]]
    return request(name, cards, hp=spec["hp"], energy=spec["energy"],
                   powers=spec.get("powers", []), relics=spec.get("relics", []))


def run(build_file, output, selected):
    build_file = build_file.resolve()
    identity = json.loads(build_file.read_text(encoding="utf-8"))
    for key in ("runtime", "solver", "dll"):
        hash_key = "harness" if key == "dll" else key
        if checksum(Path(identity[key])) != identity[f"{hash_key}_sha256"]:
            raise ValueError(f"Build identity changed: {key}")
    freeze = HERE / "fixtures.json"
    if checksum(freeze) != identity["reachability"]["fixtures.json"]:
        raise ValueError("The run differs from the build's frozen fixtures.")
    evidence = STRUCTURES / "results.json.gz"
    baseline = json.loads((STRUCTURES / "fixtures.json").read_text(encoding="utf-8"))["cases"]
    experiment = json.loads(freeze.read_text(encoding="utf-8"))
    cases = experiment["cases"]
    if set(selected) - cases.keys():
        raise ValueError(f"Unknown fixtures: {set(selected) - cases.keys()}")
    tree = build_file.parent / f"CombatSolver-{identity['upstream']}"
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    results = {}
    for name in selected or cases:
        spec = cases[name]
        directory = output / name
        directory.mkdir()
        root = base_request(tree, spec["base"], baseline[spec["base"]])
        for key, field in (("hp", "initialPlayerHp"), ("energy", "initialPlayerEnergy"),
                           ("enemy", "enemyCurrentHp")):
            if key in spec:
                root[field] = spec[key]
        if "enemy" in spec:
            root["initialEnemyMaxHps"] = [max(50, spec["enemy"])]
        root["cards"].extend(card(row[0], row[1], count=row[2] if len(row) > 2 else 1)
                             for row in spec.get("add", []))
        root["reachability"] = {"Name": name, "Base": spec["base"], "Target": spec["target"],
                                "Budget": experiment["budgets"], "Discovery": experiment["discovery"],
                                "Evidence": str(evidence), "Pair": spec.get("pair", False),
                                "Tape": spec.get("tape", False), "Laps": spec.get("laps", False)}
        request_file = directory / "request.json"
        request_file.write_text(json.dumps(root, indent=2), encoding="utf-8")
        detail = directory / "result.json"
        with (directory / "run.log").open("wb") as log:
            try:
                run = subprocess.run([identity["runtime"], identity["dll"], "--hotdraw", "reachability",
                                      str(request_file), str(detail)], cwd=tree, timeout=45,
                                     stdout=log, stderr=subprocess.STDOUT, check=False)
                results[name] = (json.loads(detail.read_text(encoding="utf-8")) if run.returncode == 0 and detail.is_file()
                                 else {"error": f"exit {run.returncode}"})
            except subprocess.TimeoutExpired:
                results[name] = {"error": "harness_timeout"}
        print(f"{name}: {results[name].get('error', 'pass')}", flush=True)

    envelope = {"schema": 1, "fixture_sha256": checksum(freeze), "structure_evidence_sha256": checksum(evidence),
                "build": {key: value for key, value in identity.items() if key not in {"runtime", "solver", "dll"}},
                "results": results}
    (output / "results.json.gz").write_bytes(gzip.compress(
        json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), mtime=0))
    (output / "summary.json").write_text(json.dumps(
        {name: summarize(row) for name, row in results.items()}, indent=2) + "\n", encoding="utf-8")
    return int(any("error" in row for row in results.values()))


def summarize(row):
    if "error" in row:
        return row
    r = row["result"]
    out = {key: r[key] for key in ("Name", "Base", "Target", "RootKey", "runtimeMs")}
    out["coldMs"] = row["coldMilliseconds"]
    fields = ("Lower", "Upper", "EntryConfirmed", "EntryUnresolved", "Victory", "Death", "Unfinished",
              "Unresolved", "VictoryWithoutEntry", "VictoryAfterEntry", "VictoryWithPeriodActions", "Attempts",
              "EntryAttempts", "AuditAttempts", "Milliseconds", "SearchStops", "FirstMove")
    out["arms"] = {key: {field: arm[field] for field in fields} | {"entryCount": len(arm["Entries"])}
                   for key, arm in r["arms"].items()}
    for key, arm in r["arms"].items():
        won = [row for row in arm["Joint"] if row["Status"] == "terminal:Victory"]
        out["arms"][key]["victoryMeanSignedHpLoss"] = (
            sum(row["HpLost"] * row["Weight"] for row in won) / arm["Victory"] if arm["Victory"] > 0 else None)
    out["potential"] = {key: r["discovery"][key] for key in ("Nodes", "SearchAttempts", "ReplayAttempts", "Stop")}
    out["potential"]["witnesses"] = [
        {"grade": w["Grade"], "kind": w["Kind"], "target": [step["Move"]["Card"] for step in w["Period"]],
         "startup": len(w["Startup"]), "stop": w["Stop"]} for w in r["discovery"]["Structures"]]
    if r["substitute"]:
        substitute = r["substitute"]
        out["substitute"] = {"target": [role["Card"] for role in substitute["replacement"]["Period"]],
                             "startup": [substitute["nosl"][key] for key in ("Lower", "Upper")],
                             "victory": substitute["nosl"]["Victory"]}
    if r["laps"]:
        out["laps"] = {key: value for key, value in r["laps"].items() if key != "Route"}
    if r["tape"]:
        out["conditioned"] = {"fixed": r["tape"]["fixedTape"]["WinProbability"],
                              "adaptive": [r["tape"]["adaptive"][key] for key in ("Lower", "Upper")],
                              "ideal": [r["tape"]["ideal"][key] for key in ("Lower", "Upper")],
                              "horizon": r["tape"]["horizon"]}
    if r["pair"]:
        out["pair"] = r["pair"]
        out["budgetCheck"] = {key: r["budgetCheck"][key] for key in ("Lower", "Upper", "Unresolved")}
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("fixtures", nargs="*")
    args = parser.parse_args()
    raise SystemExit(run(args.build, args.output, args.fixtures))
