"""Sample and compare native combat roots from bounded, legal runs."""
import argparse
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import random
import sys
from time import monotonic, perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / name) for name in ("experiments/m1-i1", "python", "tests")]
spec = importlib.util.spec_from_file_location("offline_teacher", ROOT / "experiments/m1-i2/run.py")
i2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(i2)
from room_policy import combat_action
from run_route_smoke import choose_action, UnsupportedDecision

ROUTES = (("Ironclad", 0, "run_1"), ("Silent", 0, "run_2"),
          ("Ironclad", 10, "run_2"), ("Defect", 10, "run_1"))
ACTION_LIMIT = 140
DLL = ROOT / "logs/m1-f1-build/Headless/bin/Debug/net9.0/OfflineSearchHarness.dll"
BOSS_ROUTE = ROOT / "tests/boss_reward_run_1.jsonl"


def digest(data):
    return sha256(data).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ms(start):
    return (perf_counter() - start) * 1000


def action(command):
    return {key: value for key, value in command.items() if key != "cmd"}


class Session(i2.OfflineTeacherRun):
    def __init__(self, output, seconds=35):
        super().__init__("", output)
        self.deadline = monotonic() + seconds

    def __enter__(self):
        self.engine = i2.engine_client.EngineClient(
            deadline=self.deadline, log_root=self.output, command_timeout=12)
        return self

    def __exit__(self, kind, error, traceback):
        self.engine.close(graceful=kind is None)

    def request(self, cmd, **args):
        try:
            response = super().request(cmd, **args)
        except i2.StopRun as error:
            if cmd == "i1_capture" and str(error).startswith("PredictionUnsupportedException:"):
                raise i2.StopRun("unsupported", str(error)) from error
            raise
        if cmd == "i1_step" and response.get("state"):
            self.teacher_frames.append(response["state"][0])
        return response


def sample(output, character, ascension, seed, scripted=None):
    route_id = f"{character.lower()}-a{ascension}-{seed}" + ("-archive" if scripted else "")
    rng = random.Random(seed)
    commands, candidates = 0, []
    route = dict(id=route_id, character=character, ascension=ascension, seed=seed,
                 source="tests/boss_reward_run_1.jsonl" if scripted else "simple_run")
    last = None
    try:
        with Session(output, seconds=65) as game:
            start = dict(cmd="start_run", character=character, ascension=ascension, seed=seed, lang="en")
            state = game.request(**start)
            commands = 1
            for _ in range(i2.STEP_LIMIT):
                decision = state["decision"]
                last = state.get("context")
                if decision == "game_over":
                    route["status"] = "run_victory" if state["victory"] else "death"
                    break
                if scripted:
                    if commands == len(scripted):
                        route["status"] = "archived_boss_reward" if (
                            decision == "card_reward" and last["room_type"] == "Boss") else "archive_boundary_mismatch"
                        break
                    command = scripted[commands]
                    if command["cmd"] != "action":
                        raise i2.StopRun("archive_command", "Expected a native action")
                elif decision == "combat_play":
                    command = combat_action(state)
                elif decision == "treasure":
                    command = dict(action="proceed")
                else:
                    command, _ = choose_action(state, rng)
                if decision == "map_select":
                    path = output / f"{route_id}-{commands:03}.save.json"
                    saved = game.request("write_continue_save", path=str(path))
                    if not saved.get("success") or saved.get("room_type") != "MapRoom":
                        raise i2.StopRun("checkpoint_error", str(saved))
                    state = game.execute_action(command)
                    commands += 1
                    if state["decision"] == "combat_play":
                        identity = game.request("f1_begin")
                        candidates.append(dict(
                            id=f"{route_id}-f{state['context']['floor']:02}",
                            route=route_id, character=character, ascension=ascension, seed=seed,
                            context=state["context"], identity=identity, public_root=state,
                            checkpoint=path.name, checkpoint_sha256=digest(path.read_bytes()),
                            entry=action(command), prefix_length=commands,
                        ))
                else:
                    state = game.execute_action(command)
                    commands += 1
            else:
                route["status"] = "action_limit"
    except (i2.StopRun, UnsupportedDecision, TimeoutError, RuntimeError, OSError) as error:
        route.update(status=classify(error), detail=str(error))
    route.update(actions=max(0, commands - 1), final_context=last,
                 encountered=[{**c["context"], "encounter": c["identity"]["encounter"]} for c in candidates])
    # Early anchors plus first Elite and Boss. If slots remain, take latest normal roots.
    normal = [c for c in candidates if c["context"]["room_type"] == "Monster"]
    specials = [next((c for c in candidates if c["context"]["room_type"] == kind), None)
                for kind in ("Elite", "Boss")]
    if scripted:
        selected = [c for c in specials if c]
        for root in selected:
            root["archived_suffix"] = scripted[root["prefix_length"]:]
        return route, selected
    selected = normal[:2] + [c for c in specials if c]
    selected += list(reversed(normal[2:]))[:4 - len(selected)]
    return route, sorted(selected, key=lambda c: c["prefix_length"])


