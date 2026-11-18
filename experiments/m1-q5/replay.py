"""Run the bounded Q5 Boss search and replay every distinct emitted route."""
import argparse
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent
spec = spec_from_file_location("e2_routes", HERE.parent / "m1-e2/replay.py")
e2 = module_from_spec(spec)
spec.loader.exec_module(e2)

BOSS = "holdout-02-defect"
PREFIX = 18


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def execute(folder, source, actions, decisions=None, *, case=BOSS, prefix=PREFIX, cross_mechanism=None):
    folder.mkdir(parents=True)
    plan = folder / "input.json"
    save(plan, actions)
    request = e2.load(e2.FIXTURES / f"{case}.json")
    request["generatedScenarioPath"] = str(e2.FIXTURES / f"{case}-scenario.json")
    request_path = folder / "request.json"
    save(request_path, request)
    env = dict(os.environ, OFFLINE_HARNESS_COMBATSOLVER_DLL=str(e2.BASELINE),
               M1Q1_POLICY="tactical", M1Q1_WARM="0", M1Q3_VERIFY="0", M1E1_INPUT=str(plan),
               DOTNET_GCHeapHardLimit="10000000", M1E2_BRANCH="0")
    env.pop("M1Q5_EXPECTED", None)
    if decisions is None:
        env["M1Q5_SEARCH"] = "1"
    else:
        expected = folder / "expected.json"
        save(expected, decisions)
        env.update(M1Q5_SEARCH="0", M1Q5_EXPECTED=str(expected))
    env.pop("M1Q6_CASE", None)
    milestone = "q5" if cross_mechanism is None else "q6"
    if cross_mechanism is not None:
        env["M1Q6_CASE"] = cross_mechanism
    harness = e2.WORKSPACE / f"CombatSolver-m1-{milestone}/repair/bin/OfflineSearchHarness.dll"
    command = [str(e2.DOTNET), "--fx-version", "9.0.7", str(harness), "--request", str(request_path),
               "--out", str(folder), "--workspace", str(folder), "--milestone", "M1",
               "--profile", "Custom", "--beam", "24", "--nodes", "2400", "--budget-ms", "15000",
               "--dop", "2", "--potion-policy", "Smart", "--search-mode", "Coordinator",
               "--use-portfolio", "--production-budget"]
    start = time.monotonic()
    with (folder / "console.txt").open("wb") as stream:
        subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=35, check=True)
    wall = 1000 * (time.monotonic() - start)
    native = e2.load(folder / "fast.json")
    assert (native["root"], native["live"]) == (source["root"], source["live"])
    audited_prefix = min(prefix, len(native["steps"]))
    if cross_mechanism is None or decisions is not None:
        assert audited_prefix == prefix
    for actual, expected in zip(native["steps"][:audited_prefix], source["trajectory"][:audited_prefix], strict=True):
        for key in ("turn", "selected", "before", "after"):
            assert actual[key] == expected[key], (folder.name, key)
    audit = e2.load(folder / "audit.json")
    terminal = e2.load(folder / "terminal.json")
    difference = audit["_difference"]
    return {
        "processMs": wall, "root": native["root"], "live": native["live"], "matched": audit["matched"],
        "planned": len(actions), "auditStatus": audit["status"], "nativeStatus": native["status"],
        "nativeEndTurn": native["endTurn"], "nativeOutcome": native["outcome"],
        "nativeExecuteMs": sum(step["executeMs"] for step in native["steps"]),
        "nativeSuffixExecuteMs": sum(step["executeMs"] for step in native["steps"][prefix:]),
        "nativeLifecycleSemantic": terminal["semantic"], "nativeRisk": e2.load(folder / "risk.json"),
        "publicChecks": [] if decisions is None else e2.load(folder / "public.json"),
        "firstDifference": None if not difference else {
            "step": difference["step"], "fields": [row["field"] for row in difference.get("differences", [])],
            "boundary": difference.get("boundaryReason"),
        },
        "forecastSetupMs": {key: audit[key] for key in ("rootCaptureMs", "solverAdapterMs", "rootForkAndSnapshotMs")},
        "prefixPredictionMs": sum(step["predictionMs"] for step in audit["steps"][:prefix]),
        "compareMs": audit["compareMs"],
        "peakWorkingSetBytes": audit["peakWorkingSetBytes"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--search-only", action="store_true")
    args = parser.parse_args()
    start = time.monotonic()
    assert hashlib.sha256(e2.BASELINE.read_bytes()).hexdigest() == "d286a18c7c0a06769aa636ec00cac53f3fb71de749028858c1e1a7062282ab13"
    source = e2.find_source("C", BOSS, "tactical")
    prefix = e2.inputs(source)[:PREFIX]
    output = args.output.resolve()
    output.mkdir(parents=True)
    parent = execute(output / "parent", source, prefix)
    search = e2.load(output / "parent/search.json")
    validation = {}
    seen = {}
    for row in search["candidates"]:
        if args.search_only or row["stop"] not in {"one_player_round", "victory", "death", "action_cap"}:
            continue
        decisions = row["decisions"]
        suffix = [item["input"] for item in decisions]
        route = json.dumps(suffix, sort_keys=True)
        if route in seen:
            validation[row["name"]] = {"sameRouteAs": seen[route]}
            continue
        assert time.monotonic() - start < 180, "Q5 matrix deadline"
        seen[route] = row["name"]
        outcome = execute(output / row["name"], source, prefix + suffix, decisions)
        validation[row["name"]] = outcome
        print(row["name"], outcome["matched"], outcome["planned"], outcome["nativeStatus"], flush=True)
    save(output / "results.json", {"parent": parent, "search": search, "validation": validation})


if __name__ == "__main__":
    main()
