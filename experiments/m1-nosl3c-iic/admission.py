"""Strict route certification for v3 trajectories, separate from policy inference."""
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iib"))
from engine import BANK, CAPTURE, open_worker
from interactive_contract import OBSERVATION, MODEL
from qualify_native import compare_menu, native_action
from nosl_experience import digest

VERSION = "sts2.nosl.admission.exact-route.v1"


def route_key(versions, spec, row):
    return digest([VERSION, versions, OBSERVATION, MODEL, spec,
                   [(t["observation"], t["action"]) for t in row["transitions"]]])


def certify(output, versions, spec, row):
    """Compare the observed route against two cold reconstructions.

    The predicted reconstruction must reproduce the sampled public history.
    Native hashes are inspected here, after the actor has completed the route.
    """
    feedback = row["feedback"]
    record = dict(schema=VERSION, root=digest(spec), route=route_key(versions, spec, row),
                  versions=versions, observation=OBSERVATION, model=MODEL, status=feedback["status"],
                  boundaries=0, terminal_verified=False, path=[])
    def surface(transition):
        obs, action = transition["observation"], transition["action"]
        played = obs["hand"][action["card"]]["id"] if action["card"] is not None else None
        return dict(kind=action["kind"], card=played, target=action["target"],
                    effect=obs["decision"].get("effect"))

    if feedback["status"] not in ("predicted_win", "death"):
        return record | dict(reason=feedback.get("reason"), path=[surface(t) for t in row["transitions"]])

    from interactive_contract import project

    with ExitStack() as stack:
        pred, native = [open_worker(output, stack, versions) for _ in range(2)]
        first, _ = CAPTURE(pred, spec)
        second, _ = CAPTURE(native, spec)
        record["root_state_sha256"] = digest(first["native"])
        if first["native"] != second["native"]:
            return record | dict(status="native_difference", reason="root_reconstruction")
        native.teacher_frames, native.teacher_choices = [], []
        native.request("i1_begin")
        state = pred.request("i1_n2_reset", arm="A", cap=len(row["transitions"]),
                             potions=False, rejected=[])["episode"]
        live = second["public_root"]
        selected = []
        previous = None
        frame = None
        for index, transition in enumerate(row["transitions"]):
            obs, action = transition["observation"], transition["action"]
            kind = action["kind"]
            record["path"].append(surface(transition))
            before = live
            try:
                if state["status"] != "active" or project(state["observation"]) != obs:
                    raise ValueError("Prediction did not reproduce the sampled decision")
                compare_menu(obs, live)
                if kind == "play_card":
                    args = dict(card_index=action["card"])
                    if action["target"] is not None:
                        args["target_index"] = action["target"]
                    live = native_action(native, kind, **args)
                elif kind == "select_candidate":
                    selected.append(action["choice"])
                elif kind == "confirm_selection":
                    live = native_action(native, "select_cards", indices=",".join(map(str, selected)))
                    selected.clear()
                elif kind == "end_turn":
                    live = native_action(native, kind)
                else:
                    raise ValueError("Unknown sampled action")
                state = pred.request("i1_n2_step", position=index, index=action["index"])["episode"]
                if state.get("audit_stamp"):
                    frame = native.request("i1_iib_native_stamp")
                    locked = frame["state"][0]
                    native_stamp = sha256(locked["exact_continuation_state"].encode()).hexdigest()
                    if native_stamp != state["audit_stamp"]:
                        reason = ("enemy_stage_death_boundary" if kind == "end_turn" and
                                  state["status"] == "death" and live["decision"] == "game_over"
                                  else "continuation_difference")
                        return record | dict(status="native_difference", reason=reason, position=index,
                            previous=previous, public_prediction_before=obs, native_before=before,
                            native_after=live, native_frame=frame, prediction=state)
                    record["boundaries"] += 1
                    previous = dict(position=index, stamp=native_stamp)
            except (AssertionError, ValueError) as error:
                return record | dict(status="native_difference", reason="menu_or_action_difference",
                                     position=index, detail=str(error), public_prediction_before=obs,
                                     native_before=before, native_after=live, prediction=state)
        if (state["status"] != feedback["status"] or state["terminal_observation"] != feedback["observation"]
                or not state.get("audit_stamp") or not frame or not frame["terminal"]):
            return record | dict(status="native_difference", reason="terminal_not_locked",
                                 prediction=state, native_after=live)
        final = state["terminal_observation"]
        expected = (final["hp"], final["max_hp"], state["result"]["gold"],
                    ",".join(p or "-" for p in final["potions"]))
        actual = tuple(locked[k] for k in ("player_hp", "player_max_hp", "player_gold", "player_potions"))
        if expected != actual:
            return record | dict(status="native_difference", reason="locked_resources", expected=expected, actual=actual)
        return record | dict(status="admissible_" + feedback["status"], terminal_verified=True,
                             native_terminal_stamp=previous["stamp"])


def admitted(row, evidence):
    return (row["feedback"]["eligible"] and evidence["terminal_verified"] and
            evidence["status"] == "admissible_" + row["feedback"]["status"])
