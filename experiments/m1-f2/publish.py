"""Verify F1 control parity and publish F2 replay evidence."""
import argparse
from pathlib import Path
import json

from benchmark import CUBEX, DEFECT, IRON, SILENT, f1, read


def actions(row):
    return [step["action"] for step in row["trace"]]


def terminal(row):
    return {k: v for k, v in row["native_final"].items()
            if k not in ("choice_decision_ms", "choice_observation_ms")}


def parity_trace(row):
    keys = ("action", "pre_audit", "post_audit", "choice_requests", "choice_checks")
    return [{k: step.get(k) for k in keys} for step in row["trace"]]


def selections(row):
    return [dict(request=request, checks=step.get("choice_checks", []),
                 pre_audit=step.get("pre_audit"), post_audit=step.get("post_audit"))
            for step in row["trace"] for request in step.get("choice_requests", [])]


def total(trace, field):
    values = [step[field] for step in trace if field in step]
    return round(sum(values), 4) if values else None


def summarize(row, root):
    final = row["native_final"]
    keys = ("id", "policy", "policy_version", "status", "detail", "repeat",
            "elapsed_ms", "cold_root_ms", "peak_working_set_bytes", "root_verified", "intervention",
            "differential", "matched_actions", "solve_wall_ms", "teacher_total_ms", "plan",
            "teacher_choices", "native_neutralize")
    data = {k: row[k] for k in keys if k in row}
    initial, remaining = root["identity"]["resources"], final["resources"]
    trace = row["trace"]
    choices = selections(row)
    if row["status"] == "win":
        assert final["terminal_callback"] and final["outcome"]["survived"] and final["outcome"]["final_enemy_hp"] == 0
        if row["policy"] == "C":
            assert row["matched_actions"] == len(trace) and row["differential"] == "pass"
    if row["status"] == "death":
        assert final["outcome"]["final_hp"] == 0
    data.update(ascension=root["ascension"], live=root["identity"]["live"],
                control_only=row["policy"] in ("A", "B") and root["character"] != "Silent",
                terminal_callback=final["terminal_callback"], outcome=final["outcome"], round=final["round"],
                action_requests=len(trace), result_player_hp=remaining["hp"],
                resource_changes={k: {"before": initial[k], "after": remaining[k]}
                                  for k in initial if initial[k] != remaining[k] and k != "hp"},
                timing_ms=dict(play_policy=total(trace, "decision_ms"), observe=total(trace, "observe_ms"),
                               choice_policy=final["choice_decision_ms"] if row["policy"] in ("B", "B_cf") else None,
                               native_action=total(trace, "native_ms" if row["policy"] == "C" else "execute_ms"),
                               wall_action=total(trace, "wall_ms" if row["policy"] == "C" else "execute_wall_ms")))
    if choices:
        data["choices"] = choices
    if row["policy"] == "C":
        frames = row["teacher_frames"]
        data["native_frame_sha256"] = [f1.digest(json.dumps(frame, sort_keys=True).encode()) for frame in frames]
        fields = ("enemy_hps_by_model", "all_enemy_powers", "rng_counters")
        data["neutralize_evidence"] = [
            {"step": i + 1, "before": {k: frames[i - 1][k] for k in fields},
             "after": {k: frames[i][k] for k in fields}}
            for i, step in enumerate(trace)
            if 0 < i < len(frames) and step["plan_action"]["card_id"] == "NEUTRALIZE"
        ]
        data["potion_evidence"] = [{pos: {k: frame[k] for k in ("player_potions", "rng_counters")}
                                    for pos, frame in step["potion_evidence"].items()}
                                   for step in trace if "potion_evidence" in step]
        if "first_difference" in row:
            data["first_difference"] = row["first_difference"]
    return data