def classify(error):
    if isinstance(error, i2.StopRun):
        return error.status
    if isinstance(error, UnsupportedDecision):
        return "unsupported"
    if isinstance(error, TimeoutError):
        return "time_limit"
    return "execution_fault"


def outcome(result, state):
    final = result["native_final"]
    data = final["outcome"]
    if state["decision"] == "game_over" and state.get("victory") is False and state["player"]["hp"] == 0:
        return "death"
    if final["terminal_callback"] and data["survived"] and data["final_enemy_hp"] == 0:
        return "win"
    return "unsupported" if state["decision"] not in ("card_reward", "map_select", "game_over") else "execution_fault"


def play(game, state, result, mode, forced):
    trace = result["trace"]
    if mode == "archive":
        for command in forced[:ACTION_LIMIT]:
            trace.append(dict(action=action(command), round=state.get("round"),
                              player_hp=state["player"]["hp"], energy=state.get("energy")))
            state = game.execute_action(command)
            trace[-1]["execute_wall_ms"] = game.last_request_ms
            if state["decision"] not in ("combat_play", "card_select"):
                break
        return state
    if mode == "C":
        game.teacher_frames = result["teacher_frames"] = []
        result.update(executed=trace, matched_actions=0, differential="not_run")
        clock = perf_counter()
        try:
            state = game.teacher(state, result)
        finally:
            result["teacher_total_ms"] = ms(clock)
        if result.get("fallback_reason"):
            result["status"] = result["fallback_reason"]
        elif result["differential"] != "pass":
            result["status"] = "prediction_mismatch"
        return state
    start = monotonic()
    for index in range(1, ACTION_LIMIT + 1):
        if state["decision"] != "combat_play":
            return state
        if monotonic() - start >= 20:
            result["status"] = "time_limit"
            return state
        row = dict(step=index, round=state["round"], player_hp=state["player"]["hp"],
                   energy=state["energy"], block=state["player"].get("block"), enemies=state["enemies"],
                   hand=state["hand"])
        trace.append(row)
        if mode == "A":
            clock = perf_counter()
            row["action"] = combat_action(state)
            row["decision_ms"] = ms(clock)
            state = game.execute_action(row["action"])
            row["execute_wall_ms"] = game.last_request_ms
            if state["decision"] == "card_select":
                clock = perf_counter()
                command, _ = choose_action(state, None)
                trace.append(dict(step=index, action=action(command), decision_ms=ms(clock), phase="choice"))
                state = game.execute_action(command)
                trace[-1]["execute_wall_ms"] = game.last_request_ms
        else:
            params = {"force": forced[1]} if forced and index == forced[0] else {}
            data = game.request("f1_step", step=index, **params)
            row["execute_wall_ms"] = game.last_request_ms
            state = data.pop("decision")
            row.update({k: v for k, v in data.items() if k != "type"})
            row["forced"] = bool(params)
            if row.get("choice_failure"):
                result.update(status="unsupported", detail=row["choice_failure"])
                return state
            if state.get("type") == "error":
                game.engine_error(state)
        row["after_hp"] = state.get("player", {}).get("hp")
        row["after_round"] = state.get("round")
        row["after_energy"] = state.get("energy")
        row["after_hand"] = [c["id"] for c in state.get("hand", [])]
    if state["decision"] == "combat_play":
        result["status"] = "action_limit"
    return state


def measure(output, root, mode, forced=None):
    result = dict(id=root["id"], policy="B_cf" if mode == "B" and forced else mode, trace=[])
    if result["policy"] == "B_cf":
        result["intervention"] = dict(step=forced[0], action=forced[1])
    start = perf_counter()
    try:
        with Session(output) as game:
            path = output / root["checkpoint"]
            source = path.read_bytes()
            if digest(source) != root["checkpoint_sha256"]:
                raise i2.StopRun("root_mismatch", "Checkpoint bytes changed")
            restored = game.request("load_save", path=str(path), lang="en")
            if restored["decision"] != "map_select":
                raise i2.StopRun("root_mismatch", "Restored outside map")
            state = game.execute_action(root["entry"])
            identity = game.request("f1_begin")
            matched = identity == root["identity"] and state == root["public_root"]
            result["checkpoint_match"] = matched
            if not matched:
                raise i2.StopRun("root_mismatch", "Checkpoint did not reproduce the live and public root")
            result.update(root_verified=True, cold_root_ms=ms(start), coreclr=game.engine.runtime_version)
            try:
                state = play(game, state, result, mode, forced)
            finally:
                if game.engine.proc.poll() is None:
                    result["native_final"] = game.request("f1_final")
            if "status" not in result:
                result["status"] = outcome(result, state)
            if path.read_bytes() != source:
                raise i2.StopRun("root_mismatch", "Source checkpoint mutated")
            result["peak_working_set_bytes"] = game.report["peak_working_set_bytes"]
    except (i2.StopRun, TimeoutError, RuntimeError, OSError, UnsupportedDecision) as error:
        result.update(status=classify(error), detail=str(error))
    result["elapsed_ms"] = ms(start)
    print(root["id"], result["policy"], result["status"], flush=True)
    return result


