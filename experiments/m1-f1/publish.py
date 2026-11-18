"""Publish benchmark observations without native saves or raw prediction frames."""
import argparse
from pathlib import Path
import json

from benchmark import write

CASES = {
    "ironclad-a0-run_1-f05", "silent-a0-run_2-f02", "ironclad-a10-run_2-f06",
    "defect-a10-run_1-f05", "ironclad-a0-run_1-archive-f08", "ironclad-a0-run_1-archive-f17",
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def hand(cards):
    return [{key: card[key] for key in ("index", "id", "cost", "can_play", "type", "stats")
             if key in card} for card in cards]


def step_action(row):
    return row.get("native_action") or row.get("action") or row.get("plan_action")


def project_trace(row):
    fields = ("round", "player_hp", "energy", "block", "enemies", "selected", "observation",
              "after_hp", "after_round", "after_energy", "after_hand", "forced", "phase")
    return dict(action=step_action(row), **{key: row[key] for key in fields if key in row})


def total(trace, field):
    values = [row[field] for row in trace if field in row]
    return round(sum(values), 4) if values else None


def summarize(row, initial, paired):
    report = {k: v for k, v in row.items() if k not in ("executed", "trace", "teacher_frames")}
    trace = row["trace"]
    final = report.get("native_final", {})
    report["action_requests"] = len(trace)
    report["choice_requests"] = len(final.get("choice_requests", [])) + sum(
        step.get("phase") == "choice" for step in trace)
    report["timing_ms"] = {
        "policy": total(trace, "decision_ms"),
        "observation": total(trace, "observe_ms"),
        "action_native": total(trace, "execute_ms") if row["policy"] != "C" else total(trace, "native_ms"),
        "action_wall": total(trace, "wall_ms" if row["policy"] == "C" else "execute_wall_ms"),
    }
    if final and report["timing_ms"]["policy"] is not None:
        report["timing_ms"]["policy"] += final["choice_decision_ms"]
    if final:
        resources = final["resources"]
        report["native_final"] = {key: value for key, value in final.items() if key != "resources"}
        report["result_player_hp"] = resources["hp"]
        report["resource_changes"] = {
            key: {"before": initial[key], "after": resources[key]}
            for key in ("max_hp", "gold", "deck", "relics", "potions") if resources[key] != initial[key]
        }
    report["other_verified_wins"] = [ref["policy"] for ref in paired if ref is not row and ref["status"] == "win"]
    report["better_verified_routes"] = []
    for ref in paired:
        if ref is row or ref["status"] != "win":
            continue
        candidate = ref["native_final"]["outcome"]
        if row["status"] == "death" or (row["status"] == "win"
            and candidate["hp_lost"] < final["outcome"]["hp_lost"]
            and len(candidate["potions"]) <= len(final["outcome"]["potions"])
            and ref["native_final"]["resources"]["max_hp"] >= final["resources"]["max_hp"]):
            report["better_verified_routes"].append(ref["policy"])
    return report


def publish(source, output):
    manifest = read(source / "manifest.json")
    roots = manifest["roots"]
    ids = {root["id"] for root in roots}
    assert len(ids) == len(roots) == len({r["identity"]["live"] for r in roots})
    for root in roots:
        root["public_root"]["hand"] = hand(root["public_root"]["hand"])
        player = root["public_root"]["player"]
        player["deck"] = [{k: v for k, v in card.items() if k not in ("description", "after_upgrade")}
                          for card in player["deck"]]
        root.pop("archived_suffix", None)
    runs = read(source / "results.json")
    if (source / "counterfactuals.json").exists():
        runs += read(source / "counterfactuals.json")
    for policy in ("A", "B"):
        rows = [row for row in runs if row["policy"] == policy]
        assert len(rows) == len(roots) and {row["id"] for row in rows} == ids
    for row in runs:
        assert row["root_verified"] and row["checkpoint_match"]
        if row["status"] in ("death", "win"):
            native = row["native_final"]
            outcome = native["outcome"]
            if row["status"] == "death":
                assert not outcome["survived"] and outcome["final_hp"] == 0
            else:
                assert native["terminal_callback"] and outcome["survived"] and outcome["final_enemy_hp"] == 0
                if row["policy"] == "C":
                    assert row["matched_actions"] == len(row["trace"]) and row["differential"] == "pass"
    output.mkdir(parents=True, exist_ok=True)
    write(output / "manifest.json", manifest)
    resources = {root["id"]: root["identity"]["resources"] for root in roots}
    write(output / "results.json", [
        summarize(row, resources[row["id"]], [ref for ref in runs if ref["id"] == row["id"]])
        for row in runs
    ])
    with (output / "cases.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for row in runs:
            if row["id"] not in CASES:
                continue
            for index, step in enumerate(row["trace"], 1):
                entry = dict(id=row["id"], policy=row["policy"], request=index, **project_trace(step))
                if "hand" in step:
                    entry["hand"] = hand(step["hand"])
                stream.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    publish(args.source, args.output)
