"""Run frozen diagnostic candidates, resource perturbations and independent native spot checks."""
import argparse
from contextlib import ExitStack, contextmanager
import gzip
import importlib.util
import json
from pathlib import Path
from time import perf_counter

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("s3b_produce", HERE.parent / "m1-s3a/produce.py")
s3a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s3a)
s3a.HOST = "m1-s3b-build"
b1b, bank = s3a.b1b, s3a.bank
f3a, f3b = b1b.f5b.f3a, b1b.f5b.f3b


@contextmanager
def restored(output, case, versions, expected=None):
    with ExitStack() as stack:
        game, identity = s3a.attested(output, stack, versions)
        surfaces, timing = b1b.synth.capture(game, case["spec"])
        root_hash = bank.stamp(surfaces)
        if expected is not None:
            b1b.equal("same native root", expected, root_hash)
        yield game, dict(solver=identity, root_sha256=root_hash, root_timing=timing)


def candidate(output, case, versions, expected, mode, cap):
    started = perf_counter()
    row = dict(method=mode, budget=cap, status="not_run", transitions=None, uses_hidden_rng=True,
               active_potions=False, budget_unit="nodes" if mode == "full_solver" else "transitions")
    try:
        with restored(output, case, versions, expected) as (game, root):
            row.update(root)
            before = game.request("f1_audit")
            if mode == "full_solver":
                reply = game.request("i1_capture", node_budget=cap)
                row["search_rpc_ms"] = game.last_request_ms
                row["result"] = reply
                row.update(status=reply["status"], transitions=reply.get("transitions"),
                           hot_ms=reply.get("solve_ms"), frame_replay_transitions=len(reply.get("frames", [])))
                if reply["status"] == "complete_win" and reply.get("predicted_win"):
                    frame = reply["frames"][-1][0]
                    row["winner"] = dict(actions=reply["actions"], hp=frame["player_hp"],
                                         potions=frame["player_potions"], max_hp=frame["player_max_hp"],
                                         gold=frame["player_gold"],
                                         stamps=[bank.f1.digest(f[0]["exact_continuation_state"].encode())
                                                 for f in reply["frames"]])
            else:
                reply = game.request("i1_f3b", arm="B" if mode == "beam_b" else "C",
                                     potions=False, cap=cap, rejected=[])
                row["search_rpc_ms"] = game.last_request_ms
                obs = reply.get("search", reply)
                row["result"] = obs
                row.update(status=obs["status"], transitions=obs.get("transitions"),
                           hot_ms=obs.get("hot_ms"), prediction_prepare_ms=reply.get("root_prepare_ms"))
                if "search" in reply:
                    b1b.equal("immutable solver root", True, obs["root_unchanged"])
                if obs["status"] == "predicted_win":
                    frame = obs["history"][obs["winner_node"]]["frame"]
                    row["winner"] = dict(actions=[f3b.action_for_wire(a) for a in obs["actions"]],
                                         hp=frame["hp"], hp_lost=frame["cumulative_loss"],
                                         potions=frame["potions"], stamps=obs["stamps"],
                                         max_hp=frame["max_hp"], gold=frame["gold"],
                                         prediction_gaps=frame["gaps"])
            b1b.equal("search left native root intact", before, game.request("f1_audit"))
            if "winner" in row:
                winner = row["winner"]
                winner["net_hp_loss"] = case["spec"]["hp"] - winner["hp"]
                if any(a["kind"] == "UsePotion" for a in winner["actions"]):
                    raise ValueError("Search did not preserve no-potion policy")
    except b1b.ERRORS as error:
        row.pop("winner", None)
        row.update(bank.failure(error))
    row["elapsed_ms"] = bank.elapsed(started)
    return row


