"""Aggregate single-trajectory outcomes without pooling strategies."""
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import runpy
import sys

stats = runpy.run_path(str(Path(__file__).resolve().parent.parent /
                           "m1-s3b/summarize.py"))["stats"]


def read(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def summarize(rows):
    groups = defaultdict(list)
    seen = set()
    for row in rows:
        case, result = row["case"], row["result"]
        identity = (row["cohort"], case["id"], result["strategy"])
        if identity in seen:
            raise ValueError(f"Duplicate rollout {identity}")
        seen.add(identity)
        spec = case.get("spec", {})
        live = case.get("identity", {})
        resources = live.get("resources", {})
        relics = spec.get("relics", resources.get("relics", []))
        potions = spec.get("potions", resources.get("potions", []))
        keys = {
            "all": "all",
            "character": spec.get("character", case.get("character", "Ironclad")),
            "encounter": spec.get("encounter", live.get("encounter", "unknown")),
            "build": case.get("template", case.get("rule", case["id"].rsplit("-a2", 1)[0])),
            "pressure": case.get("complexity", case.get("profile", "unknown")),
            "resources": f"relics={len(relics)},potions={sum(bool(p) for p in potions)}",
        }
        for dimension, key in keys.items():
            groups[(row["cohort"], result["strategy"], dimension, key)].append(result)
    summary = {}
    for (cohort, strategy, dimension, key), group in groups.items():
        winners = [r for r in group if r["status"] == "predicted_win"]
        summary.setdefault(cohort, {}).setdefault(strategy, {}).setdefault(dimension, {})[key] = dict(
            n=len(group), wins=len(winners), win_rate=len(winners) / len(group),
            stops=Counter(r["status"] for r in group),
            stop_details=Counter(r["detail"] for r in group if r.get("detail")),
            unsupported_boundaries=Counter(r["end"]["boundary"] for r in group
                                           if r["status"] == "unsupported" and "end" in r),
            actions=stats([r.get("action_count") for r in group]),
            transitions=stats([r.get("transitions") for r in group]),
            hot_ms=stats([r.get("hot_ms") for r in group]),
            hp=stats([r["end"]["hp"] for r in winners]),
            cumulative_loss=stats([r["end"]["cumulative_loss"] for r in winners]),
            net_hp_loss=stats([r["start"]["hp"] - r["end"]["hp"] for r in winners]),
            max_hp=stats([r["end"].get("max_hp") for r in winners]),
            gold=stats([r["end"].get("gold") for r in winners]),
            end_energy=stats([r["end"]["energy"] for r in winners]),
            end_potions=stats([sum(bool(p) for p in r["end"]["potions"]) for r in winners]),
        )
    return summary


if __name__ == "__main__":
    print(json.dumps(summarize(read(Path(sys.argv[1]))), indent=2, ensure_ascii=False))



