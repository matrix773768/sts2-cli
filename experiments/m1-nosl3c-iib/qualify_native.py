"""Compare public selector menus and complete native continuation stamps."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path

from engine import BANK, CAPTURE, bind, open_worker
from interactive_contract import project


def native_action(game, action, **args):
    result = game.request("action", action=action, args=args)
    if result.get("type") == "error":
        raise ValueError(result)
    return result


def compare_menu(obs, native):
    decision = obs["decision"]
    if decision["phase"] == "choice":
        if native["decision"] != "card_select":
            raise ValueError(("Native selector did not open", native["decision"], decision))
        expected = [(c["id"], c["upgrade"]) for c in decision["candidates"]]
        actual = [(c["id"].removeprefix("CARD."), int(c["upgraded"])) for c in native["cards"]]
        assert expected == actual, (expected, actual)
        assert (decision["min"], decision["max"]) == (native["min_select"], native["max_select"])
    else:
        assert native["decision"] == "combat_play", native["decision"]
        assert [c["id"] for c in obs["hand"]] == [c["id"].removeprefix("CARD.") for c in native["hand"]]
        assert obs["energy"] == native["energy"]
        assert obs["stars"] == (native.get("stars") or 0)
        expected = set()
        for card in native["hand"]:
            if not card["can_play"]:
                continue
            if card["target_type"] == "AnyEnemy":
                expected.update((card["index"], target["index"]) for target in native["enemies"])
            else:
                expected.add((card["index"], None))
        actual = {(a["card"], a["target"]) for a in obs["actions"] if a["kind"] == "play_card"}
        assert actual == expected, (actual, expected)


def qualify(output, versions, spec, prioritize, opening=()):
    with ExitStack() as stack:
        projected, native = [open_worker(output, stack, versions) for _ in range(2)]
        original, _ = CAPTURE(projected, spec)
        independent, _ = CAPTURE(native, spec)
        assert original["native"] == independent["native"]
        original_audit = projected.request("f1_audit")
        native.teacher_frames, native.teacher_choices = [], []
        native.request("i1_begin")
        state = projected.request("i1_n2_reset", arm="A", cap=128, potions=False, rejected=[])["episode"]
        live = independent["public_root"]
        transitions = []
        first = True
        remaining = list(opening)
        stamps = 0
        selected = []
        native_terminal = False
        difference = None
        last_combat_kind = None
        while state["status"] == "active":
            obs = project(state["observation"])
            try:
                compare_menu(obs, live)
            except (AssertionError, ValueError) as error:
                raise ValueError(f"{prioritize}, position {state['actions']}: {error}") from error
            menu = obs["actions"]
            if obs["decision"]["phase"] == "choice":
                # Use the last candidate to exercise equal-ID occurrences. Confirm
                # with the selected occurrence indices on the real native selector.
                action = next((a for a in menu if a["kind"] == "confirm_selection"), menu[-1])
            else:
                desired = remaining[0] if remaining else prioritize
                action = min(menu, key=lambda a: (a["kind"] == "end_turn",
                             a["card"] is None or obs["hand"][a["card"]]["id"] != desired,
                             a["index"]))
                if remaining:
                    assert action["card"] is not None and obs["hand"][action["card"]]["id"] == desired, (
                        desired, obs["stars"], obs["energy"])
                    remaining.pop(0)
            if first:
                invalid = projected.request("i1_n2_step", position=1, index=action["index"])["episode"]
                assert invalid["status"] == "invalid_action"
                first = False
            pos = state["actions"]
            kind = action["kind"]
            if obs["decision"]["phase"] == "combat":
                last_combat_kind = kind
            if kind == "play_card":
                args = {"card_index": action["card"]}
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
            state = projected.request("i1_n2_step", position=pos, index=action["index"])["episode"]
            assert state["status"] != "invalid_action"
            # A card is compared at its stable boundary, after all native and
            # simulated choices complete. The intervening candidate order is compared above.
            if state.get("audit_stamp") and state["status"] in ("active", "predicted_win", "death"):
                raw = native.request("i1_iib_native_stamp")
                locked = raw["state"][0]
                stamp = sha256(locked["exact_continuation_state"].encode()).hexdigest()
                native_terminal = raw["terminal"]
                if stamp != state["audit_stamp"]:
                    difference = dict(position=pos, action=kind, native_decision=live["decision"],
                                      predicted_status=state["status"], native_terminal=native_terminal,
                                      predicted_sha256=state["audit_stamp"], native_sha256=stamp)
                    break
                stamps += 1
                if native_terminal:
                    assert locked["player_hp"] == state["result"]["hp"]
                    terminal_obs = state["terminal_observation"]
                    assert locked["player_max_hp"] == terminal_obs["max_hp"]
                    assert locked["player_potions"] == ",".join(p or "-" for p in terminal_obs["potions"])
                    assert locked["player_gold"] == state["result"]["gold"]
            transitions.append(dict(position=pos, action=kind,
                                    effect=obs["decision"].get("effect"), timing=obs["decision"].get("timing"),
                                    candidate=action["choice"],
                                    automatic=state.get("automatic", [])))
        projected.request("i1_n2_close")
        assert projected.request("f1_audit") == original_audit
        status = state["status"]
        if status == "predicted_win" and last_combat_kind == "end_turn":
            status = "rule_risk"
        if difference:
            status = "native_difference"
        return dict(terminal=status, detail=state.get("detail"), native_terminal=native_terminal,
                    difference=difference, exact_boundaries=stamps, steps=transitions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    versions = bind(out, args.solver)
    cfg = json.loads((Path(__file__).parent / "integration.json").read_bytes())
    results = []
    roots = [r for batch in cfg["batches"] for r in batch]
    base = roots[0]
    for role, cards in (
        ("Silent", ("TOOLS_OF_THE_TRADE",) + ("STRIKE_SILENT",) * 4),
        ("Regent", ("DECISIONS_DECISIONS", "GLIMMER") + ("VENERATE",) * 3),
        ("Regent", ("QUASAR", "VENERATE") + ("STRIKE_REGENT",) * 3),
    ):
        roots.append(base | dict(character=role, deck=[dict(id=c, upgrade=0) for c in cards]))
    for spec in roots:
        card = spec["deck"][0]["id"]
        try:
            opening = {"DECISIONS_DECISIONS": ("VENERATE",) * 3 + (card,),
                       "QUASAR": ("VENERATE", card)}.get(card, ())
            result = qualify(out, versions, spec, card, opening)
        except (AssertionError, ValueError, BANK.f1.i2.StopRun) as error:
            result = dict(terminal="native_difference", detail=str(error))
        results.append(dict(card=card, **result))
        BANK.atomic(out / "native.json", dict(versions=versions, results=results))


if __name__ == "__main__":
    main()
