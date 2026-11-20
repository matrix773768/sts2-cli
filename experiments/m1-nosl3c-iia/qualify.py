"""Check a complete scripted public trajectory against an independent native process."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import runpy

import torch

HERE = Path(__file__).resolve().parent
HOST = "m1-nosl3c-iia-build"

BINDING = runpy.run_path(str(HERE.parent / "m1-s3a/produce.py"))
from contract import Decision, Policy, MODEL_VERSION, TRANSITION, public_observation, restore_policy, save_policy
from nosl_experience import terminal
from nosl_model import WIDTH

SPEC = dict(schema=3, character="Ironclad", act=1, act_variant="OVERGROWTH",
            encounter="SHRINKER_BEETLE_WEAK", ascension=0, seed="NOSL3ACHECK",
            hp=80, max_hp=80, relics=[], potions=[],
            deck=[dict(id=card, upgrade=upgrade) for card, upgrade in
                  [("STRIKE_IRONCLAD", 0), ("STRIKE_IRONCLAD", 1), ("DEFEND_IRONCLAD", 0),
                   ("HEADBUTT", 0), ("HEADBUTT", 1)]])


def qualify(output, spec=SPEC, discard_choice=0):
    BINDING["solver_binding"].__globals__["HOST"] = HOST
    versions = BINDING["solver_binding"](output, BINDING["FROZEN"], None)
    synth = BINDING["b1b"].synth
    with ExitStack() as stack:
        predicted, _ = BINDING["attested"](output, stack, versions)
        root, _ = synth.capture(predicted, spec)
        native, _ = BINDING["attested"](output, stack, versions)
        native_root, _ = synth.capture(native, spec)
        assert root["native"] == native_root["native"]
        before = predicted.request("f1_audit")
        native.teacher_frames, native.teacher_choices = [], []
        native.request("i1_begin")
        state = predicted.request("i1_n2_reset", arm="A", cap=64, potions=False, rejected=[])["episode"]
        transitions = []
        torch.manual_seed(7)
        policy = restore_policy(save_policy(Policy()))
        history = torch.zeros(WIDTH)
        reply = None
        with torch.no_grad():
            while state["status"] == "active":
                obs = public_observation(state["observation"])
                decision = Decision(obs)
                logits, _, embedding, instances = policy(decision, history)
                assert logits.numel() == len(obs["actions"])
                position = state["actions"]
                if position < 2:
                    wanted = ("STRIKE_IRONCLAD", "DEFEND_IRONCLAD")[position]
                    menu = [a for a in obs["actions"] if a["card"] is not None
                            and obs["hand"][a["card"]]["id"] == wanted]
                else:
                    menu = obs["actions"]
                action = min(menu, key=lambda a: (
                    a["kind"] == "end_turn",
                    a["kind"] != "play_with_draw_top",
                    a["card"] is None or obs["hand"][a["card"]]["id"] == "DEFEND_IRONCLAD",
                    a["index"],
                ))
                if position == 2:
                    choices = [a for a in menu if a["card"] == action["card"] and a["target"] == action["target"]]
                    action = choices[discard_choice]
                index = action["index"]
                history = policy.remember(history, embedding, instances[index])
                state = predicted.request("i1_n2_step", position=position, index=index)["episode"]
                plan = dict(state["audit_action"])
                if isinstance(plan["kind"], int):
                    plan["kind"] = ("PlayCard", "UsePotion", "EndTurn")[plan["kind"]]
                candidates = [a for a in obs["actions"] if a["card"] == action["card"]
                              and a["target"] == action["target"] and a["choice_zone"] == action["choice_zone"]]
                if len(candidates) == 1:
                    plan.pop("choice", None)
                reply = native.request("i1_step", action=plan)
                assert reply["type"] == "i1_state", reply
                stamp = sha256(reply["state"][0]["exact_continuation_state"].encode()).hexdigest()
                assert stamp == state["audit_stamp"], (position, action, reply.get("terminal"))
                evidence = reply.get("choice_evidence")
                if action["choice_zone"] == "discard" and len(candidates) > 1:
                    expected = [obs["discard"][a["choice"]] for a in candidates]
                    assert evidence["destination_verified"]
                    assert evidence["binding"]["source_index"] == action["choice"]
                    assert [key.split("|", 1)[0] for key in evidence["binding"]["menu"]] == [
                        f'{c["id"]}+{c["upgrade"]}' for c in expected]
                transitions.append(dict(schema=TRANSITION, position=position, observation=obs, action=action,
                                        reference_logp=logits.log_softmax(0).tolist(),
                                        native_stamp_match=True, candidate_count=len(candidates)))
            history = torch.zeros(WIDTH)
            for transition in transitions:
                decision = Decision(transition["observation"])
                logits, _, embedding, instances = policy(decision, history)
                assert logits.log_softmax(0).tolist() == transition["reference_logp"]
                history = policy.remember(history, embedding, instances[transition["action"]["index"]])
        predicted.request("i1_n2_close")
        assert before == predicted.request("f1_audit")
        feedback = terminal(state, transitions[-1]["action"])
        assert feedback["status"] == "predicted_win" and reply["terminal"], feedback
        locked = reply["state"][0]
        assert locked["player_hp"] == feedback["observation"]["hp"]
        assert locked["player_max_hp"] == feedback["observation"]["max_hp"]
        assert locked["player_gold"] == state["result"]["gold"]
        assert locked["player_potions"] == ",".join(p or "-" for p in feedback["observation"]["potions"])
        assert any(t["action"]["kind"] == "play_with_draw_top" and t["candidate_count"] > 1 for t in transitions)
        return dict(versions=versions, model_version=MODEL_VERSION, spec=spec, feedback=feedback,
                    native_gold=locked["player_gold"], native_gold_match=True,
                    logp_replay_match=True, transitions=transitions)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    BINDING["bank"].atomic(output / "qualification.json", [qualify(output, discard_choice=i) for i in (0, 1)])
