"""Version-bound B1B production with an atomic per-position journal and process recycling."""
import argparse
from contextlib import ExitStack
from functools import partial
import gzip
import json
import os
from pathlib import Path
from threading import Event
from time import monotonic, perf_counter
import importlib.util

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("s3a_b1b", HERE.parent / "m1-b1b/run_probe.py")
b1b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b1b)
bank = b1b.bank
HOST = "m1-s3a-build"
FROZEN = "0.51.5"
FIXED = "0.51.5-e3f.1"
LEGACY_RISKS = {"E3_PREDATOR_TERMINAL", "E3_PREDATOR_FIRST_WIN"}


def solver_binding(output, version, build, qualification=None):
    versions = bank.versions_for_host(output.resolve(), HOST)
    if version == FROZEN:
        dll = Path(os.environ["I1_SOLVER"]).resolve()
        expected = versions["solver_sha256"]
    else:
        if build is None:
            raise ValueError("The fixed solver requires --solver-build")
        if qualification is None:
            with gzip.open(HERE.parent / "m1-e3f/results.json.gz", "rt", encoding="utf-8") as stream:
                qualified = json.load(stream)
        else:
            qualified = bank.read(qualification)
        compiled = bank.read(build / "build.json")
        b1b.equal("qualified E3F build", qualified["build"], compiled)
        patch = HERE.parent / "m1-e3f/predator.patch"
        b1b.equal("E3F source identity",
                  (FIXED, versions["solver_sha256"], versions["game_sha256"], bank.f1.digest(patch.read_bytes())),
                  (compiled["version"], compiled["frozen_sha256"], compiled["game_sha256"],
                   compiled["source_patch_sha256"]))
        expected = compiled["patched_sha256"]
        for name in ("predator", "predator_with_potion", "other_primary_survives"):
            evidence = qualified["cases"][name]
            b1b.equal("qualified actual load", expected, evidence["prediction_identities"]["fixed"]["sha256"])
            b1b.equal("independent native evidence uses frozen inspection DLL", versions["solver_sha256"],
                      evidence["native_identity"]["sha256"])
            if not evidence["rows"] or any(row["fixed"]["differences"] for row in evidence["rows"]):
                raise ValueError("Missing strict E3F qualification")
        dll = (build / "bin/CombatSolver.dll").resolve()
    b1b.equal("selected binary hash", expected, bank.f1.digest(dll.read_bytes()))
    os.environ["I1_SOLVER"] = str(dll)
    return versions | {"solver": version, "solver_sha256": expected}


def attested(output, stack, versions):
    game = stack.enter_context(b1b.Session(output, monotonic() + 180, Event()))
    identity = game.request("i1_s3a_identity")
    b1b.equal("loaded solver hash", versions["solver_sha256"], identity["sha256"])
    if identity["version"].split("+", 1)[0] != versions["solver"]:
        raise ValueError(f"Unexpected loaded Solver version: {identity}")
    return game, identity


def read_manifest(path):
    manifest = bank.read(path)
    b1b.equal("input schema", 1, manifest["input_schema"])
    cases = {case["id"]: case for case in manifest["cases"]}
    order = manifest["sequence"]
    if len(cases) != len(manifest["cases"]) or not order or set(order) - cases.keys():
        raise ValueError("Expected unique cases and positions referencing known IDs")
    for case in cases.values():
        b1b.validate(case["spec"])
        cap = case.get("cap", 512)
        if type(cap) is not int or not 1 <= cap <= 512 or type(case.get("refine", True)) is not bool:
            raise ValueError("Invalid independent budget or F4 setting")
    return manifest, cases, order


