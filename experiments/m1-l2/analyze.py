"""Compare matched fixed-prefix labels across budgets and summarize cost."""
import argparse
from collections import Counter
import hashlib
from itertools import combinations
import json
from pathlib import Path
import sys

from run import HERE, load

sys.path.insert(0, str(HERE.parent / "m1-l1"))
from summarize import eligible, quality


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def action_key(action):
    presentation = {"cardTitle", "targetName", "potionTitle", "actionTitle", "relicEffects"}
    return {key: value for key, value in action.items() if key not in presentation}


def harness_evidence(folder):
    result = load(folder / "harness-result.json")
    if result["reachedMilestone"] != "M2":
        raise ValueError(f"Incomplete harness result: {folder}")
    search = result["search"]
    return (
        digest(search["rootContinuationStamp"]),
        digest(search["rootLiveStamp"]),
        load(folder / "route.json"),
    )


def paired_outcomes(rows, field="quality"):
    pairs = {}
    for a, b in combinations(sorted(rows), 2):
        left, right = rows[a], rows[b]
        if left["parent"] != right["parent"] or left[field] is None or right[field] is None:
            continue
        lq, rq = left[field], right[field]
        pairs[(a, b)] = (lq < rq) - (lq > rq)
    return pairs


def prefix(folder):
    result = load(folder / "measurement.json")
    if result["processStatus"] != 0:
        return result, {}
    root, live, control_route = harness_evidence(folder)
    data = load(folder / "candidates.json")
    assert data["scope"] == "offline-teacher"
    rows = {}
    for item in data["rows"]:
        action = action_key(item["action"])
        parent = digest(item["parentStateKey"])
        state = digest(item["stateKey"])
        key = digest([parent, action, state])[:16]
        assert key not in rows
        witness = item["witness"]
        is_eligible = eligible(item)
        witnessed = eligible(item | {"boundaryReason": "None"})
        if witnessed:
            assert witness and action_key(witness[0]) == action
        rows[key] = {
            "action": action, "parent": parent, "state": state,
            "postState": {k: item[k] for k in ("playerHp", "enemyHp", "energy", "block", "shufflesCrossed")},
            "traits": item["traits"], "score": item["score"], "replayMatched": item["replayMatched"],
            "outcome": item["outcome"], "boundary": item["boundaryReason"],
            "failure": item["failure"], "risk": item["risk"],
            "quality": quality(item) if is_eligible else None,
            "witnessQuality": quality(item) if witnessed else None,
            "witness": digest([action_key(a) for a in witness]) if witness else None,
            "retention": {entry["boundaryId"]: {k: entry["retention"][k] for k in
                          ("rawRank", "requiredIndex", "routingIndex", "selectedIndex")}
                          for entry in item["pool"]},
            "expanded": item["expandedNodes"], "transitions": item["transitionCount"],
            "seconds": round(item["milliseconds"] / 1000, 4),
        }
    strict = []
    pair_labels = paired_outcomes(rows)
    for (a, b), sign in pair_labels.items():
        if not sign:
            continue
        better, worse = (a, b) if sign > 0 else (b, a)
        winner, loser = rows[better], rows[worse]
        shared = winner["retention"].keys() & loser["retention"].keys()
        strict.append({"better": better, "worse": worse,
                       "scoreReversal": winner["score"] < loser["score"],
                       "sharedBoundaries": sorted(shared),
                       "beamReversal": any(winner["retention"][i]["rawRank"] >
                                           loser["retention"][i]["rawRank"] for i in shared)})
    control_hash = digest([action_key(a) for a in control_route])
    control_prefix = [key for key, row in rows.items()
                      if control_route and row["action"] == action_key(control_route[0])]
    control_quality = quality(result) if result["won"] else None
    schedule = {
        key: {
            "sameWitness": rows[key]["witness"] == control_hash,
            "sameQuality": rows[key]["quality"] == control_quality
            if rows[key]["quality"] is not None and control_quality is not None else None,
        }
        for key in control_prefix
    }
    discovery = data["discovery"]
    return {
        "nodes": result["nodes"], "rootStamp": root, "liveStamp": live,
        "liveUnchanged": True, "processSeconds": result["processSeconds"],
        "peakMiB": result["peakMiB"], "discovery": discovery,
        "counts": dict(Counter(r["outcome"] for r in rows.values())),
        "eligibleWins": sum(row["quality"] is not None for row in rows.values()),
        "verifiedWitnesses": sum(row["witnessQuality"] is not None for row in rows.values()),
        "ties": sum(sign == 0 for sign in pair_labels.values()),
        "candidateSeconds": round(sum(row["seconds"] for row in rows.values()), 3),
        "candidateExpanded": sum(row["expanded"] or 0 for row in rows.values()),
        "candidateTransitions": sum(row["transitions"] or 0 for row in rows.values()),
        "control": {k: result[k] for k in ("won", "quality", "expanded", "transitions", "boundary")}
        | {"matchedFirstAction": schedule, "witness": control_hash},
        "rows": rows, "strict": strict,
    }, pair_labels


def compare_budgets(low, high):
    shared = low.keys() & high.keys()
    return {
        "sameStrict": sum(low[key] == high[key] != 0 for key in shared),
        "flippedStrict": sum(low[key] * high[key] == -1 for key in shared),
        "strictVsTie": sum(bool(low[key]) != bool(high[key]) for key in shared),
        "sameTie": sum(low[key] == high[key] == 0 for key in shared),
        "only400Strict": sum(low[key] != 0 for key in low.keys() - high.keys()),
        "only1200Strict": sum(high[key] != 0 for key in high.keys() - low.keys()),
    }


def summarize(output):
    results = []
    for case in load(HERE / "roots.json"):
        scan = []
        for nodes in (240, 800):
            folder = output / "scan" / case / str(nodes)
            record = load(folder / "measurement.json")
            if record["processStatus"] == 0:
                record["rootStamp"], record["liveStamp"], _ = harness_evidence(folder)
            scan.append(record)
        result = {"root": case, "scope": "offline-teacher", "scan": scan}
        if any(record.get("won") for record in scan):
            samples, labels = zip(*(prefix(output / "prefix" / case / str(n)) for n in (400, 1200)))
            result["prefix"] = samples
            result["stability"] = compare_budgets(*labels)
            result["stabilityIncludingBudgetLimitedWins"] = compare_budgets(
                *(paired_outcomes(sample.get("rows", {}), "witnessQuality") for sample in samples)
            )
        observed = scan + list(result.get("prefix", ()))
        for key in ("rootStamp", "liveStamp"):
            assert len({r[key] for r in observed if r.get(key)}) <= 1, (case, key)
        results.append(result)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.output), indent=2))
