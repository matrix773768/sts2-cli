"""Check the two Q6 matrices and derive transition overlap and native evidence."""
import argparse
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest_set(run):
    return {step["successorHash"] for route in run["routes"] for step in route["decisions"]}


def verify(case, data):
    parent, search, validation = (data[key] for key in ("parent", "search", "validation"))
    assert parent["matched"] == (18 if case == "boss" else 8)
    assert search["status"] == "pass" and search["parentUnchanged"] and search["initial"] == search["native"]
    assert len(search["audited"]) == 7 and len(search["samples"]) == 35
    lookup = {(arm["arm"], arm["cap"]): arm for arm in search["audited"]}
    for arm in search["audited"]:
        assert arm["transitions"] <= arm["cap"]
        assert sum(route["transitions"] for route in arm["routes"]) == arm["transitions"]
        assert arm["distinctSuccessors"] == len(digest_set(arm))
    for sample in search["samples"]:
        ref = lookup[sample["arm"], sample["cap"]]
        assert sample["transitions"] <= sample["cap"]
        assert sample["transitions"] == ref["transitions"] and sample["selected"] == ref["selected"]
    assert validation["C"] == {"sameRouteAs": "B"}
    for label, result in validation.items():
        if "sameRouteAs" in result:
            continue
        assert result["matched"] == result["planned"] and result["permanentResourcesUnchanged"], label
        assert (result["root"], result["live"]) == (parent["root"], parent["live"])
        count = result["planned"] - parent["matched"]
        for checks in result["publicChecks"].values():
            assert len(checks) == count and all(check["equal"] for check in checks), label
        if label == "B":
            assert result["nativeStatus"] == "limit" and not result["nativeRisk"]
        else:
            assert result["nativeStatus"] == "death" and result["nativeLifecycleSemantic"]
            expected = "SANDPIT_POWER" if case == "boss" else "THE_GAMBIT_POWER"
            assert [event["cause"] for event in result["nativeRisk"]] == [expected], label
    assert lookup["B", 16]["selected"] == (None if case == "boss" else 0)
    assert lookup["C", 16]["selected"] == (0 if case == "boss" else 1)
    return lookup


def compact(data, lookups):
    for case, root in data.items():
        search = root["search"]
        search.pop("native")
        search["overlap"] = []
        for cap in (16, 32, 64):
            b, c = (digest_set(lookups[case][arm, cap]) for arm in "BC")
            search["overlap"].append({"cap": cap, "both": len(b & c), "union": len(b | c)})
        for arm in search["audited"]:
            for route in arm["routes"]:
                for step in route["decisions"]:
                    public = step.pop("public")
                    step.update(sandpitBefore=public["sandpit"], hpBefore=public["hp"],
                                energyBefore=public["energy"], blockBefore=public["menu"]["block"],
                                incomingBefore=sum(enemy["incoming"] for enemy in public["menu"]["enemies"]),
                                gambitBefore=[power for power in public["powers"] if power.startswith("THE_GAMBIT_POWER:")])
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    matrices = [read(folder / "results.json") for folder in (args.first, args.second)]
    lookups = [{case: verify(case, data) for case, data in matrix.items()} for matrix in matrices]
    for case in ("boss", "regent"):
        a, b = (matrix[case]["search"] for matrix in matrices)
        for key in ("initial", "parentHash", "status"):
            assert a[key] == b[key], (case, key)
        for first, second in zip(a["audited"], b["audited"], strict=True):
            for key in ("arm", "cap", "transitions", "distinctSuccessors", "selected"):
                assert first[key] == second[key], (case, key)
            for left, right in zip(first["routes"], second["routes"], strict=True):
                for key in ("first", "decisions", "endpoint", "stop", "powers", "enemyPowers"):
                    assert left[key] == right[key], (case, key)
    first, second = (compact(matrix, lookup) for matrix, lookup in zip(matrices, lookups, strict=True))
    for row in second.values():
        row["search"].pop("audited")  # Identical decisions and endpoints were checked above.
    payload = {"matrices": [first, second]}
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
