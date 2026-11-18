"""Run the bounded Crawlers scheduling experiment on the frozen game runtime."""
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
from run import BASE, BASELINE, DOTNET, REVISION, WORKSPACE, load

HARNESS = BASE / f"CombatSolver-{REVISION}.local/tool-build/OfflineSearchHarness/bin/Release/net9.0/OfflineSearchHarness.dll"
PATCHED = WORKSPACE / "CombatSolver-m1-l3/bin/CombatSolver.dll"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def traces(log):
    last = {}
    for line in log.splitlines():
        if not line.startswith("L3_"):
            continue
        kind, *values = line.split()
        values = list(map(int, values))
        if kind == "L3_EXPAND" and values[0] == 1:
            last = {}
        last.setdefault(kind.removeprefix("L3_").lower(), []).append(values)
    return last


def run(out, root, mode, nodes, milliseconds, repeat, deadline):
    directory = out / f"{root}-{nodes}-{milliseconds}-{mode}-{repeat}"
    directory.mkdir(parents=True)
    encounter, seed = ("OVERGROWTH_CRAWLERS", "run_2") if root == "crawlers" else ("FUZZY_WURM_CRAWLER_WEAK", "M1CS1")
    env = dict(os.environ, OFFLINE_HARNESS_COMBATSOLVER_DLL=str(BASELINE if mode == "stock" else PATCHED),
               M1CS1_WARM="1", M1CS1_MICRO="0", M1CS1_FORK="0", DOTNET_GCHeapHardLimit="10000000")
    env.pop("M1L3_RANK", None)
    if mode != "stock":
        env["M1L3_RANK"] = mode
    command = [str(DOTNET), "--fx-version", "9.0.7", str(HARNESS),
               "--character", "IRONCLAD", "--encounter", encounter, "--seed", seed,
               "--label", directory.name, "--out", str(directory.resolve()), "--profile", "Custom",
               "--search-mode", "Evaluate", "--beam", "24", "--nodes", str(nodes),
               "--dop", "1", "--budget-ms", str(milliseconds), "--potion-policy", "Smart"]
    timeout = min(25, deadline - time.monotonic())
    if timeout <= 0:
        raise TimeoutError("M1-L3 batch deadline")
    log = directory / "console.txt"
    with log.open("wb") as stream:
        subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT,
                       timeout=timeout, check=True)
    report = load(directory / "harness-result.json")
    quality = load(directory / "quality.json")
    metrics = report["pruneCounters"]
    route = load(directory / "route.json")
    result = {
        "root": root, "mode": mode, "nodes": nodes, "budgetMs": milliseconds, "repeat": repeat,
        "rootStamp": digest(report["search"]["rootContinuationStamp"]),
        "liveStamp": digest(report["search"]["rootLiveStamp"]),
        "wallMs": round(report["wallSeconds"] * 1000, 2),
        "expanded": metrics["totalExpanded"], "transitions": metrics["totalTransitions"],
        "boundary": metrics["boundary"], "timeBoundaryObserved": report["timeBoundaryObserved"],
        "peakMiB": round(report["peakProcessWorkingSetBytes"] / 2**20, 1),
        "quality": quality["quality"], "risk": quality["snapshot"]["hasRisk"],
        "actions": len(route), "routeHash": digest(route), "firstAction": route[0]["kind"] if route else None,
        "firstCard": route[0]["cardId"] if route else None, "trace": traces(log.read_text(encoding="utf-8", errors="replace")),
    }
    print(directory.name, result["expanded"], result["quality"]["won"], result["wallMs"], flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if hashlib.sha256(BASELINE.read_bytes()).hexdigest() != "d286a18c7c0a06769aa636ec00cac53f3fb71de749028858c1e1a7062282ab13":
        raise ValueError("Unexpected frozen DLL")
    deadline = time.monotonic() + 300
    results = []
    configurations = [
        ("crawlers", 400, 30000, ("stock", "off", "strike", "defend")),
        ("crawlers", 1200, 30000, ("stock", "off", "strike", "defend")),
        ("crawlers", 5000, 850, ("off", "strike", "defend")),
        ("crawlers", 5000, 850, ("defend", "off", "strike")),
        ("crawlers", 5000, 850, ("strike", "defend", "off")),
        ("small", 400, 30000, ("stock", "strike")),
    ]
    for repeat, (root, nodes, milliseconds, modes) in enumerate(configurations):
        for mode in modes:
            results.append(run(args.output, root, mode, nodes, milliseconds, repeat, deadline))
            (args.output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
