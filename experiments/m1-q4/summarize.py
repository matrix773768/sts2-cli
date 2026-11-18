"""Verify the predeclared SL branches against Q3 and repeated native runs."""
import argparse
import collections
import json
from pathlib import Path
import statistics

from benchmark import ROOTS, load

HISTORY = Path(__file__).resolve().parents[1] / "m1-q3" / "results.json"
TIMING = ("decisionMs", "choiceDecisionMs", "observeMs", "choiceObservationMs", "executeMs",
          "battleMs", "setupMs", "warmMs", "processMs", "peakMiB")
PROOF = ("root", "live", "outcome", "trajectory", "actions", "endTurn", "choiceRequests",
         "choiceChecks", "interventions", "lethalEvents", "damageToEnemies", "initialResources",
         "finalResources", "status")


def compact(data):
    groups = collections.defaultdict(list)
    for row in data:
        groups[row["case"], row["arm"]].append(row)
    assert set(groups) == {(root, arm) for root in ROOTS for arm in "ABC"}
    history = {r["case"]: r for r in load(HISTORY)["runs"] if r["policy"] == "tactical"}
    result = {}
    for (case, arm), samples in sorted(groups.items()):
        assert sorted(r["repeat"] for r in samples) == [0, 1]
        row = samples[0]
        for field in PROOF:
            assert row[field] == samples[1][field], (case, arm, field)
        assert row["status"] == "death" and row["outcome"]["finalHp"] == 0
        old = history[case]
        assert (row["root"], row["live"], row["fixtureSha"]) == (old["root"], old["live"], old["fixtureSha"])
        assert row["initialResources"] == row["finalResources"] and not row["outcome"]["potions"]
        path = row["trajectory"]
        stock = groups[case, "A"][0]["trajectory"]
        changes = [i for i, step in enumerate(path) if step["selected"] != step["stock"]]
        assert len(changes) == row["interventions"]
        start = changes[0] if changes else None
        if arm == "A":
            assert not changes
            for field in ("status", "outcome", "actions", "endTurn", "choiceRequests"):
                assert row[field] == old[field], (case, field)
            for new, previous in zip(path, old["trajectory"], strict=True):
                for field in ("turn", "selected", "before", "after", "block", "enemies"):
                    assert new[field] == previous[field], (case, field)
        else:
            assert start is not None and (len(changes) == 1 if arm == "B" else len(changes) > 1)
            assert path[:start] == stock[:start], (case, arm, start)
            for field in ("preStamp", "stock", "moves", "riskBefore"):
                assert path[start][field] == stock[start][field], (case, arm, field)
            for index in changes:
                assert path[index]["selected"] is None or path[index]["selected"] in path[index]["moves"]
        lethal = row["lethalEvents"]
        if arm in "AB":
            cause = "THE_GAMBIT_POWER" if case == ROOTS[0] else "SANDPIT_POWER"
            assert len(lethal) == 1 and lethal[0]["cause"] == cause and lethal[0]["step"] == len(path)
        else:
            assert not lethal and path[-1]["after"] == 0
        uses = [i for i, step in enumerate(path) if (step["selected"] or {}).get("id") == "FRANTIC_ESCAPE"]
        for i in uses:
            assert path[i]["riskBefore"]["sandpit"] + 1 == path[i]["riskAfter"]["sandpit"]
        trajectory = []
        for i, step in enumerate(path):
            entry = dict(step)
            if i not in changes and i not in uses and i != len(path) - 1:
                entry.pop("moves")
            trajectory.append(entry)
        result[f"{case}/{arm}"] = {
            **{k: row[k] for k in ("case", "arm", "seed", "character", "ascension", "fixtureSha",
                                  *[key for key in PROOF if key != "trajectory"])},
            "matchedPrefixActions": start if start is not None else len(path),
            "firstDivergenceStep": start + 1 if start is not None else None,
            "escapeTurns": [path[i]["turn"] for i in uses],
            "trajectory": trajectory,
            "timing": {name: [round(fn(s[name] for s in samples), 6)
                             for fn in (min, statistics.median, max)] for name in TIMING},
            "repeats": 2,
        }
    return {
        "scope": "public-observation-native-targeted-sl",
        "timingOrder": ["min", "median", "max"],
        "firstPassProcessMs": sum(row["processMs"] for row in data if row["repeat"] == 0),
        "allProcessMs": sum(row["processMs"] for row in data),
        "routes": result,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path)
    args = parser.parse_args()
    print(json.dumps(compact(load(args.raw)), indent=2))
