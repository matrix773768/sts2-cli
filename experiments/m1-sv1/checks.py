"""Run focused checks against fresh CombatSolver branches."""
import argparse
from collections import defaultdict, deque
from contextlib import closing
import json
from pathlib import Path

from campaign import ROOT, Host, config, encode, open_source, payload, reconstruct, search


def recipe(cards, seed="SV1FIXTURE01", hp=80, **overrides):
    return dict(schema=2, character="Ironclad", ascension=0, act=1, act_variant="OVERGROWTH",
                encounter="CUBEX_CONSTRUCT_NORMAL", seed=seed, hp=hp, max_hp=80, relics=[], potions=[],
                deck=[dict(id=entry, upgrade=upgraded) for entry, upgraded in cards]) | overrides


def outcomes(graph):
    return {(entry["outcome"]["kind"], entry["outcome"]["state"], first)
            for entry in graph["graph"]["endpoints"] for first in entry["first_actions"]}


def compare(result):
    tree = result["tree"]["graph"]
    reference = outcomes(result["tree"])
    edges = {(edge["from"], encode(edge["action"])): edge["to"] for edge in tree["edges"]}
    leaves = {node: entry["outcome"]["state"] for entry in tree["endpoints"] for node in entry["nodes"]}
    for mode, graph in result.items():
        assert not graph.get("stop"), (mode, graph.get("stop"))
        assert not graph["counts"]["endpoints"].get("error"), (mode, graph["graph"]["endpoints"])
        assert graph["graph"]["first_actions"] == tree["first_actions"]
        actual = outcomes(graph)
        assert actual == reference, (mode, len(actual), len(reference), list(reference - actual)[:3])
        validate_paths(graph["graph"])
        for entry in graph["graph"]["endpoints"]:
            node = 0
            for action in entry["witness"]:
                node = edges[node, encode(action)]
            assert leaves[node] == entry["outcome"]["state"]


def validate_paths(graph):
    """Recompute reachability by independent traversals from every first edge."""
    successors, sources = defaultdict(list), defaultdict(set)
    for edge in graph["edges"]:
        successors[edge["from"]].append(edge["to"])
    for index, node in enumerate(successors[0]):
        pending = deque([node])
        visited = set()
        while pending:
            current = pending.popleft()
            if current in visited:
                continue
            visited.add(current)
            sources[current].add(index)
            pending.extend(successors[current])
    for entry in graph["endpoints"]:
        reached = set().union(*(sources[node] for node in entry["nodes"]))
        assert reached == set(entry["first_actions"])


def sample_history(lane, cfg):
    path = ROOT / "logs/m1-pre1-data-structured/dataset.sqlite"
    with closing(open_source(path)) as db:
        data, expected, spec = db.execute("""
            SELECT t.payload,t.sha,p.recipe FROM trajectories t JOIN private_tasks p USING(id)
            WHERE t.split='train' AND t.complete=1 ORDER BY t.ordinal LIMIT 1
        """).fetchone()
    row = payload(data, expected)
    position = min(len(row["steps"]) - 1, 6)
    _, timing = reconstruct(lane, json.loads(spec), row["steps"], position)
    graph = search(lane, "k0", cfg["settings"], verify=True)
    lane.reset()
    return dict(prefix=position, timing=timing, counts=graph["counts"])


def hidden_worlds(lane, settings):
    """Find two identical public roots with distinct hidden draw orders."""
    cards = [("POMMEL_STRIKE", 0)] * 4 + [("STRIKE_IRONCLAD", 0)] * 2
    cards += [("DEFEND_IRONCLAD", 0), ("BASH", 0)]
    fixture = {"enemy_hp": 40}
    openings = {}
    for number in range(64):
        spec = recipe(cards, seed=f"SV1HIDDEN{number:02}")
        lane.launch()
        state, _ = reconstruct(lane, spec, None, 0, fixture)
        stamp = lane.request("i1_iid_prediction_text")["text"]
        draw = stamp.split(";D=", 1)[1].split(";C=", 1)[0]
        key = encode(state["observation"])
        prior = openings.get(key)
        lane.reset()
        if prior and prior[0] != draw:
            specs = [prior[1], spec]
            break
        openings[key] = (draw, spec)
    else:
        raise AssertionError("No public-equivalent hidden-order pair among 64 fixture seeds")

    def public_endpoints(graph):
        return {(entry["outcome"]["kind"], entry["outcome"].get("reason"),
                 encode(entry["outcome"]["public"]), tuple(entry["first_actions"]))
                for entry in graph["graph"]["endpoints"]}

    results = []
    for spec in specs:
        lane.launch()
        reconstruct(lane, spec, None, 0, fixture)
        graphs = search(lane, "k0", settings), search(lane, "k0", settings, oracle=True)
        assert graphs[0]["counts"]["random_types"]["unknown_draw"]
        assert not graphs[1]["counts"]["random_types"]
        results.append(graphs)
        lane.reset()
    (fair_a, oracle_a), (fair_b, oracle_b) = results
    assert fair_a["graph"]["first_actions"] == fair_b["graph"]["first_actions"]
    assert public_endpoints(fair_a) == public_endpoints(fair_b)
    assert public_endpoints(oracle_a) != public_endpoints(oracle_b)
    return dict(seeds=[spec["seed"] for spec in specs], fair=public_endpoints(fair_a) == public_endpoints(fair_b),
                oracle_different=public_endpoints(oracle_a) != public_endpoints(oracle_b))


