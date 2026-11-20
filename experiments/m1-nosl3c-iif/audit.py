"""IIF auditor, reusing IID replay and IIE terminal resource validation."""
from pathlib import Path
import sys
from types import FunctionType

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iie"))
import terminal_contract as iie
from equivalence import VERSION, qualifies

targets = iie.targets
frozen_menu = targets.compare_menu


def compare_menu(obs, native, indices):
    hand = [card | {"legal_target_indices": []}
            if not card["can_play"] and card.get("legal_target_indices") is not None else card
            for card in native.get("hand", [])]
    frozen_menu(obs, native | {"hand": hand}, indices)


def certify(output, versions, spec, row, mode="diagnostic", worker=None):
    if mode not in ("exact", "semantic", "diagnostic"):
        raise ValueError("Unknown certification mode")
    frames = []
    diff = {}
    native = None
    final_action = None

    class Recorder:
        def __init__(self, game):
            object.__setattr__(self, "game", game)

        def __getattr__(self, name):
            return getattr(self.game, name)

        def __setattr__(self, name, value):
            setattr(self.game, name, value)

        def request(self, command, *args, **kwargs):
            nonlocal native, final_action
            reply = self.game.request(command, *args, **kwargs)
            if command == "i1_n2_step":
                episode = reply.get("episode", {})
                pos = kwargs.get("position")
                final_action = (episode.get("status") == "death" and pos == len(row["transitions"]) - 1
                                and row["transitions"][pos]["action"]["kind"] == "end_turn")
            if command == "i1_iib_native_stamp":
                native = self.game
                frames.append(reply["state"][0]["exact_continuation_state"])
            return reply

    def field_diff(predicted, raw):
        diff.update(predicted=predicted, native=raw)
        return targets.field_diff(predicted, raw)

    def open_worker(*args):
        return Recorder((worker or targets.open_worker)(*args))

    # IID owns its ExitStack. Probe the closure before IID releases the process,
    # using the first mismatch callback and the immutable native death stamp.
    def checked_diff(predicted, raw):
        result = field_diff(predicted, raw)
        if final_action and result and set(result) <= {"Y", "AttackStarts"} and native is not None and mode != "exact":
            end = native.request("action", action="end_turn", args={})
            frame = native.request("i1_iib_native_stamp")
            diff["closed"] = (end.get("decision") == "game_over" and end.get("victory") is False
                              and frame["state"][0]["exact_continuation_state"] == raw)
        return result

    original = targets.certify
    replay = FunctionType(original.__code__, original.__globals__ | dict(
        field_diff=checked_diff, compare_menu=compare_menu, open_worker=open_worker))
    record = iie.certify(output, versions, spec, row, replay)
    raw_status = record["status"]
    allowed = (mode != "exact" and len(frames) >= 2 and "predicted" in diff and
               qualifies(record, row["feedback"], frames[-2], diff["predicted"], diff["native"], diff.get("closed")))
    if record["terminal_verified"]:
        classification = "exact_native_match"
    elif allowed:
        classification = "semantic_native_match"
    elif record.get("reason") in ("menu_or_action_difference", "locked_resources") or (
            set(record.get("continuation_fields", ())) & {"hp", "block", "energy", "stars", "P", "R", "H", "D", "C", "X"}):
        classification = "semantic_mismatch"
    else:
        classification = "semantic_unverified"
    if allowed:
        record["equivalence_proof"] = dict(rule=VERSION, native_no_progress=True, previous=frames[-2],
                                           predicted=diff["predicted"], native=diff["native"])
        if mode == "semantic":
            record.update(status="admissible_death", terminal_verified=True)
    return record | dict(certification=classification, mode=mode, exact_status=raw_status,
                         rule=VERSION if allowed else None, equivalence_version=VERSION)
