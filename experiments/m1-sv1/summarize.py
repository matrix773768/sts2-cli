"""Summarize a durable SV1 result ledger without printing private hidden state."""
import argparse
from collections import Counter
from contextlib import closing
import json
import math
from pathlib import Path

from campaign import open_source, payload
from checks import outcomes


def percentiles(values):
    items = sorted(values)
    if not items:
        return None
    result = {}
    for name, fraction in (("p50", .5), ("p90", .9), ("p95", .95), ("p99", .99), ("max", 1)):
        offset = (len(items) - 1) * fraction
        lower, upper = math.floor(offset), math.ceil(offset)
        result[name] = round(items[lower] + (items[upper] - items[lower]) * (offset - lower), 4)
    return result


def modes(records, mode):
    return [(record, record["graphs"][mode]) for record in records if mode in record["graphs"]]


def finished(graph):
    return not graph.get("stop") and not any(graph["counts"]["endpoints"].get(key, 0)
                                             for key in ("unsupported", "error", "budget"))


def before_a(item):
    return not any(action["kind"] == "settle_turn" for action in item["witness"])


def describe(records, mode, wall):
    pairs = modes(records, mode)
    graphs = [graph for _, graph in pairs]
    result = dict(roots=len(graphs), complete_region=0, complete_to_a=0, complete_to_b=0,
                  random_roots=0, random_before_a_roots=0, unsupported_roots=0, error_roots=0,
                  endpoints=Counter(), random_types=Counter(), stops=Counter(), mechanics=Counter())
    for record, graph in pairs:
        counts = graph["counts"]
        boundary = counts["endpoints"]
        result["endpoints"].update(boundary)
        result["random_types"].update(counts["random_types"])
        if graph.get("stop"):
            result["stops"][graph["stop"]] += 1
        result["random_roots"] += bool(boundary.get("random"))
        result["random_before_a_roots"] += graph["random_before_a"]
        result["unsupported_roots"] += bool(boundary.get("unsupported"))
        result["error_roots"] += bool(boundary.get("error"))
        result["complete_region"] += finished(graph)
        result["complete_to_a"] += finished(graph) and not graph["random_before_a"]
        result["complete_to_b"] += finished(graph) and not boundary.get("random")
        result["mechanics"]["choice_roots"] += bool(counts["choices"])
        result["mechanics"]["victory_roots"] += bool(boundary.get("victory"))
        result["mechanics"]["death_roots"] += bool(boundary.get("death"))
        result["mechanics"]["next_turn_roots"] += bool(boundary.get("next_turn_b"))
        result["mechanics"]["identity_rule_roots"] += graph["identity_rule"]
        result["mechanics"]["cache_hit_roots"] += bool(counts["cache_hits"])
    keys = ("state_nodes", "vertices", "transitions", "forks", "restore_calls", "cache_hits", "edges",
            "distinct_endpoints", "first_actions", "choices", "max_moves", "max_depth")
    result["counts"] = {key: percentiles(graph["counts"][key] for graph in graphs) for key in keys}
    result["memory"] = {key: percentiles(graph[key] / (1024 * 1024) for graph in graphs)
                        for key in ("peak_managed_sample_bytes", "peak_working_set_bytes")}
    timers = ("search_ms", "menu_ms", "transition_ms", "fork_ms", "restore_ms", "key_ms", "cache_ms", "result_ms")
    result["timing_ms"] = ({key: percentiles(graph["timing"][key] for graph in graphs) for key in timers} |
                           {key: percentiles(graph[key] for graph in graphs) for key in ("rpc_ms", "wire_overhead_ms")})
    result["sum_transitions"] = sum(graph["counts"]["transitions"] for graph in graphs)
    result["sum_forks"] = sum(graph["counts"]["forks"] for graph in graphs)
    result["sum_search_s"] = sum(graph["timing"]["search_ms"] / 1000 for graph in graphs)
    result["sum_fork_s"] = sum(graph["timing"]["fork_ms"] / 1000 for graph in graphs)
    result["sum_key_s"] = sum(graph["timing"]["key_ms"] / 1000 for graph in graphs)
    result["transitions_per_host_search_second"] = (result["sum_transitions"] / result["sum_search_s"]
                                                   if result["sum_search_s"] else 0)
    result["transitions_per_campaign_second"] = result["sum_transitions"] / wall if wall else 0
    result["top"] = [
        dict(root={k: record["root"][k] for k in ("index", "source", "encounter", "cards", "energy", "turn")},
             counts=graph["counts"], stop=graph.get("stop"))
        for record, graph in sorted(pairs, key=lambda row: row[1]["counts"]["transitions"], reverse=True)[:12]
    ]
    return result


def summarize(path):
    combinations = (("k0", "k1"), ("tree", "k0"), ("tree", "k1"))
    comparisons = {pair: dict(reached_both=0, complete_both=0, mismatches=[], reductions=[])
                   for pair in combinations}
    records = []
    with closing(open_source(path)) as db:
        for expected, raw in db.execute("SELECT sha,payload FROM results ORDER BY idx"):
            record = payload(raw, expected)
            graphs = record["graphs"]
            for pair, comparison in comparisons.items():
                if not all(mode in graphs for mode in pair):
                    continue
                comparison["reached_both"] += 1
                a, b = (graphs[mode] for mode in pair)
                if finished(a) and finished(b):
                    comparison["complete_both"] += 1
                    comparison["reductions"].append(1 - b["counts"]["state_nodes"] / a["counts"]["state_nodes"])
                    if outcomes(a) != outcomes(b):
                        comparison["mismatches"].append(record["root"]["index"])
            for graph in graphs.values():
                graph["random_before_a"] = any(item["outcome"]["kind"] == "random" and before_a(item)
                                               for item in graph.pop("graph")["endpoints"])
            records.append(record)
        wall = db.execute("SELECT sum(wall_s) FROM sessions").fetchone()[0] or 0
        identity, contract = db.execute("SELECT sha,json FROM contract").fetchone()
    result = dict(contract_sha256=identity, contract=json.loads(contract), attempts=len(records), wall_s=wall,
                  attempted_roots_per_s=len(records) / wall if wall else 0,
                  status=Counter(record["status"] for record in records),
                  source=Counter(record["root"]["source"] for record in records),
                  act=Counter(record["root"]["act"] for record in records),
                  room=Counter(record["root"]["room"] for record in records),
                  phases=Counter(record["root"]["phase"] for record in records),
                  positions=Counter(record["root"]["start"] for record in records),
                  encounters=len({record["root"]["encounter"] for record in records}),
                  sample={key: percentiles(record["root"][key] for record in records)
                          for key in ("turn", "energy", "hand", "hp", "actions")})
    result["wall_ms"] = percentiles(record["wall_ms"] for record in records)
    result["rebuild_ms"] = {key: percentiles(record["rebuild"][key] for record in records if "rebuild" in record)
                            for key in ("root_ms", "prefix_ms")}
    result["errors"] = Counter(record["error"].split("\n")[0] for record in records if "error" in record)
    result["modes"] = {key: describe(records, key, wall) for key in ("k0", "k1", "tree")}
    result["comparisons"] = {}
    for (left, right), comparison in comparisons.items():
        comparison["node_reductions"] = percentiles(comparison.pop("reductions"))
        result["comparisons"][f"{left}_{right}"] = comparison
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    text = json.dumps(summarize(args.ledger), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(text)
    else:
        print(text)