def main(output, build):
    output.mkdir(parents=True, exist_ok=False)
    host = Host(output, build)
    lane = host.lane()
    cfg = config()
    strike, defend = ("STRIKE_IRONCLAD", 0), ("DEFEND_IRONCLAD", 0)
    cases = {
        "duplicates_3_energy_5_cards": recipe([strike, strike, strike, defend, defend]),
        "upgrades": recipe([strike, ("STRIKE_IRONCLAD", 1), strike, defend, defend]),
        "early_victory": recipe([("BASH", 1), ("BLUDGEON", 1), strike, defend, defend]),
        "public_choices": recipe([("ARMAMENTS", 0), ("TRUE_GRIT", 1), strike, defend, defend]),
        "draw_and_energy": recipe([("POMMEL_STRIKE", 1), ("SHRUG_IT_OFF", 0), ("BLOODLETTING", 0),
                                   ("OFFERING", 0), strike, defend, defend], hp=15),
        "random_choice": recipe([("TRUE_GRIT", 0), strike, strike, defend, defend]),
        "potion": recipe([strike, strike, strike, defend, defend], potions=["FLEX_POTION"]),
        "enemy_death": recipe([strike, defend, defend, defend, defend], hp=1,
                              encounter="FUZZY_WURM_CRAWLER_WEAK"),
        "four_energy_six_cards": recipe([strike, defend, ("BASH", 0), ("IRON_WAVE", 0),
                                         ("POMMEL_STRIKE", 0), ("BLOODLETTING", 0)],
                                        relics=["LANTERN", "BAG_OF_PREPARATION"]),
        "relic_counters_zero": recipe([strike, strike, strike, defend, defend],
                                      relics=["NUNCHAKU", "TUNING_FORK"]),
        "relic_counters_nine": recipe([strike, strike, strike, defend, defend],
                                      relics=["NUNCHAKU", "TUNING_FORK"]),
        "next_turn_without_draw": recipe([("INFLAME", 0)]),
        "frog_knight_threshold": recipe([("BLUDGEON", 1), strike, defend, defend, defend],
                                       schema=3, act=3, act_variant="GLORY", encounter="FROG_KNIGHT_NORMAL"),
    }
    results = {}
    with (output / "checks.jsonl").open("xb") as stream:
        try:
            lane.launch()
            results["historical_smoke"] = sample_history(lane, cfg)
            stream.write(encode({"historical_smoke": results["historical_smoke"]}) + b"\n")
            stream.flush()
            for name, spec in cases.items():
                lane.launch()
                fixture = {"early_victory": {"enemy_hp": 4}, "four_energy_six_cards": {},
                           "relic_counters_zero": {"relic_count": 0},
                           "relic_counters_nine": {"relic_count": 9}}.get(name)
                state, _ = reconstruct(lane, spec, None, 0, fixture)
                settings = cfg["tree_settings"] | dict(wall_ms=12000)
                graphs = {mode: search(lane, mode, settings, verify=True, potions=name == "potion")
                          for mode in ("tree", "k0", "k1")}
                stream.write(encode(dict(name=name, spec=spec, graphs=graphs)) + b"\n")
                stream.flush()
                compare(graphs)
                assert lane.request("i1_sv1_state")["episode"] == state
                k1 = graphs["k1"]
                counts = k1["counts"]
                summary = dict(counts=counts, k0_nodes=graphs["k0"]["counts"]["state_nodes"],
                               k0_transitions=graphs["k0"]["counts"]["transitions"],
                               identity_rule=k1["identity_rule"])
                if name == "duplicates_3_energy_5_cards":
                    assert k1["identity_rule"] and counts["cache_hits"] > 0
                    budget = search(lane, "k1", settings | {"transitions": 2})
                    assert budget["stop"] == "transition_cap" and budget["counts"]["endpoints"]["budget"] > 0
                    summary["budget"] = budget["counts"]
                if name == "public_choices":
                    assert counts["choices"] > 0
                if name == "draw_and_energy":
                    assert counts["random_types"]["unknown_draw"] > 0
                if name == "random_choice":
                    assert counts["random_types"]["card_selection"] > 0
                if name == "potion":
                    assert any(action["kind"] == "use_potion" for action in k1["graph"]["first_actions"])
                if name == "early_victory":
                    assert counts["endpoints"]["victory"] > 0
                if name == "next_turn_without_draw":
                    assert counts["endpoints"]["next_turn_b"] > 0
                if name == "enemy_death":
                    assert counts["endpoints"]["death"] > 0
                if name == "four_energy_six_cards":
                    assert state["observation"]["energy"] == 4 and len(state["observation"]["hand"]) == 6
                results[name] = summary
                print(name, summary, flush=True)
                lane.reset()
            assert results["relic_counters_nine"]["counts"]["max_depth"] > results["relic_counters_zero"]["counts"]["max_depth"]
            results["hidden_worlds"] = hidden_worlds(lane, settings)
            stream.write(encode({"hidden_worlds": results["hidden_worlds"]}) + b"\n")
        finally:
            host.close()
    (output / "summary.json").write_bytes(encode(results) + b"\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--build", type=Path, required=True)
    args = parser.parse_args()
    main(args.output.resolve(), args.build.resolve())