def produce(output, input_path, version, build, default_cap, first_only, cold, max_new=None, qualification=None):
    manifest, cases, order = read_manifest(input_path)
    output.mkdir(parents=True, exist_ok=True)
    journal = output / "records"
    journal.mkdir(exist_ok=True)
    with bank.writer(output):
        versions = solver_binding(output, version, build, qualification)
        contract = dict(schema=2, input_sha256=bank.stamp(manifest), versions=versions,
                        policy="F3B-C/F4-fixed", default_cap=default_cap, first_only=first_only,
                        cold=cold, active_potions=False, offline_oracle=True, uses_hidden_rng=True)
        stamp = bank.stamp(contract)
        contract_path = output / "contract.json"
        if contract_path.exists():
            b1b.equal("resume contract", bank.read(contract_path), contract)
        else:
            bank.atomic(contract_path, contract)
        completed = []
        for index in range(len(order)):
            path = journal / f"{index + 1:04d}.json"
            if not path.exists():
                break
            row = bank.read(path)
            b1b.equal("journal position", (index + 1, order[index], stamp),
                      (row["ordinal"], row["input"]["id"], row["contract_sha256"]))
            completed.append(row)
        b1b.equal("contiguous journal", len(completed), len(list(journal.glob("*.json"))))
        prior = len(completed)
        started = perf_counter()
        game = identity = None
        seen = {}
        with ExitStack() as worker:
            for index in range(prior, min(len(order), prior + max_new) if max_new else len(order)):
                case = cases[order[index]]
                start = perf_counter()
                launched = game is None
                handshake = launch_ms = 0
                try:
                    if launched:
                        game, identity = attested(output, worker, versions)
                        handshake = game.startup_ms
                        launch_ms = bank.elapsed(start)
                    search = partial(b1b.search, cap=case.get("cap", default_cap),
                                     refine_quality=not first_only and case.get("refine", True),
                                     predator_fixed=version == FIXED)
                    row = b1b.execute(game, case, None, search_root=search)
                    b1b.record_handshake(row, handshake)
                    previous = seen.get(case["id"])
                    semantic = (row.get("semantic_sha256"), row.get("root_profile_sha256"),
                                (row.get("retirement") or {}).get("native_frames_sha256"))
                    if previous is not None and previous != semantic:
                        row["discard_reason"] = "resident_repeat_differential"
                    if not row.get("discard_reason"):
                        seen[case["id"]] = semantic
                except b1b.ERRORS as error:
                    if isinstance(error, (ValueError, b1b.f5b.f3a.Difference)):
                        raise
                    row = dict(input=case, outcome="unresolved", failure=bank.failure(error),
                               discard_reason="engine_startup_or_transport", synthetic=True,
                               natural_reachability="unknown", evidence_level="prediction_only")
                row.update(ordinal=index + 1, contract_sha256=stamp, solver=versions["solver"],
                           solver_sha256=versions["solver_sha256"], loaded_solver=identity,
                           record_schema=2, cap=case.get("cap", default_cap), started_cold=launched,
                           launch_ms=launch_ms, elapsed_ms=bank.elapsed(start))
                if row.get("discard_reason") or cold:
                    if game is not None and row.get("discard_reason"):
                        game.engine.close(graceful=False)
                        row["discard_exit_code"] = game.engine.proc.returncode
                    worker.close()
                    game = identity = None
                    seen.clear()
                bank.atomic(journal / f"{index + 1:04d}.json", row)
                completed.append(row)
                print(index + 1, case["id"], row.get("first", {}).get("status", row["outcome"]),
                      row.get("discard_reason", ""), flush=True)
        bank.atomic(output / "results.json", dict(contract=contract, rows=completed,
                                                  resumed_count=prior, new_count=len(completed) - prior,
                                                  elapsed_ms=bank.elapsed(started)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("produce", "catalog"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--input", type=Path, default=HERE.parent / "m1-b1b/inputs.json")
    parser.add_argument("--solver", choices=(FROZEN, FIXED), default=FROZEN)
    parser.add_argument("--solver-build", type=Path)
    parser.add_argument("--qualification", type=Path)
    parser.add_argument("--cap", type=int, choices=range(1, 513), default=512)
    parser.add_argument("--first-only", action="store_true")
    parser.add_argument("--cold", action="store_true")
    parser.add_argument("--max-new", type=int, choices=range(1, 10001), metavar="N")
    args = parser.parse_args()
    if args.mode == "catalog":
        args.output.mkdir(parents=True, exist_ok=False)
        versions = solver_binding(args.output, args.solver, args.solver_build, args.qualification)
        with ExitStack() as worker:
            game, _ = attested(args.output, worker, versions)
            bank.atomic(args.output / "catalog.json", game.request("synthetic_catalog"))
    else:
        produce(args.output, args.input, args.solver, args.solver_build,
                args.cap, args.first_only, args.cold, args.max_new, args.qualification)


if __name__ == "__main__":
    main()
