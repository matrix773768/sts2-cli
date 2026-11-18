"""Bounded real-route smoke runs using the isolated engine test transport."""

import argparse
from collections import Counter
import json
from pathlib import Path
import random
from statistics import median
import time

ROOT = Path(__file__).resolve().parents[1]


MAX_ACTIONS = 1200
RUN_SECONDS = 180


class UnsupportedDecision(Exception):
    """The engine returned a decision this policy cannot safely handle."""


def action(name, **args):
    return {"cmd": "action", "action": name, "args": args}


def choose_action(state, rng):
    decision = state["decision"]
    if decision == "map_select" and state["choices"]:
        node = rng.choice(state["choices"])
        return action("select_map_node", col=node["col"], row=node["row"]), node
    if decision == "combat_play":
        live = [enemy for enemy in state["enemies"] if enemy["hp"] > 0]
        for card in state["hand"]:
            if not card["can_play"] or card["cost"] > state["energy"]:
                continue
            args = {"card_index": card["index"]}
            target_type = card["target_type"]
            if target_type == "AnyEnemy":
                if not live:
                    continue
                args["target_index"] = min(live, key=lambda e: (e["hp"], e["index"]))["index"]
            elif target_type not in ("Self", "None", "AllEnemies", "RandomEnemy", "TargetedNoCreature"):
                continue
            return action("play_card", **args), None
        return action("end_turn"), None
    if decision in ("event_choice", "rest_site"):
        options = [option for option in state["options"]
                   if not option.get("is_locked") and option.get("is_enabled", True)]
        if options:
            choice = next((o for o in options if o.get("option_id") == "HEAL"), options[0])
            return action("choose_option", option_index=choice["index"]), None
    if decision == "card_reward":
        if state["cards"]:
            return action("select_card_reward", card_index=state["cards"][0]["index"]), None
        if state.get("can_skip"):
            return action("skip_card_reward"), None
    if decision == "bundle_select" and state["bundles"]:
        return action("select_bundle", bundle_index=state["bundles"][0]["index"]), None
    if decision == "card_select":
        minimum, maximum = state["min_select"], state["max_select"]
        if 0 <= minimum <= maximum and minimum <= len(state["cards"]):
            if minimum == 0:
                return action("skip_select"), None
            return action("select_cards", indices=",".join(
                str(card["index"]) for card in state["cards"][:minimum]
            )), None
    if decision == "shop":
        return action("leave_room"), None
    raise UnsupportedDecision(f"No legal action implemented for {decision!r}")


