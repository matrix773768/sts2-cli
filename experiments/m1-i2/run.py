"""Run one bounded Ironclad A0 experiment with hidden RNG (offline-teacher)."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import random
import sys
from time import monotonic, perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / directory) for directory in ("experiments/m1-i1", "python", "tests")]
from build import BUILD, SOLVER
from branch_memory import _reader
import engine_client
from room_policy import combat_action
from run_route_smoke import choose_action, UnsupportedDecision

STEP_LIMIT = 480
COMBAT_LIMIT = 80
RUN_SECONDS = 120
RSS_LIMIT = 512 * 1024**2
NATIVE_HASH = "62ecbe91093e1fa862de4329aac865209dcb297804caf0f0520d92d8c0b4a9c3"
SOLVER_HASH = "d286a18c7c0a06769aa636ec00cac53f3fb71de749028858c1e1a7062282ab13"


class StopRun(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status


class OfflineTeacherRun:
    def __init__(self, seed, output, verify=False, verify_potion=False):
        self.output = output
        self.verify_rejection = verify
        self.verify_potion = verify_potion
        self.rng = random.Random(seed)
        self.deadline = monotonic() + RUN_SECONDS
        self.read_memory = _reader()
        self.report = {
            "schema_version": 1, "mode": "offline-teacher", "uses_hidden_rng": True,
            "seed": seed, "character": "Ironclad", "ascension": 0,
            "game": "0.113.1/26660232", "game_sha256": NATIVE_HASH,
            "solver": "0.51.5/78e4545e825e58c3d999354b1ffcd54241b1d2cf", "solver_sha256": SOLVER_HASH,
            "budget": {
                "nodes": 1000, "beam": 24, "dop": 1, "card_branches": 32,
                "pile_branches": 18, "hand_branches": 24, "search_soft_ms": 6000,
                "cancel_ms": 8000, "command_seconds": 12, "plan_actions": 48,
                "combat_actions": COMBAT_LIMIT, "run_actions": STEP_LIMIT,
                "run_seconds": RUN_SECONDS, "heap_mib": 256, "rss_watermark_mib": 512,
            },
            "combats": [], "steps": 0, "peak_working_set_bytes": 0,
        }
        self.current = None
        self.engine = None
        self.last_request_ms = 0

    def request(self, cmd, **args):
        if cmd in ("action", "i1_step"):
            if self.report["steps"] >= STEP_LIMIT:
                raise StopRun("action_limit", "Run action limit reached")
            self.report["steps"] += 1
        start = perf_counter()
        result = self.engine.send({"cmd": cmd, **args})
        self.last_request_ms = (perf_counter() - start) * 1000
        memory = self.read_memory(self.engine.proc) if self.read_memory else None
        if memory:
            self.report["peak_working_set_bytes"] = max(self.report["peak_working_set_bytes"], memory[1])
            if memory[1] > RSS_LIMIT:
                raise StopRun("memory_limit", "Working set high-water mark exceeded")
        if result.get("type") == "error":
            self.engine_error(result)
        return result

    @staticmethod
    def engine_error(response):
        status = "engine_timeout" if response.get("error_code") == "combat_turn_timeout" else "engine_error"
        raise StopRun(status, response.get("message"))

    def execute_action(self, command):
        return self.request("action", action=command["action"], args=command.get("args", {}))

    @staticmethod
    def verify(combat, step, expected, actual):
        if expected != actual:
            combat["first_difference"] = {"step": step, "expected": expected, "actual": actual}
            combat["differential"] = "mismatch"
            raise StopRun("prediction_mismatch", f"First native difference at {step}")

    def teacher(self, state, combat):
        begin = self.request("i1_begin")
        combat["capture_native_wall_ms"] = self.last_request_ms
        plan = self.request("i1_capture")
        combat["solve_wall_ms"] = self.last_request_ms
        combat["plan"] = {k: v for k, v in plan.items() if k not in ("root", "frames")}
        self.verify(combat, "source_unchanged", begin["state"], self.request("i1_state")["state"])
        status = plan["status"]
        if status in ("budget_exhausted", "no_complete_win", "unsupported"):
            self.request("i1_release")
            combat["fallback_reason"] = status
            return state
        if status != "complete_win":
            raise StopRun("protocol_error", f"Unknown plan status: {status}")
        self.verify(combat, "root", plan["root"], begin["state"])
        if not 1 <= len(plan["actions"]) == len(plan["frames"]) <= 48:
            raise StopRun("protocol_error", "Incomplete route frames")
        if self.verify_rejection:
            self.verify_rejection = False
            rejected = self.request("i1_step", action={**plan["actions"][0], "turn": -1})
            if rejected.get("type") != "i1_rejected":
                raise StopRun("protocol_error", "Invalid turn was not rejected")
            self.verify(combat, "rejected_action", begin["state"], self.request("i1_state")["state"])
            self.report["invalid_turn_rejected_without_mutation"] = True
        previous = begin["state"]
        for index, (action, expected) in enumerate(zip(plan["actions"], plan["frames"]), 1):
            if self.verify_potion and action["kind"] == "UsePotion":
                self.verify_potion = False
                for field, value, reason in (
                    ("potion_slot", -1, "Invalid potion slot or ID"),
                    ("target_combat_id", 2**32 - 1, "Invalid potion target"),
                ):
                    rejected = self.request("i1_step", action={**action, field: value})
                    if rejected.get("type") != "i1_rejected" or rejected.get("reason") != reason:
                        raise StopRun("protocol_error", f"Invalid potion {field} was not rejected")
                    self.verify(combat, field, previous, self.request("i1_state")["state"])
                combat["invalid_potion_rejected_without_mutation"] = True
            entry = {"plan_action": action, "accepted": None}
            combat["executed"].append(entry)
            step = self.request("i1_step", action=action)
            entry["wall_ms"] = self.last_request_ms
            if step["type"] == "i1_rejected":
                entry["accepted"] = False
                raise StopRun("plan_action_rejected", step["reason"])
            decision = step["decision"]
            if decision.get("type") == "error":
                self.engine_error(decision)
            entry.update(accepted=True, native_ms=step["native_ms"],
                         native_action=step["native_action"], decision=decision["decision"])
            if decision["decision"] == "game_over" and decision.get("victory") is False:
                combat["differential"] = "unexpected_defeat"
                combat["first_difference"] = {"step": index, "expected": expected, "actual": step["state"]}
                self.request("i1_release")
                return decision
            self.verify(combat, index, expected, step["state"])
            combat["matched_actions"] += 1
            if action["kind"] == "UsePotion":
                evidence = ("player_potions", "all_enemy_powers", "enemy_hps_by_model",
                            "player_hp", "player_ordered_piles", "rng_counters")
                entry["potion_evidence"] = {
                    "before": {key: previous[0][key] for key in evidence},
                    "after": {key: step["state"][0][key] for key in evidence},
                }
            previous = step["state"]
            last = index == len(plan["actions"])
            valid_decisions = ("card_reward", "map_select", "game_over") if last else ("combat_play",)
            if step["terminal"] != last or decision["decision"] not in valid_decisions:
                combat["differential"] = "mismatch"
                combat["first_difference"] = {"step": index, "terminal_expected": last,
                                              "terminal_actual": step["terminal"], "decision": decision}
                raise StopRun("prediction_mismatch", "Native combat boundary differs")
        combat["lock_hp"] = step["state"][0]["player_hp"]
        combat["differential"] = "pass"
        self.request("i1_release")
        return decision

    def open_battle(self, state, entry_ms):
        combat = {
            "public_root": state, "entry_wall_ms": entry_ms, "fallback_reason": None,
            "executed": [], "matched_actions": 0, "differential": "not_run",
        }
        self.report["combats"].append(combat)
        self.current = combat
        if state["context"]["room_type"] != "Monster" or state["round"] != 1:
            combat["fallback_reason"] = "outside_supported_boundary"
            return state
        combat["search_sample"] = "cross_combat" if any(
            "plan" in previous for previous in self.report["combats"][:-1]) else "first_search"
        return self.teacher(state, combat)

    def play(self):
        start = perf_counter()
        self.engine = engine_client.EngineClient(deadline=self.deadline, log_root=self.output,
                                                 command_timeout=12)
        self.report["startup_ms"] = (perf_counter() - start) * 1000
        self.report["engine_log_dir"] = str(self.engine.log_dir)
        self.report["coreclr"] = self.engine.runtime_version
        state = self.request("start_run", seed=self.report["seed"], character="Ironclad",
                             ascension=0, lang="en")
        self.report["start_run_ms"] = self.last_request_ms
        self.report["initial_decision"] = state["decision"]
        while True:
            decision = state["decision"]
            if decision == "combat_play" and self.current is None:
                state = self.open_battle(state, self.last_request_ms)
                decision = state["decision"]
            combat = self.current
            if combat is not None and decision in ("card_reward", "map_select", "game_over"):
                combat.setdefault("outcome", "defeat" if decision == "game_over" and
                                  state.get("victory") is False else "victory")
                combat.setdefault("result_player", state["player"])
                combat.setdefault("settlement_boundary", decision)
                if decision in ("map_select", "game_over"):
                    combat["settled_player"] = state["player"]
                    before = combat["public_root"]["player"]
                    after = state["player"]
                    combat["resource_change"] = {
                        "net_hp_at_combat_end": combat["result_player"]["hp"] - before["hp"],
                        "net_hp_after_rewards": after["hp"] - before["hp"],
                        "net_hp_at_victory_lock": combat["lock_hp"] - before["hp"] if "lock_hp" in combat else None,
                        "gold": after["gold"] - before["gold"],
                        "max_hp": after["max_hp"] - before["max_hp"],
                        **{key: {"before": before[key], "after": after[key]}
                           for key in ("deck", "potions", "relics") if before[key] != after[key]},
                    }
                    self.current = None
            if decision == "game_over":
                if state.get("victory") is True:
                    return "victory"
                if state.get("victory") is False and state["player"]["hp"] <= 0:
                    return "defeat"
                raise StopRun("protocol_error", "Invalid native game_over")
            if decision == "combat_play":
                command = combat_action(state)
            elif decision == "treasure":
                command = {"action": "proceed"}
            else:
                command, _ = choose_action(state, self.rng)
            combat = self.current
            entry = None
            if combat is not None:
                if len(combat["executed"]) >= COMBAT_LIMIT:
                    raise StopRun("combat_action_limit", "Combat and settlement action limit reached")
                entry = {"native_action": command, "phase": "settlement" if "outcome" in combat else "fallback",
                         "accepted": None}
                combat["executed"].append(entry)
            state = self.execute_action(command)
            if entry is not None:
                entry.update(accepted=True, wall_ms=self.last_request_ms, decision=state["decision"])
            self.report["last_decision"] = state["decision"]
            self.report["last_context"] = state.get("context")

    def run(self):
        start = perf_counter()
        try:
            self.report["status"] = self.play()
        except StopRun as error:
            self.report.update(status=error.status, detail=str(error))
        except UnsupportedDecision as error:
            self.report.update(status="unsupported_decision", detail=str(error))
        except TimeoutError as error:
            self.report.update(status="run_timeout" if monotonic() >= self.deadline else "engine_timeout",
                               detail=str(error))
        except (RuntimeError, OSError, KeyError, ValueError) as error:
            self.report.update(status="engine_or_protocol_error", detail=str(error))
        finally:
            if self.engine is not None:
                self.engine.close(graceful=self.report.get("status") in ("victory", "defeat"))
            self.report["elapsed_ms"] = (perf_counter() - start) * 1000
            self.report["exit_code"] = self.engine.proc.returncode if self.engine else None
            (self.output / "report.json").write_text(json.dumps(self.report, indent=2), encoding="utf-8")
        return self.report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", default="run_1")
    parser.add_argument("--out", type=Path, default=ROOT / "logs/m1-i2")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--verify-potion", action="store_true")
    args = parser.parse_args()
    for path, expected in ((ROOT / "lib/sts2.dll", NATIVE_HASH), (SOLVER, SOLVER_HASH)):
        if sha256(path.read_bytes()).hexdigest() != expected:
            parser.error(f"Unexpected pinned binary: {path}")
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(I1_SOLVER=str(SOLVER), I1_LOG=str(output), DOTNET_GCHeapHardLimit="10000000")
    os.environ.setdefault("I1_RITSU", str(Path.home() / "Desktop/STEAM/steamapps/workshop/content/2868840/3747602295"))
    os.environ.setdefault("STS2_DOTNET", str(ROOT / "logs/m1-review-dotnet/dotnet.exe"))
    os.environ.setdefault("STS2_DOTNET_VERSION", "9.0.7")
    native = engine_client.headless_command()
    dll = BUILD / "Headless/bin/Debug/net9.0/OfflineSearchHarness.dll"
    engine_client.headless_command = lambda: [*native[:-1], str(dll)]
    result = OfflineTeacherRun(args.seed, output, verify=args.verify, verify_potion=args.verify_potion).run()
    verified = [c for c in result["combats"] if c["differential"] == "pass"
                and c.get("outcome") == "victory" and "settled_player" in c]
    print(f"{result['status']}: {len(result['combats'])} combats, {len(verified)} verified teacher wins. {output}")
    terminal = result["status"] in ("victory", "defeat") and result["exit_code"] == 0
    verification_passed = len(verified) >= 2 and result.get("invalid_turn_rejected_without_mutation")
    potion_verified = any(
        c.get("invalid_potion_rejected_without_mutation") and
        any("potion_evidence" in step for step in c["executed"][:-1]
            if step.get("decision") == "combat_play")
        for c in verified
    )
    return 0 if (terminal and (not args.verify or verification_passed)
                 and (not args.verify_potion or potion_verified)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
