"""Probe native Hidden Daggers, then compare independent Solver continuations."""
from contextlib import ExitStack
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iij2"))
from verify_guards import TOOLS, targets, target_indices, native_step, compare_state
from qualify_native import native_action


def fixture(output, versions, upgrade, count, native_only):
    deck = [dict(id="HIDDEN_DAGGERS", upgrade=upgrade)]
    deck.extend(dict(id=card, upgrade=0)
                for card in ("STRIKE_SILENT", "DEFEND_SILENT", "BLUR")[:count])
    spec = TOOLS["batch"]("iii9b-pair16", 0, "000004")["spec"] | {"deck": deck}
    compare = TOOLS["compare_menu"]
    with ExitStack() as stack:
        native = targets.open_worker(output, stack, versions)
        first, _ = targets.CAPTURE(native, spec)
        live = first["public_root"]
        native.request("i1_begin")
        hand = live["hand"]
        index, = [i for i, card in enumerate(hand) if card["id"] == "CARD.HIDDEN_DAGGERS"]
        if not native_only:
            pred = targets.open_worker(output, stack, versions)
            second, _ = targets.CAPTURE(pred, spec)
            assert first["native"] == second["native"]
            state = pred.request("i1_n2_reset", arm="A", cap=16, potions=False, rejected=[])["episode"]
            obs = targets.project(state["observation"])
            compare(obs, live, target_indices(pred, native))
            action, = [a for a in obs["actions"] if a["card"] == index]
            state = pred.request("i1_n2_step", position=0, index=action["index"])["episode"]
            assert state["status"] == "active", state.get("detail")
        live = native_action(native, "play_card", card_index=index)
        pending = live["decision"] == "card_select"
        menu = live if pending else None
        if pending:
            indices = list(range(live["min_select"]))
            if not native_only:
                for position, candidate in enumerate(indices, 1):
                    obs = targets.project(state["observation"])
                    compare(obs, live, {})
                    action, = [a for a in obs["actions"] if a["choice"] == candidate]
                    state = pred.request("i1_n2_step", position=position, index=action["index"])["episode"]
                obs = targets.project(state["observation"])
                compare(obs, live, {})
                confirm, = [a for a in obs["actions"] if a["kind"] == "confirm_selection"]
                state = pred.request("i1_n2_step", position=len(indices) + 1, index=confirm["index"])["episode"]
            live = native_action(native, "select_cards", indices=",".join(map(str, indices)))
        frame = native.request("i1_iib_native_stamp")["state"][0]["exact_continuation_state"]
        stamp = None
        if not native_only:
            stamp = compare_state(pred, native, state)
            compare(targets.project(state["observation"]), live, target_indices(pred, native))
        return dict(upgrade=upgrade, count=count, pending=pending, menu=menu, after=live,
                    native_state=frame, exact_stamp=stamp)


if __name__ == "__main__":
    mode, dest, solver = sys.argv[1:]
    output = Path(dest).resolve()
    output.mkdir(parents=True)
    targets.configure()
    versions = TOOLS["bind"](output, Path(solver).resolve())
    cases = [fixture(output, versions, upgrade, count, mode == "native")
             for upgrade in (0, 1) for count in range(4)]
    TOOLS["save_json"](output / "daggers.json", dict(engine=versions, cases=cases))
