"""Compare bounded Coordinator runs to the M1-L2 Evaluate records."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-l2"))
from run import BASE, BASELINE, DOTNET, FIXTURES, REVISION, load

CASES = ("dev-00-ironclad-elite", "dev-02-defect-elite", "dev-05-ironclad-boss", "pressure-queen")


def stamp(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main(output, matched_evaluate=False):
    output = output.resolve()
    output.mkdir(parents=True)
    assert hashlib.sha256(BASELINE.read_bytes()).hexdigest() == "d286a18c7c0a06769aa636ec00cac53f3fb71de749028858c1e1a7062282ab13"
    harness = BASE / f"CombatSolver-{REVISION}.local/tool-build/OfflineSearchHarness/bin/Release/net9.0/OfflineSearchHarness.dll"
    reference = {x["root"]: x["scan"][1] for x in load(HERE.parent / "m1-l2/results.json")}
    env = dict(os.environ, OFFLINE_HARNESS_COMBATSOLVER_DLL=str(BASELINE),
               M1CS1_WARM="0", M1CS1_MICRO="0", M1CS1_FORK="0", DOTNET_GCHeapHardLimit="18000000",
               OFFLINE_HARNESS_STREAM_DIAGNOSTICS="1")
    deadline = time.monotonic() + 220
    rows = []
    for case in (("dev-02-defect-elite",) if matched_evaluate else CASES):
        folder = output / case
        folder.mkdir()
        request = load(FIXTURES / f"{case}.json")
        request["generatedScenarioPath"] = str(FIXTURES / f"{case}-scenario.json")
        path = folder / "request.json"
        path.write_text(json.dumps(request), encoding="utf-8")
        command = [str(DOTNET), "--fx-version", "9.0.7", str(harness), "--request", str(path),
                   "--label", case, "--out", str(folder), "--profile", "Custom", "--beam", "24",
                   "--nodes", "2400", "--budget-ms", "15000", "--dop", "2", "--potion-policy", "Smart",
                   "--search-mode", "Evaluate" if matched_evaluate else "Coordinator"]
        if not matched_evaluate:
            command += ["--use-portfolio", "--production-budget", "--observe-portfolio"]
        start = time.monotonic()
        timeout = min(50, deadline - start)
        if timeout <= 0:
            raise TimeoutError("Batch deadline")
        log = folder / "console.txt"
        with log.open("wb") as stream:
            try:
                status = subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                        timeout=timeout).returncode
            except subprocess.TimeoutExpired:
                status = "timeout"
        row = {"root": case, "processStatus": status, "processSeconds": round(time.monotonic() - start, 3),
               "evaluate800": reference[case], "mode": "Evaluate" if matched_evaluate else "Coordinator"}
        if status == 0:
            result = load(folder / "harness-result.json")
            quality = load(folder / "quality.json")
            search = result["search"]
            root, live = (stamp(search[k]) for k in ("rootContinuationStamp", "rootLiveStamp"))
            assert (root, live) == (reference[case]["rootStamp"], reference[case]["liveStamp"]), case
            counters = result["pruneCounters"]
            row.update(rootStamp=root, liveStamp=live, quality=quality["quality"],
                       snapshot={k: quality["snapshot"][k] for k in ("hasRisk", "playerDead", "turn", "predictionGaps", "boundaryReason")},
                       **{k: counters.get(k) for k in ("totalExpanded", "totalTransitions", "searchedTurns", "boundary", "onlyDeathRoutes")},
                       wallSeconds=result["wallSeconds"], peakMiB=round(result["peakProcessWorkingSetBytes"] / 2**20, 1),
                       timeBoundaryObserved=result["timeBoundaryObserved"], policy=result["searchPolicy"])
        row["diagnostics"] = [line for line in log.read_text(encoding="utf-8", errors="replace").splitlines()
                              if any(key in line for key in ("BOSS_TEMPO", "POWER_COMMIT", "POWER_ROUTE", "FAIL", "SEARCH_TIME_BUDGET", "PORTFOLIO"))][-45:]
        rows.append(row)
        (output / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(case, status, row.get("quality", {}).get("won"), flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]), "--matched-evaluate" in sys.argv[2:])
