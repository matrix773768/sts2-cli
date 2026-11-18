"""Replay E1 routes and the native Boss alternative in fresh processes."""
import argparse
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent
spec = spec_from_file_location("e1_routes", HERE.parent / "m1-e1/run.py")
e1 = module_from_spec(spec)
spec.loader.exec_module(e1)
from run import BASELINE, DOTNET, FIXTURES, WORKSPACE, load
FIXED, find_source, inputs = e1.FIXED, e1.find_source, e1.inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--case", choices="ABCDE")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    assert hashlib.sha256(BASELINE.read_bytes()).hexdigest() == "d286a18c7c0a06769aa636ec00cac53f3fb71de749028858c1e1a7062282ab13"
    harness = WORKSPACE / "CombatSolver-m1-e2/repair/bin/OfflineSearchHarness.dll"
    for letter, case, policy in (*FIXED, ("D", *FIXED[-1][1:]), ("E", *FIXED[-1][1:])):
        if args.case and args.case != letter:
            continue
        folder = output / letter
        folder.mkdir()
        source = find_source("C" if letter in "DE" else letter, case, policy)
        actions = inputs(source)
        if letter in "DE":
            actions = actions[:19]
            assert actions[-1]["selected"]["id"] == "FRANTIC_ESCAPE"
            actions[-1]["selected"] = (
                None if letter == "D" else {"id": "MOMENTUM_STRIKE", "handIndex": 3, "target": 1}
            )
        plan = folder / "input.json"
        plan.write_text(json.dumps(actions), encoding="utf-8")
        request = load(FIXTURES / f"{case}.json")
        request["generatedScenarioPath"] = str(FIXTURES / f"{case}-scenario.json")
        request_path = folder / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        env = dict(os.environ, OFFLINE_HARNESS_COMBATSOLVER_DLL=str(BASELINE),
                   M1Q1_POLICY=policy, M1Q1_WARM="0", M1Q3_VERIFY="0", M1E1_INPUT=str(plan),
                   M1E2_BRANCH="1" if letter in "DE" else "0", DOTNET_GCHeapHardLimit="10000000")
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
        for actual, expected in zip(native["steps"][:18] if letter in "DE" else native["steps"],
                                    source["trajectory"]):
            for key in ("turn", "selected", "before", "after"):
                assert actual[key] == expected[key], (letter, key)
        audit = load(folder / "audit.json")
        if len(native["steps"]) == len(source["trajectory"]):
            assert native["outcome"] == source["outcome"] and native["choiceRequests"] == source["choiceRequests"]
        if letter in "DE":
            assert len(native["steps"]) == 19
            selected = native["steps"][-1]["selected"]
            if letter == "D":
                assert selected is None
            else:
                assert all(selected[key] == value for key, value in actions[-1]["selected"].items())
        print(letter, audit["status"], (audit.get("_difference") or audit.get("difference") or {}).get("step"), flush=True)
        (folder / "measurement.json").write_text(json.dumps({
            "case": case, "root": native["root"], "live": native["live"], "processMs": wall,
            "nativeOutcome": native["outcome"], "nativeChoices": native["choiceRequests"],
            "nativeVerifiedPrefixExecuteMs": sum(s["executeMs"] for s in native["steps"][:audit["matched"]]),
            "nativeExecuteMs": sum(s["executeMs"] for s in native["steps"]),
            "nativeExecuted": len(native["steps"]), "audit": audit,
            "nativeEndTurn": native["endTurn"], "nativeBattleMs": native["battleMs"],
            "nativeFinalActionMs": native["steps"][-1]["executeMs"],
        }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
