"""Validate two Q5 matrices and retain compact, reproducible route evidence."""
import argparse
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def verify(data):
    parent, search, replay = (data[key] for key in ("parent", "search", "validation"))
    assert parent["matched"] == 18 and search["publicParentEqual"] and search["parentUnchanged"]
    assert len(search["candidates"]) == 8 and len(replay) == 7
    candidates = {row["name"]: row for row in search["candidates"]}
    assert candidates["block_then_escape"]["stop"] == "required_action_unavailable"
    assert all(row["selected"] == "escape_first" for row in search["selection"])
    for name, outcome in replay.items():
        suffix = candidates[name]["decisions"]
        assert outcome["matched"] == outcome["planned"] == 18 + len(suffix), name
        for checks in outcome["publicChecks"].values():
            assert len(checks) == len(suffix) and all(row["equal"] for row in checks), name
        assert [step["actual"] for step in outcome["publicChecks"]["successors"]] == [
            item["successorHash"] for item in suffix
        ]
        assert (outcome["root"], outcome["live"]) == (parent["root"], parent["live"])
        assert outcome["nativeOutcome"]["potions"] == []
        assert outcome["nativeOutcome"]["finalHp"] == candidates[name]["endpoint"]["hp"]
        assert outcome["nativeOutcome"]["finalEnemyHp"] == candidates[name]["endpoint"]["enemyHp"]
        if candidates[name]["stop"] == "death":
            assert outcome["nativeLifecycleSemantic"] and outcome["nativeStatus"] == "death"
            assert [entry["cause"] for entry in outcome["nativeRisk"]] == ["SANDPIT_POWER"]
        else:
            assert outcome["nativeStatus"] == "limit" and not outcome["nativeRisk"]
    assert [step["input"]["selected"]["id"]
            for step in candidates["attack_then_escape"]["decisions"][:-1]] == [
                "MOMENTUM_STRIKE", "FRANTIC_ESCAPE", "COMPACT",
            ]


def compact(data, folder):
    for row in data["search"]["candidates"]:
        for item in row["decisions"]:
            public = item.pop("public")
            item["sandpitBefore"] = public["sandpit"]
            item["energyBefore"] = public["energy"]
    data["search"].pop("native")
    for name, outcome in data["validation"].items():
        native = read(folder / name / "fast.json")
        outcome["permanentResourcesUnchanged"] = native["initialResources"] == native["finalResources"]
        assert outcome["permanentResourcesUnchanged"], name
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    matrices = [read(folder / "results.json") for folder in (args.first, args.second)]
    for matrix in matrices:
        verify(matrix)
    a, b = (matrix["search"] for matrix in matrices)
    for key in ("parentHash", "initial", "selection", "visitedDistinctSuccessors"):
        assert a[key] == b[key], key
    for first, second in zip(a["candidates"], b["candidates"], strict=True):
        for key in ("name", "decisions", "endpoint", "stop", "transitions"):
            assert first[key] == second[key], key
    args.output.write_text(json.dumps({"matrices": [compact(matrix, folder)
                                                   for matrix, folder in zip(matrices, (args.first, args.second), strict=True)]},
                                      indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
