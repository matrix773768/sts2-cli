"""Check public mechanics, evidence alignment and label semantics."""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from statistics import median
import time

from dataset import PROTOCOLS, compile_dataset, query, read, write


def inspect(exports, dataset):
    inputs, labels = dataset["inputs"], dataset["labels"]
    assert len(inputs) == 35 and len(dataset["structureEvidence"]) == 13
    public = {name: row["Startup"]["h"] for name, row in inputs.items()}
    mechanics = public["core50"]
    graph = mechanics["enemyRules"][0]["rules"]
    moves = {node["MoveId"]: node for node in graph["nodes"]}
    assert moves["FIRST_ACID_GOOP"]["attacks"][0]["BaseDamage"] == 4
    assert moves["FIRST_ACID_GOOP"]["next"] == "INHALE"
    assert moves["ACID_GOOP"]["next"] == "FIRST_ACID_GOOP"
    assert moves["INHALE"]["effects"][0]["power"] == "STRENGTH_POWER"
    assert moves["INHALE"]["effects"][0]["Amount"] == 7
    assert moves["FIRST_ACID_GOOP"]["attacks"] == moves["ACID_GOOP"]["attacks"]

    finesse = next(rule for rule in mechanics["cardRules"] if rule["Entry"] == "FINESSE")
    assert [op["Op"] for op in finesse["operations"]] == ["GainBlock", "Draw"]
    assert any(rule["Entry"] == "OFFERING" and rule["knownCustomSemantics"]
               for rule in public["startup_unknown"]["cardRules"])
    assert any(power["Entry"] == "NO_DRAW_POWER" for power in public["no_draw"]["powerRules"])
    assert public["energy0"]["state"]["Energy"] != public["energy6"]["state"]["Energy"]
    zone_counts = {}
    for name, zone in (("hand1", "hand"), ("draw1", "unknown"), ("discard1", "discard")):
        state = public[name]["state"]
        identities = Counter(card["card"] for key in ("hand", "unknown", "discard") for card in state[key])
        zone_counts[name] = dict(identities)
        assert any(card["card"] == "DEFEND_IRONCLAD" for card in state[zone])
    assert zone_counts["hand1"] == zone_counts["draw1"] == zone_counts["discard1"]

    def outcome(name, arm="Startup"):
        return labels[name]["outcomes"][arm]

    assert outcome("core50")["Lower"] == outcome("core50")["Victory"] == 1
    assert outcome("core80")["Lower"] == 1 and outcome("core80")["Victory"] == 0
    same_ideal = [
        [name, outcome(name)["Lower"], outcome(name)["Upper"]]
        for name in labels if outcome(name, "IdealStartup")["Lower"] == 1 and outcome(name)["Upper"] < 1
    ]
    same_ideal_different_cashout = [
        [name, outcome(name, "Fight")["Lower"], outcome(name, "Fight")["Upper"]]
        for name in labels if outcome(name, "IdealStartup")["Victory"] == 1
        and outcome(name, "Fight")["Upper"] < 1
    ]
    assert any(row[0] == "conditioned" for row in same_ideal_different_cashout)
    direct = {name: outcome(name, "Fight")["VictoryWithoutEntry"] for name in labels
              if outcome(name, "Fight")["VictoryWithoutEntry"] > 0}
    assert direct["ordinary_direct"] == 1
    assert outcome("quick_kill", "Fight")["VictoryAfterEntry"] == 1
    assert outcome("quick_kill", "Fight")["VictoryWithPeriodActions"] == 0
    tape = labels["conditioned"]["scriptComparison"]
    assert tape["fixedTape"]["WinProbability"] == 1 / 128
    assert (tape["adaptive"]["Lower"], tape["adaptive"]["Upper"]) == (1 / 64, 1 / 64)
    assert outcome("startup_unknown")["Lower"] == 1 and len(outcome("startup_unknown")["Entries"]) == 12
    assert outcome("unsupported")["Unresolved"] == 1
    assert outcome("unsupported")["Upper"] > outcome("unsupported")["Lower"]

    contaminated = deepcopy(mechanics)
    contaminated["audit"] = {"rng": "forbidden"}
    template = deepcopy(labels["core50"]["target"])
    template["Period"][0]["FutureOutcome"] = "forbidden"
    sanitized = query(contaminated, template, labels["core50"]["budget"], "Startup")
    assert sanitized == inputs["core50"]["Startup"]
    # Contract-only cases. The live fixture export above provides the base shape.
    def diagnostic_input(turn_expiration, damage, hits):
        snapshot = deepcopy(mechanics)
        snapshot["state"]["hand"][0]["energyMods"] = [{"Amount": 0, "PackedFlags": 1 | turn_expiration}]
        first_move = snapshot["enemyRules"][0]["rules"]["nodes"][0]
        first_move["BaseDamage"], first_move["Repeats"] = damage, hits
        first_move["attacks"] = [{"BaseDamage": damage, "Repeats": hits, "Flags": 0}]
        return query(snapshot, template, labels["core50"]["budget"], "Startup")["h"]

    combat_cost = diagnostic_input(0, 12, 1)
    turn_cost = diagnostic_input(2, 12, 1)
    multi_hit = diagnostic_input(0, 6, 2)
    assert combat_cost["state"] != turn_cost["state"]
    assert combat_cost["enemyRules"] == turn_cost["enemyRules"]
    assert combat_cost["enemyRules"] != multi_hit["enemyRules"]
    assert combat_cost["state"] == multi_hit["state"]
    for arms in inputs.values():
        assert set(arms) == set(PROTOCOLS)
        assert all(set(item) == {"h", "g", "T", "protocol"} for item in arms.values())
    for arms in inputs.values():
        encoded = json.dumps(arms).lower()
        assert not any(f'"{forbidden}"' in encoded for forbidden in
                       ("audit", "rng", "airegs", "referencepublicstate", "joint", "continuations"))

    probes = {}
    for encounter, row in exports.get("enemyProbes", {}).items():
        if "error" in row:
            probes[encounter] = row
            continue
        enemies = row["result"]["input"]["enemyRules"]
        probes[encounter] = enemies
        for enemy in enemies:
            if enemy["rules"]:
                for node in enemy["rules"]["nodes"]:
                    if node["NodeKind"] != "Move":
                        assert node["next"] is None and node["successor"] == "unqualified"
                        assert node["weightsAvailable"] is False
    conditional = {
        node["ConditionalKind"]: node["condition"]
        for enemies in probes.values() if isinstance(enemies, list)
        for enemy in enemies if enemy["rules"]
        for node in enemy["rules"]["nodes"] if node["condition"]
    }
    assert conditional["TestSubjectRevive"]["dependency"] == "unqualified_revive_phase"
    assert conditional["LagavulinSleep"]["dependency"] == "owner_asleep_power"
    observed_attacks = [
        {"enemy": enemy["Entry"], "move": node["MoveId"], "attacks": node["attacks"],
         "total": sum(hit["BaseDamage"] * hit["Repeats"] for hit in node["attacks"]),
         "hits": sum(hit["Repeats"] for hit in node["attacks"])}
        for enemies in [[mechanics["enemyRules"][0]], *probes.values()] if isinstance(enemies, list)
        for enemy in enemies if enemy["rules"] for node in enemy["rules"]["nodes"] if node["attacks"]
    ]
    attack_pair = []
    for index, left in enumerate(observed_attacks):
        for right in observed_attacks[index + 1:]:
            if left["total"] == right["total"] and left["hits"] != right["hits"]:
                attack_pair.append([left, right])
    return {
        "cases": len(inputs), "policyQueries": len(inputs) * len(PROTOCOLS),
        "historicalStructureCases": len(dataset["structureEvidence"]),
        "fairExportPairs": len(exports["results"]),
        "nontrivialHiddenPairs": sum(row["result"]["fairness"]["hiddenDrawCount"] > 1
                                    for row in exports["results"].values()),
        "warmMedianMs": median(row["result"]["meanMilliseconds"] for row in exports["results"].values()),
        "warmMaxMs": max(row["result"]["meanMilliseconds"] for row in exports["results"].values()),
        "coldMedianMs": median(row["coldMilliseconds"] for row in exports["results"].values()),
        "sameAttackDifferentFollowup": [moves["FIRST_ACID_GOOP"], moves["ACID_GOOP"]],
        "sameTotalDifferentHits": attack_pair,
        "syntheticContractDiagnostics": {"equalTotalDistinctSegments": [[12, 1], [6, 2]],
                                         "costExpirationFlags": [1, 3]},
        "conditionalRules": conditional,
        "sameDeckDifferentZones": zone_counts, "sameIdealDifferentFair": same_ideal,
        "idealVictoryDifferentFairCashout": same_ideal_different_cashout,
        "directVictory": direct,
        "conditionalTape": [tape["fixedTape"]["WinProbability"], tape["adaptive"]["Lower"]],
        "exhaustionNecessity": {
            "status": "unresolved", "existingBurningPactStartup": outcome("blocker_burning_pact")["Lower"],
            "entryActions": [entry["Steps"] for entry in outcome("blocker_burning_pact")["Entries"]],
            "entryExhaustChanges": [entry["ExhaustDelta"] for entry in outcome("blocker_burning_pact")["Entries"]],
            "reason": "core already qualified at depth zero with the blocker in hand",
        },
        "enemyProbes": probes,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exports", type=Path)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("diagnostics", type=Path)
    args = parser.parse_args()
    exports = read(args.exports)
    dataset, elapsed = compile_dataset(exports)
    started = time.perf_counter()
    write(args.dataset, dataset)
    timing = {"compileMilliseconds": elapsed, "encodeGzipMilliseconds": (time.perf_counter() - started) * 1000,
              "datasetBytes": args.dataset.stat().st_size}
    result = inspect(exports, dataset) | timing | {"identity": exports.get("identity")}
    args.diagnostics.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "enemyProbes"}, indent=2))
