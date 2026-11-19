"""Compare both solver binaries against independent native development replays."""
import argparse
from contextlib import contextmanager
import gzip
import importlib.util
import json
import os
from pathlib import Path

from build_solver import FROZEN_HASH, VERSION, digest

HERE = Path(__file__).resolve().parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


e3 = load("e3_replay", HERE.parent / "m1-e3/replay.py")
f5 = load("e3f_f5", HERE.parent / "m1-f5b/run_probe.py")
bank, f3a, synth = e3.bank, e3.f3a, f5.synth
equal = f3a.equal


@contextmanager
def restore(output, root, dll, version):
    os.environ["I1_SOLVER"] = str(dll)
    with f5.session(output) as game:
        identity = game.request("i1_e3f_identity")
        equal("loaded solver DLL", digest(dll), identity["sha256"])
        if not identity["version"].startswith(version):
            raise ValueError(f"Unexpected runtime assembly version: {identity}")
        surfaces, _ = synth.capture(game, root["spec"])
        equal("frozen native root", {key: root[key] for key in surfaces}, surfaces)
        if any(c["id"] == "NEUTRALIZE" for c in root["spec"]["deck"]):
            equal("native Neutralize", {"type": "f2_unpatched", "method": "NeutralizePrefix"},
                  game.request("f1_unpatch_neutralize"))
            equal("unpatch native root", surfaces["native"], game.request("synthetic_snapshot"))
        yield game, identity


def replay(output, root, actions, binaries, partial=False):
    predicted, identities = {}, {}
    for key, (dll, version) in binaries.items():
        with restore(output, root, dll, version) as (game, identity):
            before = game.request("f1_audit")
            reply = game.request("i1_capture", node_budget=f3a.BUDGETS[0][0], fixed_actions=actions,
                                 fixed_prefix=partial)
            equal("native state after fixed replay", before, game.request("f1_audit"))
            equal("fixed frame count", len(actions), len(reply["frames"]))
            predicted[key], identities[key] = reply, identity
    rows = []
    # This independent replay loads the frozen DLL only for inspection and executes native actions.
    with restore(output, root, *binaries["frozen"]) as (game, identity):
        game.teacher_frames, game.teacher_choices = [], []
        start = game.request("i1_begin")["state"]
        for plan in predicted.values():
            equal("prediction/native root frame", start, plan["root"])
        for index, action in enumerate(actions):
            reply = game.request("i1_step", action=action)
            equal("legal native action", "i1_state", reply["type"])
            native = reply["state"]
            row = dict(step=index + 1, action=action, native=native, terminal=reply["terminal"],
                       decision=reply["decision"], terminal_window=reply.get("terminal_window"))
            for key, plan in predicted.items():
                frame = plan["frames"][index]
                row[key] = dict(predicted=frame, differences=e3.s2c.diffs(frame, native, limit=100))
            rows.append(row)
    return dict(root=start, native_identity=identity, prediction_identities=identities, rows=rows)


def search_pair(output, root, binaries):
    results = {}
    for key, binding in binaries.items():
        with restore(output, root, *binding) as (game, identity):
            first = f5.first_win(game, False)
            quality = f5.refine(game, first, False)
            results[key] = dict(identity=identity, first=first, quality=quality,
                                selected=f5.choice(first, quality, 512))
    def semantic(data):
        if data is None:
            return None
        return {key: val for key, val in data.items() if key not in {"rpc_ms", "prepare_ms"}}

    results["diff"] = {stage: f5.f5a.compare(semantic(results["frozen"][stage]),
                                            semantic(results["fixed"][stage]))
                       for stage in ("first", "quality")}
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    build = bank.read(args.build / "build.json")
    patched = (args.build / "bin/CombatSolver.dll").resolve()
    equal("built patch hash", build["patched_sha256"], digest(patched))
    versions = bank.versions_for_host(args.output.resolve(), "m1-e3f-build")
    frozen = Path(os.environ["I1_SOLVER"])
    equal("frozen input hash", FROZEN_HASH, digest(frozen))
    binaries = {"frozen": (frozen, "0.51.5"), "fixed": (patched, VERSION)}
    selection = bank.read(e3.s2c.SELECTION)
    unrelated = next(row["id"] for row in selection["selection"] if row["split"] == "development"
                     and row["id"].startswith("24a989ab"))
    selected = e3.CASES | {"unrelated": unrelated}
    selection.update(selection=[r for r in selection["selection"]
                                if r["split"] == "development" and r["id"] in selected.values()],
                     pilot=list(selected.values()))
    _, roots = e3.s2c.inputs(e3.s2c.ROOT / "logs/m1-s2b/formal", selection, "pilot")
    with gzip.open(HERE.parent / "m1-e3/results.json.gz", "rt", encoding="utf-8") as stream:
        archive = json.load(stream)["cases"]
    results = dict(host_sha256=versions["headless_sha256"], build=build, cases={}, search={})
    path = args.output / "results.json"
    for name, old in archive.items():
        root = roots[selected[name]]["root"]
        actions = [s["action"] for s in old["samples"]]
        evidence = replay(args.output, root, actions, binaries)
        equal("historical native frames", [s["native"] for s in old["samples"]],
              [s["native"] for s in evidence["rows"]])
        equal("historical frozen frames", [s["predicted"] for s in old["samples"]],
              [s["frozen"]["predicted"] for s in evidence["rows"]])
        expected_fixed = [s["differences"] for s in old["samples"]] if name == "enemy_side" else [[] for _ in actions]
        equal("exact patched difference scope", expected_fixed, [s["fixed"]["differences"] for s in evidence["rows"]])
        results["cases"][name] = evidence
        bank.atomic(path, results)
    # Reorder the same first-turn cards: two Backstabs and Strike before Predator.
    # Predator kills enemy 1 at 19 HP while enemy 2 remains alive.
    base = archive["predator_with_potion"]["samples"]
    control = replay(args.output, roots[selected["predator_with_potion"]]["root"],
                     [base[i]["action"] for i in (1, 2, 3, 0)], binaries, partial=True)
    equal("partial lethal enemy health", [0, 36], [f["enemy_hp"] for f in control["rows"][-1]["native"]])
    equal("partial lethal power", 2, control["rows"][-1]["native"][0]["player_powers"]["DRAW_CARDS_NEXT_TURN_POWER"])
    equal("partial lethal parity", [[], [], [], []], [r["fixed"]["differences"] for r in control["rows"]])
    results["cases"]["other_primary_survives"] = control
    bank.atomic(path, results)
    for name in ("predator", "predator_with_potion", "enemy_side", "unrelated"):
        result = search_pair(args.output, roots[selected[name]]["root"], binaries)
        if name in {"enemy_side", "unrelated"}:
            equal("unrelated F3B/F4 parity", {"first": [], "quality": []}, result["diff"])
        results["search"][name] = result
        bank.atomic(path, results)


if __name__ == "__main__":
    main()
