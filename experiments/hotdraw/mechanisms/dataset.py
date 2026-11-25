"""Compile public queries and separately stored supervision from frozen evidence."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
PUBLIC_FIELDS = (
    "encounter", "turn", "PlayerPhase", "hp", "maxHp", "block", "Energy", "Stars", "Gold",
    "MaxHandSize", "TerminalOutcome", "hand", "play", "discard", "exhaust", "knownTop",
    "unknown", "knownBottom", "Generation", "relics", "powers", "enemies",
)
PROTOCOLS = {
    "Startup": "startup_priority",
    "Fight": "battle_priority",
    "Switch": "joint_switch",
    "IdealStartup": "ideal_startup",
}
OBJECTIVES = {"Startup": "start_entry", "Fight": "battle_victory",
              "Switch": "battle_victory", "IdealStartup": "ideal_entry"}
MECHANISM_FIELDS = ("schema", "state", "cardCosts", "cardRules", "powerRules", "relicRules",
                    "enemyRules", "limitations")


def read(path):
    with gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else path.open(encoding="utf-8") as stream:
        return json.load(stream)


def write(path, item):
    payload = json.dumps(item, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    path.write_bytes(gzip.compress(payload, mtime=0))


def query(mechanisms, template, budget, arm):
    """An evaluator receives only the public root, requested template and protocol."""
    state = mechanisms["state"]
    if set(state) != set(PUBLIC_FIELDS):
        raise ValueError("Public-state contract drift")
    return {
        "h": {key: mechanisms[key] for key in MECHANISM_FIELDS},
        "g": {"family": template["Family"], "entryProtocol": "verified_role_replay", "period": [
            {key: role[key] for key in ("Role", "Card", "Target", "Upgrade")} for role in template["Period"]
        ]},
        "T": {key: budget[key] for key in ("StartActions", "BattleActions", "Events")},
        "protocol": PROTOCOLS[arm],
    }


def compile_dataset(exports):
    started = time.perf_counter()
    sources = {}
    for stage in ("structures", "reachability"):
        path = HERE.parent / stage / "results.json.gz"
        sources[stage] = {"pathFromRepo": f"experiments/hotdraw/{stage}/results.json.gz",
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "envelope": read(path)}
    cohort = read(HERE.parent / "reachability" / "fixtures.json")
    reach = sources["reachability"]["envelope"]["results"]
    structures = sources["structures"]["envelope"]["results"]
    inputs = {}
    labels = {}
    for name, row in reach.items():
        result = row["result"]
        public = result["PublicRoot"]["state"]
        exported = exports["results"][name]["result"]["input"]
        if exported["state"] != public:
            raise ValueError(f"{name}: live export differs from archived public root")
        inputs[name] = {arm: query(exported, result["Template"], result["Budget"], arm) for arm in PROTOCOLS}
        labels[name] = {
            "rootKey": result["RootKey"],
            "variant": cohort["cases"][name],
            "structureSource": next((key for key, value in {
                "core50": "core", "energy_limited": "energy", "conditioned": "conditioned",
            }.items() if value == result["Target"]), None),
            "target": result["Template"],
            "budget": result["Budget"], "discoveryBudget": result["Discovery"],
            "outcomes": result["arms"],
            "discovery": result["discovery"], "substitute": result["substitute"],
            "scriptComparison": result["tape"], "lapAudit": result["laps"],
        }
        for arm in result["arms"].values():
            if not 0 <= arm["Lower"] <= arm["Upper"] <= 1 + 1e-10:
                raise ValueError(f"{name}: invalid probability interval")
            if abs(sum(atom["Weight"] for atom in arm["Joint"]) - 1) > 1e-9:
                raise ValueError(f"{name}: policy probability mass is not one")
    if any(label["structureSource"] not in structures for label in labels.values()):
        raise ValueError("Dangling archived structure reference")
    return {
        "schema": 1,
        "boundObjectives": OBJECTIVES,
        "exportIdentity": exports.get("identity"),
        "provenance": {key: {k: v for k, v in value.items() if k != "envelope"} for key, value in sources.items()},
        "inputs": inputs, "labels": labels,
        "structureEvidence": {name: row["result"] for name, row in structures.items()},
    }, (time.perf_counter() - started) * 1000


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exports", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result, milliseconds = compile_dataset(read(args.exports))
    started = time.perf_counter()
    write(args.output, result)
    print(json.dumps({"prepareMilliseconds": milliseconds,
                      "encodeGzipMilliseconds": (time.perf_counter() - started) * 1000,
                      "cases": len(result["inputs"]), "bytes": args.output.stat().st_size}))
