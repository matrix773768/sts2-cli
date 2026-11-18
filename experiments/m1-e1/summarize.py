"""Extract versionable measurements and check reproducibility across two matrices."""
import argparse
from difflib import SequenceMatcher
import json
from pathlib import Path

def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def summarize(folder):
    data = load(folder / "measurement.json")
    native = load(folder / "fast.json")
    audit = data["audit"]
    difference = audit["_difference"]
    if difference and "differences" in difference:
        for item in difference["differences"]:
            pred, actual = item.pop("predicted"), item.pop("actual")
            if isinstance(pred, str) and isinstance(actual, str):
                item["edits"] = [
                    {"predicted": pred[a:b], "actual": actual[c:d], "context": pred[max(0, a-18):a]}
                    for tag, a, b, c, d in SequenceMatcher(None, pred, actual, autojunk=False).get_opcodes()
                    if tag != "equal"
                ]
            else:
                item.update(predicted=pred, actual=actual)
    audit["firstDifferenceAction"] = (
        native["steps"][difference["step"] - 1]["selected"]
        if difference and 0 < difference["step"] <= len(native["steps"]) else None
    )
    data.update(nativeBattleMs=native["battleMs"], nativeEndTurn=native["endTurn"],
                nativeObservationMs=sum(step["observeMs"] for step in native["steps"]))
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    matrices = [
        {letter: summarize(run / letter) for letter in "ABC"}
        for run in (args.first, args.second)
    ]
    for letter in "ABC":
        a, b = (matrix[letter] for matrix in matrices)
        for key in ("root", "live", "nativeOutcome", "nativeEndTurn", "nativeChoices"):
            assert a[key] == b[key], (letter, key)
        for key in ("status", "matched", "_difference", "firstDifferenceAction"):
            assert a["audit"][key] == b["audit"][key], (letter, key)
        if letter == "C":
            branches = [run["audit"]["benchmark"]["branch"] for run in (a, b)]
            for branch in branches:
                assert all(branch[key] for key in ("parentUnchanged", "repeatEqual", "distinct"))
                assert all(branch[key]["boundary"] == "None" and not branch[key]["risk"]
                           for key in ("first", "alternative", "repeated"))
            for key in ("first", "alternative", "repeated"):
                assert branches[0][key]["digest"] == branches[1][key]["digest"]
    args.output.write_text(json.dumps({"matrices": matrices}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
