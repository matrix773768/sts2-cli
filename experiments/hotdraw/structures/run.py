"""Run the frozen N2A.2 cohort and preserve all cases, including failed processes."""
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


def run(build_file, output, selected):
    build_file = build_file.resolve()
    identity = json.loads(build_file.read_text(encoding="utf-8"))
    for field, key in (("runtime", "runtime_sha256"), ("solver", "solver_sha256"),
                       ("dll", "harness_sha256")):
        if checksum(Path(identity[field])) != identity[key]:
            raise ValueError(f"Artifact identity changed: {field}")
    tree = build_file.parent / f"CombatSolver-{identity['upstream']}"
    frozen = HERE / "fixtures.json"
    if checksum(frozen) != identity["structures"]["fixtures.json"]:
        raise ValueError("The build and run need the same frozen fixture cohort.")
    experiment = json.loads(frozen.read_text(encoding="utf-8"))
    cases = experiment["cases"]
    if set(selected) - cases.keys():
        raise ValueError(f"Unknown fixtures: {set(selected) - cases.keys()}")
    output.mkdir(parents=True, exist_ok=False)
    results = {}
    for name in selected or cases:
        spec = cases[name]
        directory = (output / name).resolve()
        directory.mkdir()
        if spec.get("upstream"):
            upstream = tree / "coverage/fixtures/search/two-card-infinite-0170.json"
            root = json.loads(upstream.read_text(encoding="utf-8"))
        else:
            root = request(name, [card(item[0], item[1] if len(item) > 1 else "Hand",
                                       count=item[2] if len(item) > 2 else 1) for item in spec["cards"]],
                           hp=spec["hp"], energy=spec["energy"], powers=spec.get("powers", []),
                           relics=spec.get("relics", []))
        root["structureStudy"] = {"Name": name, "Budget": experiment["budget"] | spec.get("budget", {}),
                                  **spec.get("options", {})}
        if spec.get("prior"):
            root["structureStudy"]["PriorHotDraw"] = str(HERE.parent / "results.json")
        request_file = directory / "request.json"
        request_file.write_text(json.dumps(root, indent=2), encoding="utf-8")
        detail = directory / "result.json"
        with (directory / "run.log").open("wb") as log:
            try:
                proc = subprocess.run([identity["runtime"], identity["dll"], "--hotdraw", "structures",
                                       str(request_file), str(detail)], cwd=tree,
                                      timeout=35, stdout=log, stderr=subprocess.STDOUT, check=False)
                if proc.returncode == 0 and detail.is_file():
                    results[name] = json.loads(detail.read_text(encoding="utf-8"))
                else:
                    results[name] = {"error": f"exit {proc.returncode}"}
            except subprocess.TimeoutExpired:
                results[name] = {"error": "harness_timeout"}
        print(f"{name}: {results[name].get('error', 'pass')}", flush=True)

    payload = {"schema": 1, "fixture_sha256": checksum(frozen),
               "build": {key: value for key, value in identity.items() if key not in {"runtime", "solver", "dll"}},
               "results": results}
    (output / "results.json.gz").write_bytes(gzip.compress(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), mtime=0))
    (output / "summary.json").write_text(json.dumps(
        {name: summarize(row) for name, row in results.items()}, indent=2) + "\n", encoding="utf-8")
    return int(any("error" in row for row in results.values()))


def summarize(row):
    if "error" in row:
        return row
    result = row["result"]
    summary = {"rootKey": result["rootKey"], "coldMs": row["coldMilliseconds"],
               "comparisonMs": result["comparisonMs"]}
    for arm in ("battle", "active"):
        data = result[arm]
        summary[arm] = {key: value for key, value in data.items() if key not in ("WinningRoute", "Structures")}
        summary[arm]["winningSteps"] = len(data["WinningRoute"] or [])
        summary[arm]["structures"] = [
            {"grade": s["Grade"], "kind": s["Kind"], "startup": len(s["Startup"]), "period": len(s["Period"]),
             "periodCards": [step["Move"]["Card"] for step in s["Period"]],
             "laps": len(s["Laps"]), "completeLaps": sum(lap["Complete"] for lap in s["Laps"]),
             "firstFourDeltas": [lap["Delta"] for lap in s["Laps"][:4]], "stop": s["Stop"],
             "tapeProbability": s["ConditionalTapeProbability"], "nontrivialDraws": s["NontrivialDraws"],
             "observedPaymentRequirement": s["ObservedPaymentRequirement"],
             "entryEnergy": s["EntryEnergy"]} for s in data["Structures"]]
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("fixtures", nargs="*")
    args = parser.parse_args()
    raise SystemExit(run(args.build, args.output, args.fixtures))
