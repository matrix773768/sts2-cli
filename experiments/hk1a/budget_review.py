"""Summarize cumulative native-verified routes for manual budget review."""
from math import ceil
from statistics import mean, median
from collections import Counter


def distribution(values):
    values = sorted(values)
    if not values:
        return {"count": 0}
    return dict(count=len(values), mean=mean(values), median=median(values),
                p90=values[ceil(.9 * len(values)) - 1], maximum=values[-1])


def review(rows, tiers, *, include_strata=True):
    cumulative = [
        {row["world"]["id"]: row["tiers"][i]["incumbent"]["net"]
         for row in rows if row["tiers"][i]["incumbent"]}
        for i in range(len(tiers))
    ]
    final = cumulative[-1]
    reports = []
    previous = {}
    for i, (tier, wins) in enumerate(zip(tiers, cumulative, strict=True)):
        common = sorted(previous.keys() & wins.keys())
        remaining = {key: wins[key] - final[key] for key in sorted(wins)}
        attempts = [row["tiers"][i] for row in rows]
        reports.append(dict(
            budget_ms=tier, verified_wins=len(wins), coverage=len(wins) / len(rows) if rows else None,
            new_wins=sorted(wins.keys() - previous.keys()),
            common_previous=dict(previous_net=distribution(previous[k] for k in common),
                                 current_net=distribution(wins[k] for k in common)),
            improvement=distribution(previous[k] - wins[k] for k in common),
            remaining_to_highest=distribution(remaining.values()),
            large_remaining={key: gain for key, gain in remaining.items() if gain >= 5},
            search_seconds=distribution(t["search_seconds"] for t in attempts if "search_seconds" in t),
            end_to_end_seconds=distribution(t["end_to_end_seconds"] for t in attempts
                                            if "end_to_end_seconds" in t),
            endings=dict(Counter(t.get("boundary") or "unavailable" for t in attempts)),
            native_routes=sum(t["status"] == "native_win" for t in attempts),
            turn_differences=sum(t.get("prediction_diagnostics", {}).get("turn_differences", 0) for t in attempts),
            terminal_differences=sum(any(value is False for field, value in
                                         t.get("prediction_diagnostics", {}).get("terminal", {}).items()
                                         if field in ("hpMatches", "maxHpMatches")) for t in attempts),
            expanded=distribution(t["search"]["totalExpanded"] for t in attempts if "search" in t),
            transitions=distribution(t["search"]["totalTransitions"] for t in attempts if "search" in t),
        ))
        previous = wins
    chosen = next((i for i, wins in enumerate(cumulative)
                   if final and wins.keys() == final.keys()
                   and sum(wins.values()) - sum(final.values()) <= 2 * len(final)), None)
    tail = reports[-1]
    estimate = None
    if chosen is not None and all(t["end_to_end_seconds"]["count"] for t in reports[:chosen+1]):
        estimate = 192 * (mean(r["legacy_init_seconds"] for r in rows)
                          + sum(t["end_to_end_seconds"]["mean"] for t in reports[:chosen+1]))
    strata = {}
    if include_strata:
        for name, key in (("HP", lambda w: w["spec"]["max_hp"]), ("来源", lambda w: w["source"]),
                          ("遭遇", lambda w: w["spec"]["encounter"])):
            groups = {}
            for row in rows:
                groups.setdefault(str(key(row["world"])), []).append(row)
            strata[name] = {label: review(group, tiers, include_strata=False)["tiers"]
                            for label, group in sorted(groups.items())}
    return dict(tiers=reports, recommended_index=chosen,
                recommendation_tail=reports[chosen]["large_remaining"] if chosen is not None else {},
                estimated_formal_seconds=estimate, strata=strata,
                world_best={w["id"]: dict(source=w["source"], max_hp=w["spec"]["max_hp"],
                                           encounter=w["spec"]["encounter"],
                                           net_by_tier=[wins.get(w["id"]) for wins in cumulative])
                            for w in sorted((r["world"] for r in rows), key=lambda w: w["id"])}
                if include_strata else {},
                consider_30000_ms=(tuple(tiers) == (100, 500, 2000, 10000) and bool(tail["new_wins"] or
                                   tail["improvement"].get("maximum", 0) >= 5)),
                legacy_init_seconds=distribution(row["legacy_init_seconds"] for row in rows),
                world_end_to_end_seconds=distribution(row["world_end_to_end_seconds"] for row in rows
                                                      if "world_end_to_end_seconds" in row))


if __name__ == "__main__":
    import argparse
    from contextlib import closing
    import json
    from pathlib import Path
    import sqlite3

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    args = parser.parse_args()
    uri = args.ledger.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as ledger:
        rows = [json.loads(raw) for raw, in ledger.execute("SELECT payload FROM results ORDER BY id")]
    if not rows:
        raise SystemExit("No committed results")
    tiers = [t["budget_ms"] for t in rows[0]["tiers"]]
    print(json.dumps(review(rows, tiers), ensure_ascii=True, indent=2))
