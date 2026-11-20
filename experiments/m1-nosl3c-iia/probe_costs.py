"""Verify energy-X and fixed star spending from matched native roots."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path

from qualify import BINDING, HOST, SPEC
from contract import public_observation

CASES = (
    ("energy_x", "Ironclad", ("WHIRLWIND", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD",
                             "DEFEND_IRONCLAD", "STRIKE_IRONCLAD"), ("WHIRLWIND",)),
    ("fixed_stars", "Regent", ("VENERATE", "FALLING_STAR", "STRIKE_REGENT",
                              "DEFEND_REGENT", "STRIKE_REGENT"), ("VENERATE", "FALLING_STAR")),
)


def probe(output):
    BINDING["solver_binding"].__globals__["HOST"] = HOST
    versions = BINDING["solver_binding"](output, BINDING["FROZEN"], None)
    capture = BINDING["b1b"].synth.capture
    results = []
    for name, role, deck, sequence in CASES:
        spec = SPEC | dict(character=role, deck=[dict(id=card, upgrade=0) for card in deck])
        with ExitStack() as stack:
            prediction, native = [BINDING["attested"](output, stack, versions)[0] for _ in range(2)]
            source, _ = capture(prediction, spec)
            independent, _ = capture(native, spec)
            assert source["native"] == independent["native"]
            native_state = independent["public_root"]
            native.teacher_frames, native.teacher_choices = [], []
            native.request("i1_begin")
            state = prediction.request("i1_n2_reset", arm="A", cap=16, potions=False, rejected=[])["episode"]
            evidence = []
            for card in sequence:
                assert state["status"] == "active", state
                obs = public_observation(state["observation"])
                assert obs["stars"] == (native_state.get("stars") or 0)
                matching = [a for a in obs["actions"] if a["card"] is not None
                            and obs["hand"][a["card"]]["id"] == card]
                assert matching, (name, card, obs["stars"], native_state["hand"])
                action = matching[0]
                native_card = native_state["hand"][action["card"]]
                assert native_card["id"] == "CARD." + card and native_card["can_play"]
                if action["energy_x"]:
                    assert action["cost"] == obs["energy"]
                else:
                    assert action["cost"] == native_card["cost"]
                assert action["star_cost"] == native_card.get("star_cost", 0)
                state = prediction.request("i1_n2_step", position=state["actions"],
                                           index=action["index"])["episode"]
                wire = dict(state["audit_action"])
                wire["kind"] = "PlayCard"
                reply = native.request("i1_step", action=wire)
                assert reply["type"] == "i1_state", reply
                stamp = sha256(reply["state"][0]["exact_continuation_state"].encode()).hexdigest()
                assert stamp == state["audit_stamp"], (name, card, action)
                native_state = reply["decision"]
                evidence.append(dict(card=card, action=action, stars_before=obs["stars"],
                                     native_stamp_match=True))
            assert (evidence[-1]["action"]["energy_x"] if name == "energy_x"
                    else evidence[-1]["action"]["star_cost"] > 0)
            prediction.request("i1_n2_close")
            results.append(dict(case=name, spec=spec, steps=evidence))
    return dict(versions=versions, cases=results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    BINDING["bank"].atomic(output / "costs.json", probe(output))
