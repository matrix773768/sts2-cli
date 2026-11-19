"""Independently replay decisions and compare observation, choice and terminal surfaces."""
import argparse
from pathlib import Path

from qualify_interaction import base, original_stops
from native_check import differences

f3b = base.n1["diagnose"]["f3b"]
POWERS = {"STRENGTH_POWER", "DEXTERITY_POWER", "WEAK_POWER", "VULNERABLE_POWER", "FRAIL_POWER"}


def native_powers(values):
    powers = (dict(id=p["name"].removesuffix(".title"), amount=p["amount"]) for p in values or [])
    return sorted((p for p in powers if p["id"] in POWERS), key=lambda p: p["id"])


def compare(observation, state):
    result = []
    basic = {k: v for k, v in observation.items() if k != "powers"} | {
        "enemies": [{k: e[k] for k in ("index", "hp", "block")} for e in observation["enemies"]],
        "actions": list({(a["card"], a["target"]): a for a in observation["actions"]}.values()),
    }
    if diff := differences(basic, state):
        result.append(dict(field="base", diff=diff))
    if observation["powers"] != native_powers(state.get("player_powers")):
        result.append(dict(field="player_powers", predicted=observation["powers"],
                           native=native_powers(state.get("player_powers"))))
    for enemy, native in zip(observation["enemies"], state["enemies"]):
        for key, value in {"intents": [i["type"] for i in native["intents"] or []],
                           "powers": native_powers(native.get("powers"))}.items():
            if enemy[key] != value:
                result.append(dict(field=key, slot=enemy["index"], predicted=enemy[key], native=value))
        hits = [i["damage"] for i in native["intents"] or [] if "damage" in i
                for _ in range(i.get("hits", 1))]
        if enemy["attack_hits"] != hits:
            result.append(dict(field="attack_hits", slot=enemy["index"],
                               predicted=enemy["attack_hits"], native=hits))
    for action in basic["actions"]:
        preview = action.get("preview")
        if not preview:
            continue
        card = state["hand"][action["card"]]
        stats = card["stats"] or {}
        target = next((t for t in card.get("damage_by_target", [])
                       if t["target_index"] == action["target"]), {})
        for key, value in {"damage_per_hit": target.get("damage"), "hits": target.get("repeat", 2 if card["id"] == "CARD.TWIN_STRIKE" else 1),
                           "block": stats.get("block"), "draw": stats.get("cards")}.items():
            if preview[key] is not None and preview[key] != value:
                result.append(dict(field=key, card=card["id"], predicted=preview[key], native=value))
    return result


def audit(game, state, row):
    game.teacher_frames, game.teacher_choices = [], []
    game.request("i1_begin")
    diffs, choices = [], []
    step_count = 0
    native_stamp = stamp = None
    last = None
    for step, plan, stamp in zip(row["trajectory"], row["terminal"]["audit_actions"],
                                 row["terminal"]["audit_stamps"], strict=True):
        if state["decision"] != "combat_play" or plan is None:
            break
        obs = step["observation"]
        diffs.extend(dict(step=step_count + 1, **d) for d in compare(obs, state))
        selected = step["action"].get("choice_index")
        candidates = [a["choice"] for a in obs["actions"]
                      if selected is not None and a["card"] == step["action"]["args"]["card_index"]]
        wire = f3b.action_for_wire(plan)
        # The native selector short-circuits a mandatory one-item menu.
        if len(candidates) == 1:
            wire.pop("choice")
        try:
            last = game.request("i1_step", action=wire)
        except base.bank.f1.i2.StopRun as error:
            return dict(status="native_error", checked=step_count, detail=str(error),
                        diffs=diffs, choices=choices)
        if last["type"] != "i1_state":
            return dict(status="native_rejected", checked=step_count, reply=last, diffs=diffs, choices=choices)
        step_count += 1
        native_stamp = base.bank.f1.digest(last["state"][0]["exact_continuation_state"].encode())
        if selected is not None and len(candidates) == 1:
            choices.append(dict(step=step_count, kind="native_singleton", selected=selected,
                                candidates=candidates, state_match=native_stamp == stamp))
        elif evidence := last.get("choice_evidence"):
            binding = evidence["binding"]
            native_menu = [key.split("|", 1)[0] for key in binding["menu"]]
            expected = [f'{c["id"]}+{c["upgrade"]}' for c in candidates]
            choices.append(dict(step=step_count, selected=selected, native_index=binding["option"],
                                source_index=binding["source_index"], native_menu=native_menu,
                                predicted_menu=expected, verified=evidence["destination_verified"],
                                state_match=native_stamp == stamp))
        state = last["decision"]
    final = game.request("f1_final")
    status = base.bank.f1.outcome({"native_final": final}, state)
    predicted = row["terminal"]["feedback"]["combat_terminal"]
    locked = last["state"][0] if last and last["terminal"] else {}
    return dict(status=status, checked=step_count, diffs=diffs, choices=choices,
                predicted_terminal=predicted, native_outcome=final["outcome"],
                native_locked={k: locked[k] for k in ("player_hp", "player_max_hp", "player_gold", "player_potions")
                               if k in locked},
                native_after_combat={"decision": state["decision"], "resources": final["resources"],
                                     "reward_action_executed": False},
                strict_terminal_stamp_match=(native_stamp == stamp) if last and last["terminal"] else None,
                evidence="public_and_choice_audit")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    versions = base.s3a.solver_binding(output, base.s3a.FIXED, base.ROOT / "logs/m1-e3f/release")
    data = base.bank.read(args.benchmark)
    result = dict(versions=versions, original_stops=original_stops(), lifecycle=[], rows=[])
    for item in data["inputs"]:
        rows = [r for r in data["rows"] if r["id"] == item["case"]["id"]]
        selected = [next(r for r in rows if r["phase"] == "cold")]
        if any(r["defense_first"] for r in rows):
            selected.append(next(r for r in rows if r["defense_first"]))
        for row in selected:
            with base.worker(output, item, versions, result["lifecycle"]) as (game, root):
                check = audit(game, root["public_root"], row)
            result["rows"].append(dict(id=row["id"], defense_first=row["defense_first"], **check))
            base.bank.atomic(output / "audit.json", result)


if __name__ == "__main__":
    main()
