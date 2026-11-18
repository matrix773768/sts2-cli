"""Validate two independent E2 matrices and extract their portable evidence."""
import argparse
import hashlib
import json
from pathlib import Path


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(state):
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


def case(folder):
    metrics = load(folder / "measurement.json")
    terminal = load(folder / "terminal.json")
    predicted = terminal.pop("predicted")
    phases = [terminal.pop("lastBefore"), *terminal["phases"]]
    for phase in phases:
        state = phase.pop("state")
        phase["rawStateSha256"] = digest(state)
        phase["differentFields"] = [
            [key for key in shadow if shadow[key] != native[key]]
            for shadow, native in zip(predicted, state, strict=True)
        ]
        phase["enemyHp"] = [item["enemyHp"] for item in state]
        phase["rngCounters"] = state[0]["rngCounters"]
        phase["turnHistory"] = state[0]["exactContinuationState"].split(";Y=", 1)[1].split(";O=", 1)[0]
        phase["deckSha256"] = digest(phase.pop("deck"))
    terminal["phases"] = phases
    terminal["predictionSha256"] = digest(predicted)
    terminal["predictedEnemyHp"] = [item["enemyHp"] for item in predicted]
    terminal["predictedRngCounters"] = predicted[0]["rngCounters"]
    terminal["predictedTurnHistory"] = predicted[0]["exactContinuationState"].split(";Y=", 1)[1].split(";O=", 1)[0]
    audit = metrics["audit"]
    if diff := audit["_difference"]:
        fields = [item["field"] for item in diff.get("differences", [])]
        audit["_difference"] = {"step": diff["step"], "fields": fields}
    metrics["terminal"] = terminal
    return metrics


def verify(matrix):
    for letter, matched in zip("ABCDE", (18, 20, 43, 19, 19)):
        row = matrix[letter]
        terminal = row["terminal"]
        assert row["audit"]["matched"] == matched, letter
        assert terminal["semantic"] == (letter in "BCD"), letter
        assert terminal["rawTerminalEqual"] is (None if letter == "E" else False), letter
        if letter in "BCD":
            assert terminal["alignment"] == "last_player_window"
        if letter in "DE":
            branch = terminal["branch"]
            reference = matrix["C"]["audit"]["benchmark"]["branch"]["first"]
            assert branch["lifecycleNativeAlternative"]
            assert branch["strictNativeAlternative"] == (letter == "E")
            assert branch["first"]["digest"] == branch["repeated"]["digest"] != branch["alternate"]["digest"]
            assert branch["first"]["digest"] == reference["digest"]
            assert all(branch[key]["boundary"] == "None" and not branch[key]["risk"]
                       for key in ("first", "alternate", "repeated"))
    assert len({(matrix[key]["root"], matrix[key]["live"]) for key in "CDE"}) == 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    matrices = [{letter: case(folder / letter) for letter in "ABCDE"} for folder in (args.first, args.second)]
    for matrix in matrices:
        verify(matrix)
    for a, b in zip(matrices[0].values(), matrices[1].values(), strict=True):
        for key in ("root", "live", "nativeOutcome", "nativeChoices"):
            assert a[key] == b[key], key
        for key in ("phases", "predictionSha256", "alignment", "semantic"):
            assert a["terminal"][key] == b["terminal"][key], key
        if a["terminal"]["branch"]:
            for key in ("first", "alternate", "repeated"):
                assert a["terminal"]["branch"][key]["digest"] == b["terminal"]["branch"][key]["digest"], key
    args.output.write_text(json.dumps({"matrices": matrices}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
