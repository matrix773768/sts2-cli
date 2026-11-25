"""Summarize cumulative native-verified routes for manual budget review."""
from math import ceil
from statistics import mean, median


def distribution(values):
    values = sorted(values)
    if not values:
        return {"count": 0}
    return dict(count=len(values), mean=mean(values), median=median(values),
                p90=values[ceil(.9 * len(values)) - 1], maximum=values[-1])


def review(rows, tiers):
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
        ))
        previous = wins
    chosen = next((i for i, wins in enumerate(cumulative)
                   if final and wins.keys() == final.keys()
                   and sum(wins.values()) - sum(final.values()) <= 2 * len(final)), None)
    tail = reports[-1]
    return dict(tiers=reports, recommended_index=chosen,
                recommendation_tail=reports[chosen]["large_remaining"] if chosen is not None else {},
                consider_30000_ms=(len(tiers) == 4 and bool(tail["new_wins"] or
                                   tail["improvement"].get("maximum", 0) >= 5)),
                legacy_init_seconds=distribution(row["legacy_init_seconds"] for row in rows),
                world_end_to_end_seconds=distribution(row["world_end_to_end_seconds"] for row in rows
                                                      if "world_end_to_end_seconds" in row))
