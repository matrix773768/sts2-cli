"""Audit matrix integrity and export full compressed route trajectories."""
import argparse
import gzip
import json
from pathlib import Path

from benchmark import load, f1, TIERS
from check import history


def prefix_signatures(search):
    nodes = {n["id"]: n["frame"]["stamp"] for n in search["history"]}
    return [(r["plan"]["strategy"], [nodes[i] for i in r["nodes"]])
            for r in search["routes"] if r["plan"]["repair_reason"] == "initial_strategy"
            and r["stop"] != "truncated"]


def publish(source, check_output, output):
    rows = load(source / "results.json")
    checks = load(check_output / "checks.json")
    keys = {(r["id"], r["arm"], r["potions"]) for r in rows}
    ids = {r["id"] for r in rows}
    assert len(ids) == 5 and len(rows) == len(keys) == 35
    assert keys == {(rid, arm, potions) for rid in ids for arm in ("A", "B", "C", "D")
                    for potions in ((False,) if arm == "A" else (False, True))}
    output.mkdir(parents=True, exist_ok=True)
    initial = {}
    with (output / "histories.jsonl.gz").open("wb") as stream:
        with gzip.GzipFile(filename="", mode="wb", mtime=0, fileobj=stream) as archive:
            for row in rows:
                assert row["used"] <= TIERS[-1]
                raw = history(source / row["history"])
                assert sum(r["transitions"] for r in raw) == row["used"]
                assert all(r.get("root_unchanged") for r in raw if "history" in r)
                if row["status"] == "native_win":
                    accepted = raw[-1]["verification"]
                    assert accepted["status"] == "win" and accepted["strict_terminal"]
                    assert accepted["matched_actions"] == len(raw[-1]["actions"])
                    assert all(t["expected_sha256"] == t["actual_sha256"] for t in accepted["trace"])
                if row["arm"] in ("C", "D") and raw and "history" in raw[0]:
                    initial[row["id"], row["arm"], row["potions"]] = prefix_signatures(raw[0])
                key = row.pop("history").removesuffix(".json.gz")
                row["history_key"] = key
                archive.write((json.dumps(dict(key=key, trials=raw), separators=(",", ":")) + "\n").encode())
    for rid in ids:
        for potions in (False, True):
            a, b = (initial.get((rid, arm, potions), []) for arm in ("C", "D"))
            assert all(x == y for x, y in zip(a, b))
    f1.write(output / "results.json", rows)
    f1.write(output / "checks.json", checks)
    print(f"Audited {len(rows)} cells, {sum(r['status']=='native_win' for r in rows)} verified wins")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "checks", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    publish(args.source, args.checks, args.output)
