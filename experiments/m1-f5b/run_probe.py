"""Paired offline prediction-only comparison with independent native spot checks."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import importlib.util
from pathlib import Path
from threading import Event
from time import monotonic, perf_counter

HERE = Path(__file__).resolve().parent
F5A = HERE.parent / "m1-f5a"
spec = importlib.util.spec_from_file_location("f5a_probe", F5A / "probe.py")
f5a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f5a)
bank, s2c, synth = f5a.bank, f5a.s2c, f5a.synth
f3a, f3b, quality = s2c.f3a, s2c.f3b, f5a.quality
CAP = 512


def session(output):
    return bank.Session(output, monotonic() + 95, Event())


def terminal_risk(actions):
    return bool(actions and actions[-1].get("card_id") == "PREDATOR")


def timed_request(game, command, **args):
    before = game.request("f1_audit")
    response = game.request(command, arm="C", potions=False, rejected=[], **args)
    rpc_ms = game.last_request_ms
    f3a.equal("unchanged live source", before, game.request("f1_audit"))
    if "search" not in response:
        return dict(status=response["status"], transitions=None, fault=response, rpc_ms=rpc_ms)
    search = response["search"]
    f3a.equal("search root restored", True, search["root_unchanged"])
    if not 0 <= search["transitions"] <= args["cap"]:
        raise ValueError("Transition budget exceeded")
    return search | dict(rpc_ms=rpc_ms, prepare_ms=response["root_prepare_ms"])


def first_win(game, adaptive):
    result = timed_request(game, "i1_f3b", cap=CAP, f5b_adaptive=adaptive)
    history = result.pop("history", [])
    if result["status"] == "predicted_win":
        frame = history[result["winner_node"]]["frame"]
        result["winner"] = dict(key=result["winner_key"], hp=frame["hp"],
                                hp_lost=frame["cumulative_loss"], potions=frame["potions"],
                                actions=result["actions"], stamps=result["stamps"], at=0,
                                predator_terminal=terminal_risk(result["actions"]))
    return result


def refine(game, seed, adaptive, *, cap=CAP):
    if "winner" not in seed or seed["transitions"] == cap:
        return None
    winner = seed["winner"]
    result = timed_request(game, "i1_f4", cap=cap - seed["transitions"], f5b_adaptive=adaptive,
                           seed_actions=[f3b.action_for_wire(a) for a in winner["actions"]],
                           seed_stamps=winner["stamps"], include_history=False)
    result.pop("history", None)
    for candidate in result.get("candidates", []):
        candidate["predator_terminal"] = terminal_risk(candidate["actions"])
    return result


def choice(seed, search, budget):
    if "winner" not in seed or seed["transitions"] > budget:
        return None
    winner = seed["winner"]
    candidates = [c for c in (search or {}).get("candidates", [])
                  if seed["transitions"] + c["at"] <= budget and c["potions"] == winner["potions"]]
    chosen = max([winner, *candidates], key=lambda c: (c["hp"], -c["at"]))
    return {key: chosen[key] for key in ("key", "hp", "hp_lost", "potions", "predator_terminal")}


def run_case(output, row, root, reverse, stress_hp):
    spec = root["spec"] if stress_hp is None else root["spec"] | {"hp": stress_hp}
    result = dict(case=row, stress_hp=stress_hp, reverse=reverse, first={}, refine={},
                  root_resources=None)
    phase = "initialize"
    try:
        with session(output) as game:
            clock = perf_counter()
            surfaces, timing = synth.capture(game, spec)
            result["root_timing"] = timing
            result["root_resources"] = surfaces["identity"]["resources"]
            result["root_identity"] = surfaces["identity"]["live"]
            if stress_hp is None:
                f3a.equal("frozen native source", {k: root[k] for k in surfaces}, surfaces)
            if any(card["id"] == "NEUTRALIZE" for card in spec["deck"]):
                f3a.equal("native Neutralize", {"type": "f2_unpatched", "method": "NeutralizePrefix"},
                          game.request("f1_unpatch_neutralize"))
                f3a.equal("unpatch source", surfaces["native"], game.request("synthetic_snapshot"))
            for name in (("adaptive", "fixed") if reverse else ("fixed", "adaptive")):
                phase = "first_" + name
                result["first"][name] = first_win(game, name == "adaptive")
            tasks = [("fixed", "fixed", False), ("same_seed", "fixed", True),
                     ("adaptive", "adaptive", True)]
            if result["first"]["fixed"].get("winner_key") == result["first"]["adaptive"].get("winner_key"):
                # Same route and remaining budget are both required to reuse the response.
                if result["first"]["fixed"]["transitions"] == result["first"]["adaptive"]["transitions"]:
                    tasks.pop()
            for name, source, adaptive in reversed(tasks) if reverse else tasks:
                phase = "refine_" + name
                result["refine"][name] = refine(game, result["first"][source], adaptive)
            if len(tasks) == 2:
                result["refine"]["adaptive"] = result["refine"]["same_seed"]
                result["adaptive_refine_shared"] = True
            result["prediction_wall_ms"] = bank.elapsed(clock)
    except (f3a.Difference, *bank.ERRORS) as error:
        result["fault"] = dict(phase=phase, **bank.failure(error))
    result["pareto"] = {
        name: {budget: choice(result["first"].get(seed, {}), result["refine"].get(name), budget)
               for budget in (128, 256, CAP)}
        for name, seed in (("fixed", "fixed"), ("same_seed", "fixed"), ("adaptive", "adaptive"))
    }
    return result


def sources(split):
    selection = bank.read(F5A / "selection.json")
    selection["selection"] = [row for row in selection["selection"] if row["split"] == split]
    selection["pilot"] = []
    return s2c.inputs(s2c.ROOT / "logs/m1-s2b/formal", selection, "all")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("split", choices=("development", "validation"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    plan, roots = sources(args.split)
    versions = bank.versions_for_host(args.output, "m1-f5b-build")
    for key in ("game_sha256", "solver_sha256", "coreclr"):
        f3a.equal("frozen " + key, plan["versions"][key], versions[key])
    work = [(item, None) for item in roots.values()]
    if args.split == "development":
        stress = bank.read(HERE / "protocol.json")["stress_development"]
        work.extend((roots[key], hp) for key, hp in stress.items())
    def task(job):
        order, (item, hp) = job
        return run_case(args.output, item["case"], item["root"], order % 2 != 0, hp)
    rows = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        for row in pool.map(task, enumerate(work)):
            rows.append(row)
            print(row["case"]["id"][:8], row["stress_hp"],
                  {arm: v["status"] for arm, v in row["first"].items()}, row.get("fault"), flush=True)
            bank.atomic(args.output / "results.json", dict(versions=versions, cap=CAP, rows=rows))


if __name__ == "__main__":
    main()