def audit(output, case, versions, result):
    winner = result["winner"]
    evidence = dict(method=result["method"], case=case["id"])
    try:
        with restored(output, case, versions, result["root_sha256"]) as (game, _):
            plan = game.request("i1_capture", node_budget=1000, fixed_actions=winner["actions"])
            b1b.equal("fixed frames", winner["stamps"],
                      [bank.f1.digest(f[0]["exact_continuation_state"].encode()) for f in plan["frames"]])
        with restored(output, case, versions, result["root_sha256"]) as (game, _):
            f3a.replay_live(game, None, plan, evidence)
    except f3a.Difference as error:
        evidence.update(status="strict_difference", first_difference=dict(
            phase=error.phase, predicted=error.expected, native=error.actual))
    except bank.ERRORS as error:
        evidence.update(bank.failure(error))
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver-build", type=Path, required=True)
    parser.add_argument("--trace-case", help="Retain complete C512 history for a declared diagnostic root")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    versions = s3a.solver_binding(args.output, s3a.FIXED, args.solver_build)
    protocol = bank.read(HERE / "diagnostic-plan.json")
    with gzip.open(HERE.parent / "m1-s3a/hard.json.gz", "rt", encoding="utf-8") as stream:
        source = {r["input"]["id"]: r for r in json.load(stream)["rows"]}
    b1b.equal("512 frozen solver", {versions["solver_sha256"]},
              {r["solver_sha256"] for r in source.values()})
    output = dict(schema=1, protocol=protocol, versions=versions, rows=[], perturbations=[], native_audits=[])
    path = args.output / "results.json"
    if args.trace_case:
        if args.trace_case not in protocol["exhausted"] + protocol["capped"]:
            raise ValueError("Trace root must be in the frozen diagnostic protocol")
        original = source[args.trace_case]
        row = candidate(args.output, original["input"], versions, original["root_sha256"], "c_trace", 512)
        b1b.equal("frozen C status and budget", (original["first"]["status"], original["first"]["transitions"]),
                  (row["status"], row["transitions"]))
        bank.atomic(path, output | {"trace": row, "input": original["input"]})
        return
    for group in ("exhausted", "capped"):
        for key in protocol[group]:
            original = source[key]
            b1b.equal("development only", "development", original["input"]["split"])
            b1b.equal("diagnostic stratum", "exhausted" if group == "exhausted" else "transition_cap",
                      original["first"]["status"])
            methods = [("beam_b", protocol["beam_b_transitions"]),
                       ("full_solver", protocol["full_solver_nodes"])]
            if group == "capped":
                methods.append(("c_extended", protocol["continued_c_transitions"]))
            runs = [candidate(args.output, original["input"], versions, original["root_sha256"], m, n)
                    for m, n in methods]
            winning = next((r for r in runs if "winner" in r), None)
            diagnosis = "predicted_witness" if winning else "solvability_unknown"
            output["rows"].append(dict(id=key, group=group, original=original["first"], input=original["input"],
                                       root_sha256=original["root_sha256"], diagnosis=diagnosis, runs=runs))
            if winning and len(output["native_audits"]) < protocol["native_max_controls"]:
                output["native_audits"].append(audit(args.output, original["input"], versions, winning))
            print(key, group, [r["status"] for r in runs], flush=True)
            bank.atomic(path, output)
    for key in protocol["hp_perturbation"]:
        original = source[key]["input"]
        spec = original["spec"] | {"hp": min(original["spec"]["max_hp"],
                                           original["spec"]["hp"] + protocol["hp_delta"])}
        changed = original | {"id": "hp-" + bank.stamp([key, spec])[:16], "spec": spec,
                              "source_case": key, "generation_source": "s3b_hp_perturbation"}
        row = candidate(args.output, changed, versions, None, "c_perturbed", 512)
        b1b.equal("changed root identity", False, row.get("root_sha256") == source[key]["root_sha256"])
        output["perturbations"].append(dict(input=changed, old_hp=original["spec"]["hp"], result=row))
        bank.atomic(path, output)


if __name__ == "__main__":
    main()
