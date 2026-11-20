"""Audit incomplete and previously blocked paths in two independent processes."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path

from completion_engine import bind, iig, targets
from compare_frozen import entries
from nosl_experience import save_json
from qualify_native import native_action
from replay_frozen import key
from replay_archive import selection


def target_indices(pred, native):
    first = pred.request("i1_iid_prediction_roster")
    second = native.request("i1_iid_native_roster")
    result = {}
    for side in ("enemy", "ally"):
        if set(first[side]) != set(second[side]) or len(set(second[side])) != len(second[side]):
            raise ValueError(f"Different {side} roster")
        result[side] = [second[side].index(entity) for entity in first[side]]
    return result


def native_step(native, action, slots, selected):
    kind = action["kind"]
    if kind == "play_card":
        args = {"card_index": action["card"]}
        if action["target_side"]:
            side = action["target_side"]
            name = "ally_index" if side == "ally" else "target_index"
            args[name] = slots[side][action["target"]]
        return native_action(native, kind, **args)
    if kind == "end_turn":
        return native_action(native, kind)
    if kind == "select_candidate":
        selected.append(action["choice"])
        return None
    if kind == "confirm_selection":
        response = native_action(native, "select_cards", indices=",".join(map(str, selected)))
        selected.clear()
        return response
    raise ValueError(f"No native binding for {kind}")


def probe(output, versions, batch, continue_choice, last_candidate):
    row = next(iter(batch["rows"]), None)
    route = row["transitions"] if row else []
    if not route:
        return {"status": "no_archived_actions"}
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        first, _ = targets.CAPTURE(pred, batch["spec"])
        second, _ = targets.CAPTURE(native, batch["spec"])
        if first["native"] != second["native"]:
            raise ValueError("Independent starts differ")
        native.teacher_choices, native.teacher_frames = [], []
        native.request("i1_begin")
        state = pred.request("i1_n2_reset", arm="A", cap=len(route)+32, potions=False, rejected=[])["episode"]
        live = second["public_root"]
        selected = []
        results = []
        position = 0
        while state["status"] == "active":
            position = state["actions"]
            obs = targets.project(state["observation"])
            menu = obs["actions"]
            choice = obs["decision"]["phase"] == "choice"
            try:
                slots = {} if choice else target_indices(pred, native)
                iig.audit.compare_menu(obs, live, slots)
                if position < len(route):
                    fixed = route[position]
                    if any(obs[name] != value for name, value in fixed["observation"].items() if name != "actions"):
                        return dict(status="historical_observation_diverged", position=position, steps=results)
                    action, = [a for a in menu if key(a) == key(fixed["action"])]
                elif choice and continue_choice:
                    action = next((a for a in menu if a["kind"] == "confirm_selection"),
                                  menu[-1] if last_candidate else menu[0])
                else:
                    break
                live = native_step(native, action, slots, selected) or live
                trigger_trace = state.get("interaction_trace")
                state = pred.request("i1_n2_step", position=position, index=action["index"])["episode"]
            except (AssertionError, ValueError) as error:
                return dict(status="menu_or_action_difference", position=position, detail=str(error),
                            public=obs, native=live, steps=results)
            data = dict(position=position, action=action, public_choice=obs["decision"] if choice else None,
                        source="archived" if position < len(route) else "new_diagnostic_choice",
                        interaction=trigger_trace, status=state["status"])
            results.append(data)
            if state.get("audit_stamp") and live["decision"] != "card_select":
                frame = native.request("i1_iib_native_stamp")
                if not frame.get("state"):
                    return dict(status="native_frame_missing", position=position, native=live, steps=results)
                raw = frame["state"][0]["exact_continuation_state"]
                native_stamp = sha256(raw.encode()).hexdigest()
                if native_stamp != state["audit_stamp"]:
                    predicted = pred.request("i1_iid_prediction_text")["text"]
                    return dict(status="continuation_difference", position=position, native=live,
                                native_terminal=frame["terminal"], differences=targets.field_diff(predicted, raw),
                                predicted=state["status"], steps=results)
                data.update(stamp=native_stamp, native_terminal=frame["terminal"])
        pred.request("i1_n2_close")
        return dict(status=state["status"], native_decision=live["decision"], steps=results,
                    interaction=state.get("interaction_trace"),
                    last_stable=next((s["position"] for s in reversed(results) if s.get("stamp")), None),
                    comparison_reached=position, archived_actions=len(route))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("ledgers", type=Path, nargs="+")
    parser.add_argument("--solver", type=Path, required=True)
    parser.add_argument("--case", action="append", required=True)
    parser.add_argument("--continue-choice", action="store_true")
    parser.add_argument("--last-candidate", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    targets.configure()
    versions = bind(output, args.solver.resolve())
    cases = selection(args.case)
    results = []
    for ledger in args.ledgers:
        for step, root, batch in entries(ledger):
            if (ledger.name, step, root) not in cases:
                continue
            outcome = probe(output, versions, batch, args.continue_choice, args.last_candidate)
            results.append(dict(ledger=ledger.name, step=step, root=root, **outcome))
            save_json(output / "prefix.json", dict(engine=versions, results=results))