def setup(output):
    for path, expected in ((ROOT / "lib/sts2.dll", i2.NATIVE_HASH), (i2.SOLVER, i2.SOLVER_HASH)):
        if digest(path.read_bytes()) != expected:
            raise ValueError(f"Unexpected pinned binary: {path}")
    os.environ.update(I1_SOLVER=str(i2.SOLVER), I1_LOG=str(output), DOTNET_GCHeapHardLimit="10000000")
    os.environ.setdefault("I1_RITSU", str(Path.home() / "Desktop/STEAM/steamapps/workshop/content/2868840/3747602295"))
    os.environ.setdefault("STS2_DOTNET", str(ROOT / "logs/m1-review-dotnet/dotnet.exe"))
    os.environ.setdefault("STS2_DOTNET_VERSION", "9.0.7")
    native = i2.engine_client.headless_command()
    i2.engine_client.headless_command = lambda: [*native[:-1], str(DLL)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--stage", choices=("all", "sample", "evaluate", "teacher", "intervene"), default="all")
    parser.add_argument("--intervention", nargs=3, action="append", default=[],
                        metavar=("ROOT", "REFERENCE", "STEP"))
    args = parser.parse_args()
    output = args.output.resolve()
    if args.stage in ("all", "sample"):
        output.mkdir(parents=True)
    setup(output)
    if args.stage in ("all", "sample"):
        runs, roots = [], []
        for route in ROUTES:
            summary, selected = sample(output, *route)
            print(summary["id"], summary["status"], len(selected), flush=True)
            runs.append(summary)
            roots.extend(selected)
        archive = [json.loads(line) for line in BOSS_ROUTE.read_text(encoding="utf-8").splitlines()]
        summary, selected = sample(output, "Ironclad", 0, "run_1", archive)
        print(summary["id"], summary["status"], len(selected), flush=True)
        runs.append(summary)
        roots.extend(selected)
        write(output / "manifest.json", dict(schema=1, routes=runs, roots=roots,
                                             game_sha256=i2.NATIVE_HASH, solver_sha256=i2.SOLVER_HASH))
    if args.stage == "sample":
        return
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    if args.stage == "intervene":
        roots = {root["id"]: root for root in manifest["roots"]}
        results = json.loads((output / "results.json").read_text(encoding="utf-8"))
        by_key = {(row["id"], row["policy"]): row for row in results}
        for root_id, reference, step_text in args.intervention:
            step = int(step_text)
            baseline = by_key[root_id, "B"]["trace"]
            comparison = by_key[root_id, reference]
            actions = [row.get("native_action") or row["action"] for row in comparison["trace"]]
            if not 1 <= step <= min(len(actions), len(baseline)) or comparison["status"] != "win":
                parser.error(f"Expected a verified winning reference with action at step {step}")
            if [row["action"] for row in baseline[:step - 1]] != actions[:step - 1]:
                parser.error("Baseline and reference prefixes diverged before the intervention")
            if baseline[step - 1]["action"] == actions[step - 1]:
                parser.error("The forced action must differ from B")
            row = measure(output, roots[root_id], "B", (step, actions[step - 1]))
            # Prove that the forced action was reached after the same public parent.
            observed = row["trace"]
            fields = ("round", "player_hp", "energy", "enemies", "hand")
            if (len(observed) < step or not observed[step - 1].get("forced") or
                [r["action"] for r in observed[:step]] != actions[:step] or
                any(observed[step - 1][key] != baseline[step - 1][key] for key in fields)):
                row["status"] = "intervention_mismatch"
            row["intervention"]["reference"] = reference
            results.append(row)
            write(output / "counterfactuals.json", [r for r in results if r["policy"] == "B_cf"])
        return
    if args.stage == "teacher":
        results = [row for row in json.loads((output / "results.json").read_text(encoding="utf-8"))
                   if row["policy"] != "C"]
    else:
        results = []
        for root in manifest["roots"]:
            for policy in ("A", "B"):
                results.append(measure(output, root, policy))
                write(output / "results.json", results)
            if root["context"]["room_type"] == "Boss" and "archived_suffix" in root:
                results.append(measure(output, root, "archive", root["archived_suffix"]))
                write(output / "results.json", results)
    # Cover both ascensions, preferring native deaths to unsupported roots.
    ordinary = [root for root in manifest["roots"] if root["context"]["room_type"] == "Monster"]
    b = {row["id"]: row for row in results if row["policy"] == "B"}
    failures = sorted((root for root in ordinary if b[root["id"]]["status"] != "win"),
                      key=lambda root: b[root["id"]]["status"] != "death")
    controls = [root for root in ordinary if b[root["id"]]["status"] == "win"]
    targets = []
    for difficulty in (0, 10):
        targets.extend([root for root in failures if root["ascension"] == difficulty][:2])
    for root in targets + controls[:1]:
        results.append(measure(output, root, "C"))
        write(output / "results.json", results)


if __name__ == "__main__":
    main()
