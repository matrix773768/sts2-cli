"""Compare first-win searches on a root-only dataset, then verify generated winning routes."""
import argparse
import gzip
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-f3a"))
spec = importlib.util.spec_from_file_location("f3a_benchmark", HERE.parent / "m1-f3a/benchmark.py")
f3a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f3a)
f1 = f3a.f1
TIERS = (128, 512, 2048)
KINDS = ("PlayCard", "UsePotion", "EndTurn")
MAX_NATIVE_CHECKS = 3


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_history(path, value):
    with path.open("wb") as stream, gzip.GzipFile(filename="", mode="wb", mtime=0, fileobj=stream) as archive:
        archive.write(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


def action_for_wire(action):
    kind = action["kind"]
    return {**action, "kind": KINDS[kind] if isinstance(kind, int) else kind}


def prepare_native(output, root, result, *, restore=f3a.restored):
    actions = [action_for_wire(a) for a in result["actions"]]
    preparation, plan = f3a.search(output, root, f3a.BUDGETS[0], actions, restore=restore)
    if not plan or preparation["status"] != "complete_win":
        return dict(status="independent_prediction_rejected", preparation=preparation), None
    stamps = [f1.digest(step[0]["exact_continuation_state"].encode()) for step in plan["frames"]]
    mismatch = next((i for i, (a, b) in enumerate(zip(stamps, result["stamps"]), 1) if a != b), None)
    if mismatch is not None or len(stamps) != len(result["stamps"]):
        return dict(status="search_fixed_prediction_difference", preparation=preparation,
                    first_difference=mismatch, expected=stamps, actual=result["stamps"]), None
    return preparation, plan


def expect_native(output, root, result, *, restore=f3a.restored, keep_frames=False):
    preparation, plan = prepare_native(output, root, result, restore=restore)
    if plan is None:
        return preparation
    native = f3a.replay(output, root, plan, restore=restore)
    native["preparation"] = preparation
    if keep_frames:
        native["fixed_plan"] = plan
    return native


def search(output, root, arm, potions, cap, rejected, *, restore=f3a.restored):
    with restore(output, root) as (game, _):
        audit = game.request("f1_audit")
        response = game.request("i1_f3b", arm=arm, potions=potions, cap=cap, rejected=rejected)
        rpc_ms = game.last_request_ms
        f3a.equal("native_source", audit, game.request("f1_audit"))
        if "search" not in response:
            return dict(status=response["status"], transitions=0, fault=response)
        result = response["search"]
        assert result["transitions"] <= cap and result["root_unchanged"]
        result["search_rpc_ms"] = rpc_ms
        result["prediction_prepare_ms"] = response["root_prepare_ms"]
        return result


def run_cell(output, root, arm, potions, cap, *, restore=f3a.restored,
             charge_fixed=False, keep_frames=False):
    trials, rejected, compact = [], [], []
    used = 0
    fixed = 0
    status = "not_run"
    first_prediction = None
    native_win = None
    start = perf_counter()
    for _ in range(MAX_NATIVE_CHECKS):
        if used + fixed == cap:
            break
        try:
            result = search(output, root, arm, potions, cap - used - fixed, rejected, restore=restore)
        except (f1.i2.StopRun, RuntimeError, OSError, TimeoutError, f3a.Difference) as error:
            # In strict accounting a failed transport cannot expose its partial cost.
            result = dict(status=f1.classify(error), detail=str(error),
                          transitions=cap - used - fixed if charge_fixed else 0,
                          **({"cost_is_upper_bound": True} if charge_fixed else {}))
        used += result["transitions"]
        status = result["status"]
        if status == "predicted_win":
            if first_prediction is None:
                first_prediction = used
            if charge_fixed:
                cost = len(result["actions"])
                if cost > cap - used - fixed:
                    status = "prediction_only_budget"
                    trials.append(result | {"validation_skipped": status})
                    compact.append(dict(status=status, transitions=result["transitions"],
                                        winner_key=result["winner_key"]))
                    break
                fixed += cost
            verified = expect_native(output, root, result, restore=restore, keep_frames=keep_frames)
            result["verification"] = verified
            status = verified["status"]
            if status == "win":
                status = "native_win"
                native_win = used + fixed
            else:
                rejected.append(result["winner_key"])
        trials.append(result)
        brief = {k: v for k, v in result.items() if k not in ("history", "routes", "verification", "actions", "stamps")}
        if "routes" in result:
            brief["rollouts"] = len(result["routes"])
            brief["rollout_stops"] = {stop: sum(r["stop"] == stop for r in result["routes"])
                                     for stop in sorted({r["stop"] for r in result["routes"]})}
            brief["node_stops"] = {stop: sum(n["frame"]["stop"] == stop for n in result["history"])
                                   for stop in sorted({n["frame"]["stop"] for n in result["history"]})}
        if "verification" in result:
            brief["verification"] = {k: v for k, v in result["verification"].items()
                                     if k not in ("trace", "first_difference", "fixed_plan")}
            if status == "native_win":
                winner = [r for r in result["routes"] if r["stop"] == "predicted_win"]
                brief["winning_plan"] = winner[-1]["plan"] if winner else {"strategy": "beam"}
        compact.append(brief)
        if status == "native_win" or result["status"] != "predicted_win" or arm == "A":
            break
    tiers = {}
    for tier in [v for v in TIERS if v <= cap] or [cap]:
        if native_win is not None and native_win <= tier:
            tiers[str(tier)] = "native_win"
        elif used + fixed >= tier and (first_prediction is None or first_prediction > tier):
            tiers[str(tier)] = "no_win_within_budget"
        elif used + fixed > tier:
            tiers[str(tier)] = "prediction_only"
        else:
            tiers[str(tier)] = status
    label = f"{root['id']}-{arm}-{'allow' if potions else 'dry'}"
    archive_path = output / f"{label}.json.gz"
    save_history(archive_path, trials)
    print(label, status, used, flush=True)
    return dict(id=root["id"], encounter=root["identity"]["encounter"], arm=arm, potions=potions,
                status=status, used=used, first_prediction=first_prediction, first_native=native_win,
                tiers=tiers, **({"fixed_transitions": fixed, "total_charged": used + fixed}
                                if charge_fixed else {}), hot_ms=sum(t.get("hot_ms", 0) for t in trials),
                cpu_ms=sum(t.get("cpu_ms", 0) for t in trials),
                wall_ms=f1.ms(start), trials=compact, history=archive_path.name)


def stage_roots(source, output, sentinel):
    manifest = load(source / "manifest.json")
    if (manifest["game_sha256"], manifest["solver_sha256"]) != (f1.i2.NATIVE_HASH, f1.i2.SOLVER_HASH):
        raise ValueError("Unexpected game/solver identities")
    roots = manifest["roots"]
    if sentinel:
        roots = [r for r in roots if r["id"] == "ironclad-a0-run_1-f05"]
    else:
        pinned = load(HERE.parent / "m1-f3a/manifest.json")["roots"]
        if [(r["id"], r["identity"]) for r in roots] != [(r["id"], r["identity"]) for r in pinned]:
            raise ValueError("Root identities differ from the frozen F3A manifest")
    for root in roots:
        name = root["checkpoint"]
        if Path(name).name != name:
            raise ValueError("Expected a local checkpoint filename")
        shutil.copyfile(source / name, output / name)
    f1.write(output / "input-roots.json", [dict(id=r["id"], sha256=r["checkpoint_sha256"],
             live=r["identity"]["live"]) for r in roots])
    return roots


def deny_reference_open(event, args):
    if event == "open" and isinstance(args[0], (str, bytes)):
        name = Path(args[0].decode() if isinstance(args[0], bytes) else args[0]).name
        if "reference-routes" in name.lower():
            raise PermissionError("Offline teacher actions are excluded from this benchmark")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cap", type=int, default=TIERS[-1], choices=TIERS)
    parser.add_argument("--arm", choices=("A", "B", "C", "D"), action="append")
    parser.add_argument("--root")
    parser.add_argument("--sentinel", action="store_true")
    args = parser.parse_args()
    sys.addaudithook(deny_reference_open)
    output = args.output.resolve()
    output.mkdir(parents=True)
    roots = stage_roots(args.source.resolve(), output, args.sentinel)
    f3a.setup(output, "m1-f3b-build")
    rows = []
    for root in roots:
        if args.root and root["id"] != args.root:
            continue
        for arm in args.arm or ("A", "B", "C", "D"):
            for potions in (False,) if arm == "A" or args.sentinel else (False, True):
                rows.append(run_cell(output, root, arm, potions, args.cap))
                f1.write(output / "results.json", rows)


if __name__ == "__main__":
    main()
