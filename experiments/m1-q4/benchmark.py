"""Run the predeclared targeted SL arms in isolated native processes."""
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

ROOTS = ("dev-03-regent-elite", "holdout-02-defect")
SOLVER_SHA = "d286a18c7c0a06769aa636ec00cac53f3fb71de749028858c1e1a7062282ab13"


def trial(output, case, arm, repeat, deadline):
    folder = output / f"{case}-{arm}-{repeat}"
    folder.mkdir()
    request = load(FIXTURES / f"{case}.json")
    fixture = FIXTURES / f"{case}-scenario.json"
    request["generatedScenarioPath"] = str(fixture)
    path = folder / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    env = dict(os.environ, OFFLINE_HARNESS_COMBATSOLVER_DLL=str(BASELINE),
               M1Q1_POLICY="tactical", M1Q1_WARM="1", M1Q4_ARM=arm, M1Q3_VERIFY="0", DOTNET_GCHeapHardLimit="10000000")
    build = "CombatSolver-m1-q4/repair"
    command = [str(DOTNET), "--fx-version", "9.0.7",
               str(WORKSPACE / f"{build}/bin/OfflineSearchHarness.dll"),
               "--request", str(path), "--out", str(folder), "--workspace", str(folder),
               "--milestone", "M1", "--profile", "Custom", "--beam", "24", "--nodes", "2400",
               "--budget-ms", "15000", "--dop", "2", "--potion-policy", "Smart",
               "--search-mode", "Coordinator", "--use-portfolio", "--production-budget"]
    start = time.monotonic()
    timeout = min(28, deadline - start)
    if timeout <= 0:
        raise TimeoutError("Q4 batch deadline")
    with (folder / "console.txt").open("wb") as log:
        try:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env, timeout=timeout)
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            exit_code = "timeout"
    info = load(fixture)
    output_row = dict(case=case, arm=arm, repeat=repeat, seed=info["seed"],
                      character=info["characterId"], encounterKind=info["encounterKind"], ascension=info["ascension"],
                      fixtureSha=hashlib.sha256(fixture.read_bytes()).hexdigest(),
                      processMs=(time.monotonic()-start)*1000, exitCode=exit_code)
    log = (folder / "console.txt").read_text(encoding="utf-8", errors="replace")
    output_row["reattachVisualCalls"] = log.count("Q2_REATTACH_PRESENTATION_BYPASSED")
    identity = folder / "identity.json"
    if identity.exists():
        output_row.update(load(identity))
    if exit_code == 0:
        data = load(folder / "fast.json")
        steps = data.pop("steps")
        native = load(folder / "harness-result.json")
        output_row.update(data, actions=len(steps),
                          setupMs=sum(s["Milliseconds"] for s in native["steps"]),
                          decisionMs=sum(s["decisionMs"] for s in steps),
                          observeMs=sum(s["observeMs"] for s in steps),
                          executeMs=sum(s["executeMs"] for s in steps))
        output_row["trajectory"] = [{k: s[k] for k in ("turn", "selected", "before", "after", "block", "enemies", "moves", "stock", "preStamp", "riskBefore", "riskAfter")} for s in steps]
    else:
        if "Fatal error. 0xC0000005" in log and "DecimillipedeSegment+<ReattachMove>" in log:
            output_row.update(status="unsupported_reattach", failure="DecimillipedeSegment.ReattachMove -> Godot.ResourceLoader")
        elif "Native rejected" in log:
            output_row.update(status="native_rejected", failure="native legality recheck failed")
        else:
            output_row.update(status="host_timeout" if exit_code == "timeout" else "host_error",
                              failure=next((line.strip().split(" in C:")[0] for line in log.splitlines()
                                            if "Fatal error" in line or "Exception:" in line), None))
    print(case, arm, repeat, output_row["status"], output_row.get("actions"), flush=True)
    return output_row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    assert hashlib.sha256(BASELINE.read_bytes()).hexdigest() == SOLVER_SHA
    output.mkdir(parents=True)
    rows = []
    deadline = time.monotonic() + 180
    for case in ROOTS:
        for repeat in range(2):
            for arm in ("A", "B", "C") if repeat == 0 else ("C", "B", "A"):
                rows.append(trial(output, case, arm, repeat, deadline))
                (output / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
