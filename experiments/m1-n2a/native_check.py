"""Replay frozen N2A actions on independent native development roots."""
import argparse
from pathlib import Path
from time import perf_counter

from qualify import ROOT, bank, ms, s3a, worker


def native_view(state):
    return dict(turn=state["round"], hp=state["player"]["hp"], block=state["player"]["block"],
                energy=state["energy"], draw_count=state["draw_pile_count"],
                hand=[c["id"].removeprefix("CARD.") for c in state["hand"]],
                enemies=[{k: e[k] for k in ("index", "hp", "block")} for e in state["enemies"]],
                actions=[(c["index"], target, c["cost"]) for c in state["hand"] if c["can_play"]
                         for target in ([e["index"] for e in state["enemies"]]
                                        if c["target_type"] == "AnyEnemy" else [None])]
                        + [(None, None, None)])


def differences(projected, state):
    expected = native_view(state)
    actual = dict(projected)
    actual["enemies"] = list(actual["enemies"])
    actual["hand"] = [c["id"] for c in actual["hand"]]
    actual["actions"] = [(a["card"], a["target"], a["cost"]) for a in actual["actions"]]
    return {k: dict(predicted=v, native=expected[k]) for k, v in actual.items() if v != expected[k]}


def audit(game, state, row):
    checked = 0
    for step in row["trajectory"]:
        if state["decision"] != "combat_play":
            return dict(status="native_boundary_difference", step=checked + 1, native=state["decision"])
        diff = differences(step["observation"], state)
        if diff:
            return dict(status="observation_difference", step=checked + 1, fields=diff)
        state = game.execute_action(step["action"])
        checked += 1
    predicted = row["terminal"]
    final = game.request("f1_final")
    status = bank.f1.outcome({"native_final": final}, state)
    status = "predicted_win" if status == "win" else status
    if predicted["status"] not in ("predicted_win", "death"):
        return dict(status="prediction_boundary", checked=checked, native=state["decision"],
                    predicted=predicted, outcome=final["outcome"])
    outcome = final["outcome"]
    pred = predicted["result"]
    resources = final["resources"]
    expected = dict(status=predicted["status"], hp=pred["hp"], gold=pred["gold"],
                    max_hp=pred["max_hp"], potions=pred["potions"], hp_lost=pred["cumulative_loss"])
    actual = dict(status=status, hp=outcome["final_hp"], gold=resources["gold"],
                  max_hp=resources["max_hp"], potions=resources["potions"], hp_lost=outcome["hp_lost"])
    return dict(status="public_and_outcome_match" if expected == actual else "terminal_difference",
                checked=checked, expected=expected, native=actual, evidence="public_diff_only")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    versions = s3a.solver_binding(args.output, s3a.FIXED, ROOT / "logs/m1-e3f/release")
    data = bank.read(args.benchmark)
    result = dict(versions=versions, lifecycle=[], rows=[])
    for item in data["inputs"]:
        for row in (r for r in data["rows"] if r["phase"] == "cold" and r["id"] == item["case"]["id"]):
            started = perf_counter()
            with worker(args.output, item, versions, result["lifecycle"]) as (game, root):
                check = audit(game, root["public_root"], row)
            result["rows"].append(dict(id=row["id"], elapsed_ms=ms(started), **check))
            bank.atomic(args.output / "audit.json", result)


if __name__ == "__main__":
    main()
