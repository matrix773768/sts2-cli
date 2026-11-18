"""Export public candidate and result tables separately from offline teacher routes."""
import argparse
import json
from pathlib import Path

from sample import f1


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def control(row, initial):
    final = row.get("native_final")
    data = {k: row[k] for k in ("status", "detail", "policy_version", "root_verified",
                                "elapsed_ms", "cold_root_ms", "peak_working_set_bytes") if k in row}
    trace = row["trace"]
    data["actions"] = len(trace)
    data["timing_ms"] = {}
    for key in ("decision_ms", "observe_ms", "execute_ms", "execute_wall_ms"):
        values = [step[key] for step in trace if key in step]
        data["timing_ms"][key] = round(sum(values), 4) if values else None
    if final:
        data.update(outcome=final["outcome"], round=final["round"],
                    result_player_hp=final["resources"]["hp"],
                    choice_decision_ms=final["choice_decision_ms"],
                    resource_changes=changes(initial, final["resources"]))
    return data


def changes(initial, final):
    return {k: {"before": initial[k], "after": final[k]}
            for k in initial if k != "hp" and initial[k] != final[k]}


def mechanism(root):
    cards = {card["id"].removeprefix("CARD.") for card in root["public_root"]["player"]["deck"]}
    rules = (
        ("draw", {"POMMEL_STRIKE", "SHRUG_IT_OFF", "VICIOUS", "OFFERING"}),
        ("energy_or_cost_change", {"OFFERING", "ENLIGHTENMENT"}),
        ("discard_topdeck_and_scaling", {"HEADBUTT", "RAMPAGE"}),
        ("self_hp_loss_payoffs", {"INFERNO", "TEAR_ASUNDER"}),
        ("max_hp_on_kill", {"FEED"}),
    )
    return {label: sorted(known & cards) for label, known in rules if known & cards}


def publish(source, output):
    manifest = load(source / "manifest.json")
    rows = load(source / "evaluation.json")
    references = load(source / "reference-routes.json")
    roots = {root["id"]: root for root in manifest["roots"]}
    assert list(roots) == [r["id"] for r in rows]
    assert len(roots) == len({r["identity"]["live"] for r in roots.values()})
    published_routes = {}
    for row in rows:
        rid = row["id"]
        root = roots[rid]
        assert root["context"]["act"] >= 2
        checkpoint = source / root["checkpoint"]
        assert f1.digest(checkpoint.read_bytes()) == root["checkpoint_sha256"]
        root["deck_mechanisms"] = mechanism(root)
        root["partition"] = "development"
        root["independently_root_verified"] = any(attempt["root_verified"] for attempt in row["attempts"])
        root["stratum"] = row["stratum"]
        initial = root["identity"]["resources"]
        if ref := references.get(rid):
            published_routes[rid] = ref
        if replay := row.get("replay"):
            final = replay["native_final"]
            remaining = final.pop("resources")
            replay["result_player_hp"] = remaining["hp"]
            replay["resource_changes"] = changes(initial, remaining)
            if replay["status"] == "win":
                route = published_routes[rid]
                trace = route["verification"]["trace"]
                assert replay["root_verified"] and replay["strict_terminal"]
                assert replay["matched_actions"] == len(route["plan_actions"]) == len(trace)
                assert all(t["expected_sha256"] == t["actual_sha256"] for t in trace)
                assert not any(t["terminal"] for t in trace[:-1])
                assert trace[-1]["terminal"] and trace[-1]["decision"] in ("card_reward", "map_select", "game_over")
                outcome = final["outcome"]
                assert outcome["combat_ended"] and outcome["survived"] and outcome["final_enemy_hp"] == 0
                assert final["terminal_callback"]
        if "controls" in row:
            row["controls"] = {mode: control(result, initial) for mode, result in row["controls"].items()}
            assert all(result["root_verified"] for result in row["controls"].values())
    for route in manifest["routes"]:
        route["native_command_count"] = len(route.pop("commands"))
    manifest["partition_note"] = "All candidates share one historical Act 1 lineage. No held-out roots."
    output.mkdir(parents=True, exist_ok=True)
    f1.write(output / "manifest.json", manifest)
    f1.write(output / "evaluation.json", rows)
    # Future strategy runners only receive the checkpoints and public manifest.
    f1.write(output / "offline-reference-routes.json", published_routes)
    print(f"{len(rows)} candidates, {sum(r.get('replay', {}).get('status') == 'win' for r in rows)} strict native wins")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    publish(args.source, args.output)
