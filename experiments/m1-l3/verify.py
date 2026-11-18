"""Validate experiment invariants and replay distinct winning Crawlers routes."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-l2"))
from run import DOTNET, load
from verify_crawlers import replay

STRIKE = [17081539879745055099, 6157755496321621557]
DEFEND = [1355609195813973648, 11553611504259844353]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = load(args.output / "results.json")
    assert len(rows) == 19
    for root in ("small", "crawlers"):
        for key in ("rootStamp", "liveStamp"):
            assert len({r[key] for r in rows if r["root"] == root}) == 1, (root, key)
    for stock in (r for r in rows if r["mode"] == "stock"):
        match, = [r for r in rows if r["root"] == stock["root"] and r["nodes"] == stock["nodes"]
                  and r["mode"] == ("strike" if stock["root"] == "small" else "off")]
        for field in ("expanded", "transitions", "quality", "routeHash", "boundary"):
            assert stock[field] == match[field], (field, stock, match)
    for row in rows:
        trace = row["trace"]
        if row["root"] == "small" or row["mode"] == "stock":
            assert "pool" not in trace and "swap" not in trace
            continue
        assert len(trace["pool"]) == 1
        order = [event[1:] for event in trace["expand"] if event[1:] in (STRIKE, DEFEND)]
        assert order == ([STRIKE, DEFEND] if row["mode"] == "strike" else [DEFEND, STRIKE]), row
        assert bool(trace.get("swap")) == (row["mode"] == "strike"), row

    os.environ["STS2_DOTNET"] = str(DOTNET)
    os.environ["STS2_DOTNET_VERSION"] = "9.0.7"
    deadline = time.monotonic() + 100
    native = {}
    candidates = load(HERE.parent / "m1-l2" / "results.json")
    crawlers, = [r for r in candidates if r["root"] == "crawlers"]
    first_steps = crawlers["prefix"][1]["rows"]
    for row in rows:
        if row["root"] != "crawlers" or not row["quality"]["won"] or row["routeHash"] in native:
            continue
        directory = args.output / (
            f"{row['root']}-{row['nodes']}-{row['budgetMs']}-{row['mode']}-{row['repeat']}"
        )
        route = load(directory / "route.json")
        fields = ("kind", "cardId", "targetCombatId", "cardOccurrence")
        first, = [r for r in first_steps.values()
                  if all(r["action"][k] == route[0][k] for k in fields)]
        item = first["postState"] | {"witness": route, "quality": row["quality"]}
        native[row["routeHash"]] = replay(item, args.output / "native", deadline)
    print(json.dumps(native, indent=2))


if __name__ == "__main__":
    main()
