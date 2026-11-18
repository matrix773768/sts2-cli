"""Bounded scan and fixed-prefix follow-up on the frozen M1-L1 runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]
BASE = WORKSPACE / "CombatSolver-m1-cs1"
FIXTURES = BASE / "fixtures" / "requests"
BASELINE = BASE / "baseline.dll"
REVISION = "78e4545e825e58c3d999354b1ffcd54241b1d2cf"
DOTNET = HERE.parents[1] / "logs" / "m1-review-dotnet" / "dotnet.exe"


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def run(output, case, scenario, nodes, probe, harness, deadline):
    directory = output / ("prefix" if probe else "scan") / case / str(nodes)
    directory.mkdir(parents=True)
    env = dict(os.environ, OFFLINE_HARNESS_COMBATSOLVER_DLL=str(BASELINE),
               M1L2_PREFIX="1" if probe else "0", DOTNET_GCHeapHardLimit="10000000")
    timeout = min(110 if probe else 30, deadline - time.monotonic())
    if timeout <= 0:
        raise TimeoutError("M1-L2 batch deadline")
    if not scenario:
        request = load(FIXTURES / f"{case}.json")
        request["generatedScenarioPath"] = str(FIXTURES / f"{case}-scenario.json")
        request_path = directory / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        scenario = ["--request", str(request_path.resolve())]
    command = [str(DOTNET), "--fx-version", "9.0.7", str(harness), *scenario,
               "--label", case, "--out", str(directory), "--profile", "Custom",
               "--search-mode", "Evaluate", "--beam", "24", "--nodes", str(nodes),
               "--dop", "1", "--budget-ms", "6000", "--potion-policy", "Smart"]
    start = time.monotonic()
    with (directory / "console.txt").open("wb") as log:
        try:
            status = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            status = "timeout"
    record = {"root": case, "nodes": nodes, "processStatus": status,
              "processSeconds": round(time.monotonic() - start, 3)}
    if status == 0:
        result = load(directory / "harness-result.json")
        quality = load(directory / "quality.json")
        metrics = result["pruneCounters"]
        record.update({
            "scenario": result["scenario"],
            "won": quality["quality"]["won"] and not quality["snapshot"]["hasRisk"],
            "quality": {k: v for k, v in quality["quality"].items() if k != "score"},
            "boundary": metrics["boundary"],
            "expanded": metrics["selectedExpanded"], "transitions": metrics["selectedTransitions"],
            "seconds": result["wallSeconds"],
            "peakMiB": round(result["peakProcessWorkingSetBytes"] / 2**20, 1),
        })
    (directory / "measurement.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(case, nodes, probe, status, record.get("won"), record.get("expanded"), flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("phase", choices=("scan", "prefix"))
    parser.add_argument("--harness", type=Path)
    args = parser.parse_args()
    if hashlib.sha256(BASELINE.read_bytes()).hexdigest() != "d286a18c7c0a06769aa636ec00cac53f3fb71de749028858c1e1a7062282ab13":
        raise ValueError("Unexpected frozen baseline")
    roots = load(HERE / "roots.json")
    deadline = time.monotonic() + (270 if args.phase == "scan" else 660)
    if args.phase == "scan":
        harness = BASE / f"CombatSolver-{REVISION}.local" / "tool-build/OfflineSearchHarness/bin/Release/net9.0/OfflineSearchHarness.dll"
        for case, scenario in roots.items():
            for nodes in (240, 800):
                run(args.output, case, scenario, nodes, False, harness, deadline)
    else:
        if args.harness is None:
            parser.error("--harness is required for prefix runs")
        for case, scenario in roots.items():
            records = [load(args.output / "scan" / case / str(n) / "measurement.json") for n in (240, 800)]
            if any(record.get("won") for record in records):
                for nodes in (400, 1200):
                    run(args.output, case, scenario, nodes, True, args.harness.resolve(), deadline)


if __name__ == "__main__":
    main()
