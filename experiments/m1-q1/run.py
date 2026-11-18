"""Run a bounded cold/prewarmed public-policy matrix on native combat roots."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-l2"))
from run import BASELINE, DOTNET, FIXTURES, WORKSPACE, load

CASES = {"small": None, "prisms": "dev-02-defect-elite", "decimillipede": "dev-00-ironclad-elite"}


def run_case(output, harness, case, policy, warm, repeat, deadline):
    folder = output / f"{case}-{policy}-{warm}-{repeat}"
    if folder.exists():
        folder = folder.with_name(folder.name + "-retry")
    folder.mkdir(parents=True)
    fixture = CASES[case]
    if fixture:
        request = load(FIXTURES / f"{fixture}.json")
        request["generatedScenarioPath"] = str(FIXTURES / f"{fixture}-scenario.json")
        path = folder / "request.json"
        path.write_text(json.dumps(request), encoding="utf-8")
        scenario = ["--request", str(path)]
    else:
        scenario = ["--character", "IRONCLAD", "--encounter", "FUZZY_WURM_CRAWLER_WEAK", "--seed", "M1CS1"]
    env = dict(os.environ, OFFLINE_HARNESS_COMBATSOLVER_DLL=str(BASELINE),
               M1Q1_POLICY=policy, M1Q1_WARM=str(warm), DOTNET_GCHeapHardLimit="10000000")
    start = time.monotonic()
    timeout = min(28, deadline - start)
    if timeout <= 0:
        raise TimeoutError("Q1 batch deadline")
    with (folder / "console.txt").open("wb") as log:
        proc = subprocess.run([str(DOTNET), "--fx-version", "9.0.7", str(harness), *scenario,
                        "--out", str(folder), "--workspace", str(folder), "--milestone", "M1", "--profile", "Custom", "--beam", "24",
                        "--nodes", "2400", "--budget-ms", "15000", "--dop", "2", "--potion-policy", "Smart",
                        "--search-mode", "Coordinator", "--use-portfolio", "--production-budget"],
                       env=env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    end = time.monotonic()
    if proc.returncode:
        console = (folder / "console.txt").read_text(encoding="utf-8", errors="replace")
        if "Fatal error. 0xC0000005" not in console or "DecimillipedeSegment+<ReattachMove>" not in console:
            raise RuntimeError(f"Unexpected native host exit {proc.returncode}, see {folder}")
        return dict(case=case, policy=policy, warm=bool(warm), repeat=repeat,
                    status="unsupported_native_host", exitCode=proc.returncode,
                    failure="DecimillipedeSegment.ReattachMove -> Godot.ResourceLoader: 0xC0000005",
                    processMs=(end-start)*1000)
    data = load(folder / "fast.json")
    native = load(folder / "harness-result.json")
    steps = data.pop("steps")
    times = [step["decisionMs"] for step in steps]
    data.update(case=case, policy=policy, repeat=repeat, processMs=(end-start)*1000,
                harnessSetupMs=sum(row["Milliseconds"] for row in native["steps"]),
                transitions=0, simulationMs=0, ipcRequests=0, actions=len(steps),
                decisionSumMs=sum(times), decisionFirstMs=times[0], decisionMedianMs=statistics.median(times),
                observeSumMs=sum(s["observeMs"] for s in steps), executeSumMs=sum(s["executeMs"] for s in steps),
                trajectory=[{k: s[k] for k in ("turn", "selected", "before", "after", "block", "enemies")} for s in steps])
    print(case, policy, warm, repeat, data["status"], data["actions"], flush=True)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    assert hashlib.sha256(BASELINE.read_bytes()).hexdigest() == "d286a18c7c0a06769aa636ec00cac53f3fb71de749028858c1e1a7062282ab13"
    harness = WORKSPACE / "CombatSolver-m1-q1/bin/OfflineSearchHarness.dll"
    rows = load(args.output / "results.json") if args.resume else []
    completed = {(row["case"], row["policy"], row["warm"], row["repeat"]) for row in rows}
    deadline = time.monotonic() + 250
    for case in CASES:
        if args.smoke and case != "prisms":
            continue
        for repeat in range(1 if args.smoke else 2):
            for warm in (0, 1):
                for policy in ("first", "tactical") if repeat == 0 else ("tactical", "first"):
                    if (case, policy, bool(warm), repeat) in completed:
                        continue
                    rows.append(run_case(args.output.resolve(), harness, case, policy, warm, repeat, deadline))
                    (args.output / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
