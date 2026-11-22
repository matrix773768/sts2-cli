"""Run the existing II-J fixtures and five single-root attempts on one build."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent
SOLVER_SHA = "2c7a9ec1d0f6a58226be9aee9230268b40ab96fa6efe582cddf2e376b9a18e5f"
CHECKS = (
    ("quasar", "iij1/verify_choices.py", ("quasar",)),
    ("cleanse", "iij1/verify_choices.py", ("instances",)),
    ("related", "iij1/verify_choices.py", ("related",)),
    ("guards", "iij2/verify_guards.py", ()),
    ("daggers", "iij3/verify_daggers.py", ("compare",)),
    ("hammer-route", "iij4/verify_route.py", ()),
    ("power", "iij4/verify_power.py", ()),
    ("guards-sample", "iij2/resample.py", ()),
    ("daggers-sample", "iij3/resample_pair.py", ()),
    ("hammer-sample", "iij4/resample_hammer.py", ()),
    ("quasar-route", "iij5a/verify_quasar.py", ("route",)),
    ("quasar-sample", "iij5a/verify_quasar.py", ("sample",)),
)


def run(output, solver, workers):
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    status = subprocess.check_output(["git", "status", "-sb"], text=True).strip()
    build = json.loads((solver / "build.json").read_bytes())
    assert (build["version"], build["patched_sha256"]) == ("0.51.5-iij.4", SOLVER_SHA)
    output.mkdir(parents=True)
    env = os.environ | {"STS2_DOTNET": str(Path("logs/m0-v5/dotnet9/dotnet.exe").resolve()),
                        "STS2_DOTNET_VERSION": "9.0.7", "PYTHONUTF8": "1"}

    def check(item):
        name, script, args = item
        command = [sys.executable, str(HERE.parent / f"m1-nosl3c-{script}"),
                   *args, str(output / name), str(solver)]
        start = perf_counter()
        with (output / f"{name}.log").open("wb") as log:
            result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        return dict(name=name, command=command, exit=result.returncode, seconds=perf_counter() - start)

    start = perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        checks = list(pool.map(check, CHECKS))
    result = dict(head=head, status=status, build=build, workers=workers,
                  seconds=perf_counter() - start, checks=checks)
    (output / "run.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return int(any(check["exit"] for check in checks))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", type=Path, default=Path("logs/iij4-solver"))
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    raise SystemExit(run(args.output.resolve(), args.solver.resolve(), args.workers))
