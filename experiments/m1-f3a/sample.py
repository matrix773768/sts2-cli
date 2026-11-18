"""Collect bounded Act 2 candidates from the versioned legal run_1 route."""
import argparse
import importlib.util
import json
from pathlib import Path
import random

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("f2_benchmark", HERE.parent / "m1-f2/benchmark.py")
f2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f2)
f1 = f2.f1

BRANCHES = (("offering-west", True, "west"), ("offering-east", True, "east"),
            ("skip-middle", False, "middle"))
PER_BRANCH = 4
MAP_ACTION_LIMIT = 55


def setup(output, name="m1-f3a-build"):
    f1.DLL = f1.ROOT / f"logs/{name}/Headless/bin/Debug/net9.0/OfflineSearchHarness.dll"
    f1.setup(output)


def branch(output, label, take, direction, seen):
    roots = []
    record = dict(branch=label, boss_reward="Offering" if take else "skip", direction=direction,
                  commands=[], encounters=[], status="route_limit")
    rng = random.Random("run_1-act2")

    def send(game, command):
        record["commands"].append(command)
        return game.request(**command) if "cmd" in command else game.execute_action(command)

    try:
        with f2.Session(output, seconds=65) as game:
            for line in f1.BOSS_ROUTE.read_text(encoding="utf-8").splitlines():
                state = game.request(**json.loads(line))
            if state["decision"] != "card_reward" or state["context"]["room_type"] != "Boss":
                raise ValueError("Historical route did not reach first Boss reward")
            record["boss_reward_hp"] = state["player"]["hp"]
            offering = next(card for card in state["cards"] if card["id"] == "CARD.OFFERING")
            reward = dict(action="select_card_reward", args=dict(card_index=offering["index"])) if take else dict(action="skip_card_reward")
            state = send(game, reward)
            if state["decision"] != "map_select" or state["context"]["act"] != 2:
                raise ValueError("Boss reward did not lead to Act 2")
            encounter_count = 0
            turn_step = 0
            for index in range(MAP_ACTION_LIMIT + PER_BRANCH * 140):
                decision = state["decision"]
                if decision == "game_over":
                    record["status"] = "death"
                    break
                if state["context"]["act"] != 2:
                    record["status"] = "left_act_2"
                    break
                if decision == "combat_play":
                    turn_step += 1
                    step = game.request("f1_step", step=turn_step)
                    record["commands"].append(step["action"])
                    if step.get("choice_failure"):
                        record.update(status="unsupported", detail=step["choice_failure"])
                        break
                    state = step["decision"]
                    if state.get("type") == "error":
                        game.engine_error(state)
                    if turn_step >= 140:
                        record["status"] = "combat_action_limit"
                        break
                elif decision == "map_select":
                    record["map_actions"] = record.get("map_actions", 0) + 1
                    if record["map_actions"] > MAP_ACTION_LIMIT:
                        break
                    nodes = sorted(state["choices"], key=lambda x: x["col"])
                    node = nodes[0 if direction == "west" else -1 if direction == "east" else len(nodes) // 2]
                    command = dict(action="select_map_node", args=dict(col=node["col"], row=node["row"]))
                    path = output / f"{label}-{index:03}.save.json"
                    saved = game.request("write_continue_save", path=str(path))
                    if not saved.get("success") or saved.get("room_type") != "MapRoom":
                        raise ValueError("Checkpoint outside native map")
                    state = send(game, command)
                    if state["decision"] != "combat_play":
                        continue
                    turn_step = 0
                    identity = game.request("f1_begin")
                    encounter_count += 1
                    earlier = seen.get(identity["live"])
                    rid = earlier or f"run1-{label}-a2f{state['context']['floor']:02}"
                    record["encounters"].append(dict(id=rid, duplicate=earlier is not None))
                    if earlier is None:
                        seen[identity["live"]] = rid
                        roots.append(dict(id=rid, branch=label, source_group="boss_reward_run_1",
                                          character="Ironclad", ascension=0, seed="run_1",
                                          context=state["context"], identity=identity, public_root=state,
                                          checkpoint=path.name, checkpoint_sha256=f1.digest(path.read_bytes()),
                                          entry=command, entry_command_index=len(record["commands"])))
                    if encounter_count == PER_BRANCH:
                        record["status"] = "sample_cap"
                        break
                else:
                    command = dict(action="proceed") if decision == "treasure" else f1.choose_action(state, rng)[0]
                    state = send(game, command)
    except (f1.i2.StopRun, f1.UnsupportedDecision, TimeoutError, RuntimeError, ValueError) as error:
        record.update(status=f1.classify(error), detail=str(error))
    print(label, record["status"], len(roots), flush=True)
    return record, roots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--f2-host", action="store_true", help="Use the previously built F2 host for sampling")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True)
    setup(out, "m1-f2-build" if args.f2_host else "m1-f3a-build")
    seen, routes, roots = {}, [], []
    for label, take, direction in BRANCHES:
        route, found = branch(out, label, take, direction, seen)
        roots.extend(found)
        routes.append(route)
        f1.write(out / "manifest.json", dict(schema=1, source="tests/boss_reward_run_1.jsonl",
                 source_sha256=f1.digest(f1.BOSS_ROUTE.read_bytes()), game_sha256=f1.i2.NATIVE_HASH,
                 solver_sha256=f1.i2.SOLVER_HASH, routes=routes, roots=roots))


if __name__ == "__main__":
    main()
