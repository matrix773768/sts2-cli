"""Run fixed native plans against direct CombatSolver Replay in A/B/C order."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-l2"))
from run import BASELINE, DOTNET, FIXTURES, WORKSPACE, load

FIXED = (
    ("A", "dev-02-defect-elite", "tactical"),
    ("B", "dev-00-ironclad-elite", "first"),
    ("C", "holdout-02-defect", "tactical"),
)


def find_source(letter, case, policy):
    if letter == "C":
        return load(HERE.parent / "m1-q4/results.json")["routes"][f"{case}/C"]
    return next(row for row in load(HERE.parent / "m1-q3/results.json")["runs"]
                if (row["case"], row["policy"]) == (case, policy))


def inputs(source):
    picks = {}
    for request in source.get("choiceRequests", []):
        index, = request["indexes"]
        card = request["candidates"][index]
        occurrence = sum(c["key"] == card["key"] for c in request["candidates"][:index])
        picks[request["step"]] = {k: card[k] for k in ("id", "key", "upgrade")} | {"optionOccurrence": occurrence}
    return [{"turn": step["turn"], "selected": step["selected"], "pick": picks.get(i)}
            for i, step in enumerate(source["trajectory"], 1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--case", choices="ABC")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    assert hashlib.sha256(BASELINE.read_bytes()).hexdigest() == "d286a18c7c0a06769aa636ec00cac53f3fb71de749028858c1e1a7062282ab13"
    harness = WORKSPACE / "CombatSolver-m1-e1/repair/bin/OfflineSearchHarness.dll"
    for letter, case, policy in FIXED:
        if args.case and args.case != letter:
            continue
        folder = output / letter
        folder.mkdir()
        source = find_source(letter, case, policy)
        plan = folder / "input.json"
        plan.write_text(json.dumps(inputs(source)), encoding="utf-8")
        request = load(FIXTURES / f"{case}.json")
        request["generatedScenarioPath"] = str(FIXTURES / f"{case}-scenario.json")
        request_path = folder / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        env = dict(os.environ, OFFLINE_HARNESS_COMBATSOLVER_DLL=str(BASELINE),
                   M1Q1_POLICY=policy, M1Q1_WARM="0", M1Q3_VERIFY="0", M1E1_INPUT=str(plan),
                   DOTNET_GCHeapHardLimit="10000000")
        command = [str(DOTNET), "--fx-version", "9.0.7", str(harness), "--request", str(request_path),
                   "--out", str(folder), "--workspace", str(folder), "--milestone", "M1",
                   "--profile", "Custom", "--beam", "24", "--nodes", "2400", "--budget-ms", "15000",
                   "--dop", "2", "--potion-policy", "Smart", "--search-mode", "Coordinator",
                   "--use-portfolio", "--production-budget"]
        start = time.monotonic()
        with (folder / "console.txt").open("wb") as stream:
            subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=35, check=True)
        wall = 1000 * (time.monotonic() - start)
        native = load(folder / "fast.json")
        assert (native["root"], native["live"]) == (source["root"], source["live"])
        for actual, expected in zip(native["steps"], source["trajectory"]):
            for key in ("turn", "selected", "before", "after"):
                assert actual[key] == expected[key], (letter, key)
        audit = load(folder / "audit.json")
        if len(native["steps"]) == len(source["trajectory"]):
            assert native["outcome"] == source["outcome"] and native["choiceRequests"] == source["choiceRequests"]
        print(letter, audit["status"], (audit.get("_difference") or audit.get("difference") or {}).get("step"), flush=True)
        (folder / "measurement.json").write_text(json.dumps({
            "case": case, "root": native["root"], "live": native["live"], "processMs": wall,
            "nativeOutcome": native["outcome"], "nativeChoices": native["choiceRequests"],
            "nativeVerifiedPrefixExecuteMs": sum(s["executeMs"] for s in native["steps"][:audit["matched"]]),
            "nativeExecuteMs": sum(s["executeMs"] for s in native["steps"]),
            "nativeExecuted": len(native["steps"]), "audit": audit,
        }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
