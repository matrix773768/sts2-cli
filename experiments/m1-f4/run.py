"""Compare frozen F3B C with charged local refinement of its first strict win."""
import argparse
import gzip
import json
from pathlib import Path
import shutil
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "m1-f3d-b"))
from verify import bank, f3a, f3b, native_neutralize, synth

HOST = "m1-f4-build"
TIERS = (128, 512)
VERIFY_LIMIT = 3


def history(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def optimize(output, root, seed, cap, restore):
    clock = perf_counter()
    try:
        with restore(output, root) as (game, _):
            before = game.request("f1_audit")
            response = game.request("i1_f4", arm="C", potions=False, cap=cap, rejected=[],
                                    seed_actions=seed["actions"], seed_stamps=seed["stamps"])
            f3a.equal("native refinement source", before, game.request("f1_audit"))
        if "search" not in response:
            return dict(status=response["status"], transitions=0, candidates=[], reason=response,
                        seed_transitions=0, elapsed_ms=bank.elapsed(clock))
        search = response["search"]
        assert 0 <= search["transitions"] <= cap and search["root_unchanged"]
        assert search["transitions"] == search["seed_transitions"] + sum(
            attempt["transitions"] for attempt in search["attempts"])
        return search | {"elapsed_ms": bank.elapsed(clock)}
    except (f3a.Difference, *bank.ERRORS) as error:
        # A transport timeout cannot expose a reliable partial transition count.
        return dict(bank.failure(error), transitions=None, seed_transitions=None,
                    candidates=[], elapsed_ms=bank.elapsed(clock))


def route_resources(native):
    final = native["native_final"]
    return dict(hp=final["resources"]["hp"], locked_hp=final["outcome"]["final_hp"],
                max_hp=final["resources"]["max_hp"], hp_lost=final["outcome"]["hp_lost"],
                potions_used=final["outcome"]["potions"], potion_slots=final["resources"]["potions"])


def accepted_resources(native):
    assert native["status"] == "win" and native["strict_terminal"], native["status"]
    resources = route_resources(native)
    f3a.equal("dry potions used", [], resources["potions_used"])
    return resources


def refine(output, root, incumbent, spent, cap, restore, cache):
    started = perf_counter()
    baseline = accepted_resources(incumbent["verification"])
    chosen = dict(key=incumbent["winner_key"], resources=baseline, source="first_strict")
    result = dict(cap=cap, first_strict_transitions=spent, selected=chosen, baseline=baseline,
                  validation=[], validation_transitions=0, quality_status="not_run",
                  quality_observed=0, quality_charged=0,
                  seed_replay_transitions=0, predicted_candidates=[], total_charged=spent, delta_hp=0)
    remaining = cap - spent
    if remaining <= len(incumbent["actions"]):
        result.update(quality_status="insufficient_remaining", elapsed_ms=bank.elapsed(started))
        return result

    # Reserve enough for one maximum-length fixed replay when the budget allows.
    # Additional checks can use whatever remains after search and earlier checks.
    reserve = min(f3a.MAX_PLAN, (remaining - len(incumbent["actions"])) // 2)
    search_cap = remaining - reserve
    quality = optimize(output, root, incumbent, search_cap, restore)
    f3b.save_history(output / "quality.json.gz", quality)
    observed = quality["transitions"]
    charged = search_cap if observed is None else observed
    result.update(quality_status=quality["status"], quality_detail=quality.get("detail"),
                  quality_observed=observed, quality_charged=charged, search_cap=search_cap,
                  quality_ms=quality["elapsed_ms"],
                  quality_hot_ms=quality.get("hot_ms"), quality_peak_bytes=quality.get("peak_working_set_bytes"),
                  seed_replay_transitions=quality["seed_transitions"], total_charged=spent + charged)
    candidates = quality["candidates"]
    result["predicted_candidates"] = [
        {k: v for k, v in candidate.items() if k not in ("stamps", "actions")} for candidate in candidates]
    for candidate in sorted(candidates, key=lambda c: (-c["hp"], c["at"], c["key"])):
        if candidate["hp"] <= baseline["locked_hp"] or len(result["validation"]) >= VERIFY_LIMIT:
            break
        fixed_cost = len(candidate["actions"])
        if result["total_charged"] + fixed_cost > cap:
            continue
        # Charge the full requested fixed replay, even on early rejection or when
        # the report can reuse identical evidence from the other budget tier.
        result["total_charged"] += fixed_cost
        result["validation_transitions"] += fixed_cost
        key = (candidate["key"], tuple(candidate["stamps"]))
        reused = key in cache
        if reused:
            evidence, origin = cache[key]
            native_ms = 0
        else:
            clock = perf_counter()
            evidence = f3b.expect_native(output, root, {
                "actions": candidate["actions"], "stamps": candidate["stamps"]}, restore=restore)
            native_ms = bank.elapsed(clock)
            origin = output.name
            cache[key] = (evidence, origin)
        item = dict(key=candidate["key"], predicted_hp=candidate["hp"],
                    discovery_transitions=spent + candidate["at"], status=evidence["status"],
                    evidence_origin=origin, reused_validation=reused, elapsed_ms=native_ms,
                    fixed_prediction_transitions=fixed_cost,
                    matched_actions=evidence.get("matched_actions", 0))
        if evidence["status"] == "win":
            resources = accepted_resources(evidence)
            item["resources"] = resources
            item["comparable_potion_slots"] = resources["potion_slots"] == baseline["potion_slots"]
            if item["comparable_potion_slots"] and resources["hp"] > chosen["resources"]["hp"]:
                chosen = dict(key=candidate["key"], resources=resources, source="refinement",
                              discovery_transitions=item["discovery_transitions"])
        result["validation"].append(item)
        if chosen["resources"]["hp"] == chosen["resources"]["max_hp"]:
            break
    f3b.save_history(output / "native-evidence.json.gz", [
        dict(key=key[0], stamps=key[1], origin=origin, native=evidence)
        for key, (evidence, origin) in cache.items() if origin == output.name])
    result.update(selected=chosen, delta_hp=chosen["resources"]["hp"] - baseline["hp"],
                  elapsed_ms=bank.elapsed(started))
    return result


def run(output, source, selected, control=None):
    reference = bank.read(ROOT / "experiments/m1-s2a/results.json")
    previous = bank.read(ROOT / "experiments/m1-f3d-b/results.json")["cases"]
    versions = bank.versions_for_host(output, HOST)
    for key in ("game_sha256", "solver_sha256", "coreclr"):
        f3a.equal(f"frozen {key}", reference["versions"][key], versions[key])
    clock = perf_counter()
    report = dict(cases={}, versions=versions, cap=TIERS, offline_oracle=True,
                  potions=False, cached_controls=control is not None)
    if control:
        f3a.equal("cached control host", control["report"]["versions"], versions)
    for name in reference["f3b_selection"]:
        if selected and name not in selected:
            continue
        case = output / name
        case.mkdir()
        pin = next(r for r in reference["cases"] if r["case"] == name)
        saved = next(r["root"] for r in source["cases"] if r["case"] == name)
        f3a.equal("frozen spec and live", (pin["spec"], pin["live"]),
                  (saved["spec"], saved["identity"]["live"]))
        root, timing, _ = synth.sample(case, saved["spec"], versions)
        for key in ("public_root", "identity", "native"):
            f3a.equal(f"frozen root {key}", saved[key], root[key])
        root["native_verified"] = True
        restore = native_neutralize if name == "poison-early" else synth.rebuild

        # The shared phase is exactly F3B C. One control at 512 is also the 128
        # control only if all counted trials fit 128 and reproduce F3D-B.
        if control and name in control["report"]["cases"]:
            control_row = control["report"]["cases"][name]
            f3a.equal("cached control root", control_row["live"], pin["live"])
            baseline = control_row["baseline"]
            archive = baseline["history"]
            shutil.copyfile(control["path"] / name / archive, case / archive)
        else:
            baseline = f3b.run_cell(case, root, "C", False, max(TIERS), restore=restore)
        trials = history(case / baseline["history"])
        row = dict(live=pin["live"], root_ms=timing["root_ms"], baseline=baseline, tiers={})
        report["cases"][name] = row
        if baseline["status"] == "native_win":
            seed = trials[-1]
            expected = previous[name]
            f3a.equal("shared control within both tiers",
                      (expected["used"], expected["trials"][-1]["route_key"]),
                      (baseline["used"], seed["winner_key"]))
            fixed_cost = sum(len(trial["actions"]) for trial in trials if "verification" in trial)
            spent = baseline["used"] + fixed_cost
            assert spent <= min(TIERS)
            row.update(baseline_fixed_transitions=fixed_cost, baseline_total_charged=spent)
            row["baseline_resources"] = accepted_resources(seed["verification"])
            cache = {}
            for cap in TIERS:
                stage = case / str(cap)
                stage.mkdir()
                outcome = refine(stage, root, seed, spent, cap, restore, cache)
                row["tiers"][str(cap)] = outcome
                print(name, cap, outcome["quality_status"], outcome["total_charged"],
                      outcome["selected"]["resources"]["hp"], flush=True)
        else:
            print(name, "control failed", baseline["status"], flush=True)
        bank.atomic(output / "results.json", report | {"wall_ms": bank.elapsed(clock)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source", type=Path, default=ROOT / "logs/m1-s2a/formal/records.json")
    parser.add_argument("--case", action="append", help="Limit a diagnostic run to the named frozen cases")
    parser.add_argument("--control", type=Path, help="Reuse frozen control evidence from a previous F4 run")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    sys.addaudithook(f3b.deny_reference_open)
    control = (dict(path=args.control.resolve(), report=bank.read(args.control / "results.json"))
               if args.control else None)
    run(output, bank.read(args.source), args.case, control)


if __name__ == "__main__":
    main()
