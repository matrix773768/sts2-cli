"""Target-aware collection and independent differential replay on the II-D host."""
from pathlib import Path
import sys
from types import FunctionType

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iic"))
import admission
from engine import BANK, CAPTURE, bind, open_worker
import interactive_contract as base
import qualify_native
import run_admission
import train_interactive


def project(wire):
    obs = frozen_project(wire)
    obs["allies"] = [base.only(a, ("index", "hp", "block", "attack_hits", "intents", "powers"))
                     for a in wire["allies"]]
    for ally in obs["allies"]:
        ally["powers"] = [base.only(power, ("id", "amount")) for power in ally["powers"]]
    for action, raw in zip(obs["actions"], wire["actions"], strict=True):
        action["target_side"] = raw.get("target_side")
        action["target_type"] = raw.get("target_type")
    return obs


class Decision(base.Decision):
    def __init__(self, obs):
        # Reuse the same entity encoder and tensor dimensions. Public indices
        # remain scoped to their own side; only the tensor references are offset.
        enemies = obs["enemies"]
        offset = len(enemies)
        referenced = {a["target"] for a in obs["actions"] if a["target_side"] == "ally"}
        allies = [entity | {"index": i + offset} for i, entity in enumerate(obs["allies"]) if i in referenced]
        actions = [a | {"target": a["target"] + offset} if a["target_side"] == "ally" else a
                   for a in obs["actions"]]
        super().__init__(obs | {"enemies": [*enemies, *allies], "actions": actions})
        self.actions = obs["actions"]


def compare_menu(obs, native, indices):
    if obs["decision"]["phase"] == "choice":
        qualify_native.compare_menu(obs, native)
        return
    if native["decision"] != "combat_play":
        raise ValueError("Native is not at a playable combat boundary")
    if [c["id"] for c in obs["hand"]] != [c["id"].removeprefix("CARD.") for c in native["hand"]]:
        raise ValueError("Hand instances differ")
    if (obs["hp"], obs["block"], obs["energy"], obs["stars"]) != (
            native["player"]["hp"], native["player"]["block"], native["energy"], native.get("stars") or 0):
        raise ValueError("Public resources differ")
    expected = set()
    for card in native["hand"]:
        slots = card.get("legal_target_indices")
        kind = card["target_type"]
        side = "enemy" if kind == "AnyEnemy" else "ally"
        if slots is not None:
            expected.update((card["index"], indices[side].index(slot), side) for slot in slots)
        elif card["can_play"]:
            expected.add((card["index"], None, None))
    actual = {(a["card"], a["target"], a["target_side"]) for a in obs["actions"] if a["kind"] == "play_card"}
    if expected != actual:
        raise ValueError(("legal_target_menu", sorted(expected - actual, key=str), sorted(actual - expected, key=str)))


def worker_bind(output, solver):
    binding = FunctionType(bind.__code__, bind.__globals__ | {"HOST": "m1-nosl3c-iid-build"})
    return binding(output, solver)


def field_diff(predicted, native):
    import re

    def fields(text):
        return dict(part.split("=", 1) for part in re.split(r";(?=[A-Za-z][A-Za-z0-9_]*=)", text)
                    if "=" in part)

    left, right = fields(predicted), fields(native)
    return {key: {"prediction": left.get(key), "native": right.get(key)}
            for key in dict.fromkeys([*left, *right]) if left.get(key) != right.get(key)}


def certify(output, versions, spec, row):
    latest = {}
    live = None
    indices = {}
    workers = []
    remapped_actions = []

    class DiagnosticWorker:
        def __init__(self, game):
            object.__setattr__(self, "game", game)

        def __getattr__(self, name):
            return getattr(self.game, name)

        def __setattr__(self, name, value):
            setattr(self.game, name, value)

        def request(self, command, *args, **kwargs):
            result = self.game.request(command, *args, **kwargs)
            if command == "i1_n2_step" and result.get("episode", {}).get("audit_stamp"):
                latest["worker"] = self.game
                latest["stamp"] = result["episode"]["audit_stamp"]
            if command == "i1_iib_native_stamp":
                latest["native"] = result
                predicted = latest.get("worker")
                if predicted is not None:
                    frame = result["state"][0]["exact_continuation_state"]
                    from hashlib import sha256
                    if latest["stamp"] != sha256(frame.encode()).hexdigest():
                        text = predicted.request("i1_iid_prediction_text")["text"]
                        latest["difference"] = field_diff(text, frame)
            return result

    def compare(obs, native):
        nonlocal live
        live = native
        if obs["decision"]["phase"] == "combat":
            pred_roster = workers[0].request("i1_iid_prediction_roster")
            native_roster = workers[1].request("i1_iid_native_roster")
            for side in ("enemy", "ally"):
                if (set(pred_roster[side]) != set(native_roster[side]) or
                        len(set(native_roster[side])) != len(native_roster[side])):
                    raise ValueError(f"Different {side} roster identity")
                indices[side] = [native_roster[side].index(entity) for entity in pred_roster[side]]
            for enemy in obs["enemies"]:
                peer = native["enemies"][indices["enemy"][enemy["index"]]]
                if (enemy["hp"], enemy["block"]) != (peer["hp"], peer["block"]):
                    raise ValueError("Target HP or block differs")
        compare_menu(obs, native, indices)

    def action(game, kind, **args):
        if kind == "play_card" and "target_index" in args:
            card = live["hand"][args["card_index"]]
            side = "ally" if card["target_type"] in ("AnyAlly", "AnyPlayer") else "enemy"
            chosen = args.pop("target_index")
            slot = indices[side][chosen]
            if slot != chosen:
                remapped_actions.append(dict(side=side, predicted_slot=chosen, native_slot=slot))
            args["ally_index" if side == "ally" else "target_index"] = slot
        return qualify_native.native_action(game, kind, **args)

    def diagnostic_worker(*args):
        worker = open_worker(*args)
        workers.append(worker)
        return DiagnosticWorker(worker)

    dependencies = admission.certify.__globals__ | dict(
        open_worker=diagnostic_worker, native_action=action, compare_menu=compare)
    # II-C imports the projection at replay time. configure() installs
    # the target-aware projection for this isolated process.
    result = FunctionType(admission.certify.__code__, dependencies)(output, versions, spec, row)
    result["remapped_targets"] = remapped_actions
    for entry, step in zip(result.get("path", []), row["transitions"]):
        entry["target_type"] = step["action"]["target_type"]
    if "difference" in latest:
        result["continuation_fields"] = latest["difference"]
    position = result.get("position")
    if position is not None and position < len(row["transitions"]):
        step = row["transitions"][position]
        obs, action = step["observation"], step["action"]
        result["first_failure"] = dict(position=position, action=action["kind"], target_type=action["target_type"],
            effect=obs["decision"].get("effect"), phase=obs["decision"]["phase"],
            card=obs["hand"][action["card"]]["id"] if action["card"] is not None else None)
    return result


def configure():
    base.project = project
    run_admission.bind = worker_bind
    run_admission.certify = certify
    collector = train_interactive.collect.__wrapped__
    from torch import no_grad
    run_admission.collect = no_grad()(FunctionType(collector.__code__,
                                                  collector.__globals__ | dict(project=project, Decision=Decision)))
    def optimize(policy, adam, rows, config, model_hash):
        update = train_interactive.update
        deps = update.__globals__ | dict(Decision=Decision, MODEL_VERSION=base.MODEL,
                                         checkpoint=train_interactive.checkpoint_policy)
        return FunctionType(update.__code__, deps)(policy, adam, rows, config, model_hash)
    run_admission.optimize = optimize


frozen_project = base.project
