"""Strict enemy-side battle admission over the frozen exact auditor."""
from pathlib import Path
import sys
from types import FunctionType

HERE = Path(__file__).resolve().parent
for folder in ("m1-nosl3c-iig-completion", "m1-nosl3c-iih"):
    sys.path.insert(0, str(HERE.parent / folder))
import completion_engine as completion
from build_reward_host import HOST

RULE = "sts2.nosl.iih3.enemy-side-exact-combat.v1"
REASON = "E3_ENEMY_SIDE_TERMINAL"
SOLVER = "d15ba0e66d2bf54dd1d00714c39f7b8ecc26b9a5b35b79ceb64277d4fd4a54dd"
GAME = "62ecbe91093e1fa862de4329aac865209dcb297804caf0f0520d92d8c0b4a9c3"


def bind(output, solver):
    original = completion.targets.bind
    return FunctionType(original.__code__, original.__globals__ | {"HOST": HOST})(output, solver)


def candidate(row):
    feedback = row["feedback"]
    steps = row["transitions"]
    return bool(steps and not feedback["eligible"] and feedback["status"] == "rule_risk"
                and feedback["reason"] == REASON and feedback["actions"] == len(steps)
                and feedback["observation"] and steps[-1]["action"]["kind"] == "end_turn")


def certify(output, versions, spec, row, mode="exact"):
    if not candidate(row):
        return completion.certify(output, versions, spec, row, mode)
    rejected = dict(status="rule_risk", certification="semantic_unverified",
                    terminal_verified=False, mode=mode, rule=RULE)
    if mode not in ("exact", "semantic", "diagnostic"):
        raise ValueError("Unknown certification mode")
    if (versions.get("solver_sha256"), versions.get("game_sha256"), versions.get("coreclr")) != (
            SOLVER, GAME, "9.0.7"):
        return rejected | dict(reason="e3_unattested_build")

    collected = row["feedback"].copy()
    derived = collected | dict(status="predicted_win", reason=None, eligible=True)
    replay = row | {"feedback": derived}
    predicted = None
    decision = None
    closure = None

    class Worker:
        def __init__(self, game):
            object.__setattr__(self, "game", game)

        def __getattr__(self, name):
            return getattr(self.game, name)

        def __setattr__(self, name, value):
            setattr(self.game, name, value)

        def request(self, command, *args, **kwargs):
            nonlocal predicted, decision, closure
            reply = self.game.request(command, *args, **kwargs)
            if command == "i1_n2_step":
                predicted = reply["episode"]
                waiting = (predicted.get("observation") or {}).get("decision", {}).get("phase") == "choice"
                if not waiting and not predicted.get("audit_stamp"):
                    raise ValueError("Missing stable E3 prediction stamp")
            if command == "action":
                decision = reply
            if command == "i1_iib_native_stamp" and reply["terminal"] and closure is None:
                before = self.game.request("i1_iih_reward_snapshot")
                repeat = self.game.request("action", action="end_turn", args={})
                after = self.game.request("i1_iih_reward_snapshot")
                keys = ("player", "run_rng", "player_rng", "room", "visited_map_nodes")
                closure = bool(decision and decision.get("decision") == "card_reward"
                               and repeat == decision and all(before[k] == after[k] for k in keys))
            return reply

    def open_worker(*args):
        return Worker(completion.targets.open_worker(*args))

    proof = completion.iig.audit.certify(output, versions, spec, replay, mode="exact", worker=open_worker)
    if not (proof["terminal_verified"] and closure and predicted
            and predicted["status"] == "predicted_win"
            and predicted["result"]["boundary"] == "None"
            and predicted["actions"] == collected["actions"]):
        return proof | rejected | dict(reason=proof.get("reason") or "e3_native_closure_unverified")
    if "hp_accounting" in replay:
        row["hp_accounting"] = replay["hp_accounting"]
    row["collected_feedback"] = collected
    row["feedback"] = derived
    return proof | dict(mode=mode, rule=RULE, solver_terminal_status=predicted["status"],
                        native_no_progress=True, contract="strict_combat")