class Run:
    def __init__(self, seed):
        self.seed = seed
        self.started = time.perf_counter()
        self.deadline = time.monotonic() + RUN_SECONDS
        self.game = None
        self.startup = None
        self.actions = Counter()
        self.rooms = []
        self.combats = []
        self.furthest = (0, 0)
        self.timings = []
        self.command = None
        self.response = None
        self.pending_node = None
        self.previous = None
        self.repeats = 0

    def send(self, command):
        self.command, self.response = command, None
        start = time.perf_counter()
        if command["cmd"] == "action":
            self.actions[command["action"]] += 1
        try:
            self.response = self.game.send(command)
            return self.response
        finally:
            duration = time.perf_counter() - start
            self.timings.append(duration)
            with (self.game.log_dir / "timings.jsonl").open("a", encoding="utf-8") as log:
                json.dump({"seconds": duration, "command": command,
                           "response": self.response}, log, ensure_ascii=False)
                log.write("\n")

    def observe(self, state):
        context = state.get("context", {})
        progress = (context.get("act", 0), context.get("floor", 0))
        self.furthest = max(self.furthest, progress)
        if state["decision"] == "combat_play":
            room_key = (*progress, context.get("room_type"))
            if not self.combats or self.combats[-1]["key"] != room_key:
                self.combats.append({"key": room_key, "rounds": 0})
            combat = self.combats[-1]
            combat["rounds"] = max(combat["rounds"], state["round"])

    def play(self):
        from conftest import Game

        self.game = Game(deadline=self.deadline)
        self.startup = time.perf_counter() - self.started
        rng = random.Random(self.seed)
        command = {"cmd": "start_run", "character": "Ironclad", "seed": self.seed,
                   "ascension": 0, "lang": "en"}
        while time.monotonic() < self.deadline:
            state = self.send(command)
            if not isinstance(state, dict):
                return "protocol_error", "Expected a JSON object"
            if state.get("type") == "error":
                kind = "engine_timeout" if state.get("error_code") == "combat_turn_timeout" else "engine_error"
                return kind, state.get("message")
            if state.get("type") != "decision" or state.get("decision") in (None, "unknown"):
                return "protocol_error", "Missing or unknown decision"
            self.observe(state)
            if self.pending_node is not None:
                node = self.pending_node
                # Query the map even when the engine handles a room within the entry command.
                world = self.send({"cmd": "get_map"})
                expected = {key: node[key] for key in ("col", "row")}
                if isinstance(world, dict) and world.get("type") == "error":
                    return "engine_error", world.get("message")
                if (not isinstance(world, dict) or world.get("type") != "map"
                        or world.get("current_coord") != expected):
                    return "protocol_error", f"Map entry was not confirmed for {node!r}"
                context = state["context"]
                room_type = context.get("room_type")
                if room_type == "Map" and node["type"] != "Unknown":
                    room_type = node["type"]
                self.rooms.append({"act": context["act"], "floor": context["floor"],
                                   **expected, "node_type": node["type"], "room_type": room_type})
                self.pending_node = None
                self.command, self.response = command, state
            elif command["cmd"] == "start_run" and state["decision"] == "event_choice":
                self.rooms.append({"act": state["context"]["act"], "floor": state["context"]["floor"],
                                   "room_type": "Event", "event": state.get("event_name")})

            if state["decision"] == "game_over":
                victory, hp = state.get("victory"), state.get("player", {}).get("hp")
                if victory is True:
                    return "victory", None
                if victory is False and isinstance(hp, int) and hp <= 0:
                    return "defeat", None
                return "protocol_error", f"Invalid game_over: victory={victory!r}, hp={hp!r}"
            if sum(self.actions.values()) >= MAX_ACTIONS:
                return "action_limit", f"Reached {MAX_ACTIONS} actions"
            next_command, node = choose_action(state, rng)
            current = (next_command, state)
            self.repeats = self.repeats + 1 if current == self.previous else 0
            if self.repeats >= 3:
                return "stalled", "Same command and complete state repeated without progress"
            self.previous = current
            command, self.pending_node = next_command, node
        return "run_timeout", f"Exceeded {RUN_SECONDS}s run deadline"

    def execute(self):
        try:
            status, detail = self.play()
        except UnsupportedDecision as error:
            status, detail = "unsupported_decision", str(error)
        except TimeoutError as error:
            status = "run_timeout" if time.monotonic() >= self.deadline else "command_timeout"
            detail = str(error)
        except (RuntimeError, OSError) as error:
            status = "protocol_error" if "Invalid engine JSON" in str(error) else "transport_error"
            detail = str(error)
        finally:
            if self.game is not None:
                self.game.close()
        ordered = sorted(self.timings)
        terminal = status in ("victory", "defeat")
        return {
            "seed": self.seed, "character": "Ironclad", "ascension": 0, "status": status,
            "native_game_over": terminal, "victory": status == "victory" if terminal else None,
            "act": self.furthest[0], "floor": self.furthest[1], "rooms": self.rooms,
            "room_counts": dict(Counter(room["room_type"] for room in self.rooms)),
            "combats": self.combats, "combat_count": len(self.combats),
            "rounds_reached": sum(combat["rounds"] for combat in self.combats),
            "actions": sum(self.actions.values()), "action_counts": dict(self.actions),
            "startup_seconds": self.startup, "elapsed_seconds": time.perf_counter() - self.started,
            "command_count": len(ordered),
            "command_median_seconds": median(ordered) if ordered else None,
            "command_p95_seconds": ordered[(95 * len(ordered) - 1) // 100] if ordered else None,
            "command_max_seconds": ordered[-1] if ordered else None,
            "last_command": self.command, "last_response": self.response,
            "pending_node": self.pending_node, "detail": detail,
            "log_dir": str(self.game.log_dir) if self.game is not None else None,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seeds", nargs="+")
    args = parser.parse_args()
    output = ROOT / "logs" / "m0-c1"
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for seed in args.seeds:
        result = Run(seed).execute()
        results.append(result)
        print(f"{seed}: {result['status']} act={result['act']} floor={result['floor']} "
              f"actions={result['actions']} detail={result['detail']}", flush=True)
        (output / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False),
                                             encoding="utf-8")
    return 0 if all(result["native_game_over"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
