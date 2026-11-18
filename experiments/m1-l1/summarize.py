"""Summarize fixed-prefix Teacher witnesses without labeling missing continuations."""
import argparse
from collections import Counter
from itertools import combinations
import json
from pathlib import Path

from statistics import median


def quality(row):
    q = row["quality"]
    return (
        q["deathSaveUseCount"],
        q["outstandingStolenResource"],
        q["strategicHpDeficit"] + q["potionStrategicCost"],
        -q["growthHpCredit"],
        -q["growthRewardCount"],
        q["projectedBattleHpLost"],
        q["combatEndedTurn"],
        q["projectedBattlePotionCount"],
    )


def eligible(row):
    return (
        row["outcome"] == "win" and row["matched"] and row["replayMatched"]
        and row["boundaryReason"] == "None"
        and not row["risk"] and not row["hasPredictionRisk"]
        and row["quality"]["combatEndedTurn"] is not None
    )


def manual(row):
    return 2 * row["playerHp"] - row["enemyHp"] + row["block"] + row["energy"]


def compare(delta):
    return "correct" if delta > 0 else "inverted" if delta < 0 else "tie"


def summarize(folder):
    evidence = json.loads((folder / "candidates.json").read_text(encoding="utf-8"))
    harness = json.loads((folder / "harness-result.json").read_text(encoding="utf-8"))
    if evidence["scope"] != "offline-teacher" or harness["reachedMilestone"] != "M2":
        raise ValueError(f"Incomplete Teacher run at {folder}")
    rows = evidence["rows"]
    pairs = []
    ties = 0
    for left, right in combinations(rows, 2):
        if left["parentStateKey"] != right["parentStateKey"] or not all(map(eligible, (left, right))):
            continue
        if quality(left) == quality(right):
            ties += 1
            continue
        winner, loser = sorted((left, right), key=quality)
        winner_ranks = {p["boundaryId"]: p["retention"]["rawRank"] for p in winner["pool"]}
        loser_ranks = {p["boundaryId"]: p["retention"]["rawRank"] for p in loser["pool"]}
        shared = sorted(winner_ranks.keys() & loser_ranks.keys())
        pairs.append({
            "better": rows.index(winner), "worse": rows.index(loser),
            "generatedScore": compare(winner["score"] - loser["score"]),
            "manualScore": compare(manual(winner) - manual(loser)),
            "sharedBeamRank": {
                boundary: compare(loser_ranks[boundary] - winner_ranks[boundary])
                for boundary in shared
            },
        })
    features = ("outcome", "boundaryReason", "matched", "replayMatched", "risk",
                "hasPredictionRisk", "failure", "score", "playerHp", "enemyHp", "energy", "block",
                "traits", "shufflesCrossed", "endShuffles", "expandedNodes", "transitionCount")
    return {
        "root": harness["label"],
        "rngGroup": harness["scenario"]["Seed"],
        "scope": evidence["scope"],
        "profile": evidence["budget"]["profile"],
        "discoveryNodes": evidence["discoveryNodes"],
        "generatedEvents": evidence["generatedEvents"],
        "counts": dict(Counter(row["outcome"] for row in rows)),
        "eligibleWins": sum(map(eligible, rows)),
        "tiedPairs": ties,
        "strictPairs": pairs,
        "solveMillisecondsMedian": round(median(row["milliseconds"] for row in rows), 1),
        "peakWorkingSetMiB": round(evidence["peakWorkingSet"] / 2**20, 1),
        "rows": [
            {
                "action": {key: row["action"][key] for key in
                           ("kind", "cardId", "cardOccurrence", "potionId", "targetCombatId", "choice")},
                **{key: row[key] for key in features},
                "quality": list(quality(row)) if eligible(row) else None,
                "retention": [
                    {key: item["retention"][key] for key in
                     ("rawRank", "requiredIndex", "routingIndex", "selectedIndex")}
                    | {"boundary": item["boundaryId"], "reason": item["reason"]}
                    for item in row["pool"]
                ],
                "milliseconds": round(row["milliseconds"], 1),
            }
            for row in rows
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", type=Path, nargs="+")
    args = parser.parse_args()
    print(json.dumps([summarize(folder) for folder in args.roots], indent=2))