def validate(rows, frozen_rows, frozen_cf, roots):
    base = {(r["id"], r["policy"]): r for r in frozen_rows if r["policy"] in ("A", "B")}
    by_key = {(r["id"], r["policy"]): r for r in rows if not r.get("repeat")}
    assert len(roots) == 18 and len(base) == 36
    assert all(r["root_verified"] and r["checkpoint_match"] for r in rows)
    for key, old in base.items():
        row = by_key[key]
        if not row["id"].startswith("silent-"):
            assert row["status"] == old["status"] and actions(row) == actions(old)
            assert terminal(row) == terminal(old)
        elif row["policy"] == "A":
            assert row["status"] == old["status"] and all(row["native_final"][k] == old["native_final"][k]
                                                         for k in ("outcome", "round", "resources"))
    for row in (r for r in rows if r.get("repeat")):
        first = by_key[row["id"], row["policy"]]
        assert row["status"] == first["status"] and terminal(row) == terminal(first)
        assert parity_trace(row) == parity_trace(first)
    for row in (r for r in rows if r["id"].startswith("silent-") and r["policy"] in ("A", "B")):
        assert row["status"] in ("win", "death")
        discarded = [c for c in selections(row) if c["request"]["action"] in ("SURVIVOR", "PREPARED")]
        if row["policy"] == "B":
            assert discarded
        for choice in discarded:
            check, = [c for c in choice["checks"] if "discard" in c]
            assert check["discard"] and check["rng_at_choice"] == check["rng_after"]
            assert [i["option"] for i in check["instances"]] == choice["request"]["indexes"]
            assert choice["post_audit"]
    evidence = []
    for old in frozen_cf:
        rid, step = old["id"], old["intervention"]["step"]
        cf = by_key[rid, "B_cf"]
        normal = by_key[rid, "B"]
        assert cf["status"] == old["status"] and terminal(cf) == terminal(old) and actions(cf) == actions(old)
        assert parity_trace(normal)[:step - 1] == parity_trace(cf)[:step - 1]
        parent, intervention = normal["trace"][step - 1], cf["trace"][step - 1]
        assert parent["public"] == intervention["public"] and parent["pre_audit"] == intervention["pre_audit"]
        assert parent["observation"] == intervention["observation"] and parent["action"] != intervention["action"]
        reference = by_key[rid, "A"] if rid == DEFECT else next(
            r for r in frozen_rows if r["id"] == rid and r["policy"] == "C")
        reference_action = reference["trace"][step - 1]
        assert reference["status"] == "win"
        assert (reference_action.get("native_action") or reference_action["action"]) == intervention["action"]
        evidence.append(dict(id=rid, step=step, public_parent=parent["public"], parent_native=parent["pre_audit"],
                             legal_cards=parent["observation"]["moves"], end_turn_legal=True,
                             baseline=parent["action"], forced=intervention["action"],
                             baseline_after=parent["post_audit"], intervention_after=intervention["post_audit"],
                             native_terminal={r["policy"]: r["native_final"]["outcome"]
                                              for r in (normal, cf, reference)}))
    assert {r["id"] for r in rows if r["policy"] == "C"} == {CUBEX, SILENT}
    return evidence


def publish(source, f1_output, prepared, output, teacher=None):
    roots = {r["id"]: r for r in read(f1_output / "manifest.json")["roots"]}
    rows = read(source / "results.json")
    if teacher:
        rows = [r for r in rows if r["policy"] != "C"] + read(teacher / "results.json")
    evidence = validate(rows, read(f1_output / "results.json"), read(f1_output / "counterfactuals.json"), roots)
    output.mkdir(parents=True, exist_ok=True)
    f1.write(output / "results.json", [summarize(r, roots[r["id"]]) for r in rows if not r.get("repeat")])
    f1.write(output / "prepared.json", read(prepared / "prepared.json"))
    f1.write(output / "strategy-parents.json", evidence)
    with (output / "strategy-traces.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            if row["id"] not in (IRON, DEFECT):
                continue
            root = roots[row["id"]]
            for step in row["trace"]:
                entry = dict(id=row["id"], policy=row["policy"],
                             **{k: v for k, v in step.items() if not k.endswith("_ms")})
                if "public" in entry:
                    public = entry["public"]
                    if public["player"]["deck"] == root["public_root"]["player"]["deck"]:
                        entry["public"] = {**public, "player": {k: v for k, v in public["player"].items() if k != "deck"}}
                        entry["player_deck_from_strategy_parent"] = True
                stream.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"Verified {len(rows)} trials, 28 non-Silent controls and two intervention parents")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("f1_output", type=Path)
    parser.add_argument("prepared", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--teacher", type=Path)
    args = parser.parse_args()
    publish(args.source, args.f1_output, args.prepared, args.output, args.teacher)
