"""Run a Q6 matrix, retaining native evidence for predeclared representatives."""
import argparse
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
spec = spec_from_file_location("q5_replay", HERE.parent / "m1-q5/replay.py")
q5 = module_from_spec(spec)
spec.loader.exec_module(q5)
ROOTS = {"boss": ("holdout-02-defect", "C", 18), "regent": ("dev-03-regent-elite", "A", 8)}


def representatives(search):
    runs = {row["arm"]: row for row in search["audited"] if row["cap"] == 64}
    if not runs:
        return
    root = runs["A"]["routes"][0]
    yield "A", root
    for arm in ("B", "C"):
        chosen = runs[arm]["selected"]
        if chosen is not None:
            yield arm, runs[arm]["routes"][chosen]
    death = next((row for row in runs["C"]["routes"] if row["stop"] == "death"), None)
    if death is not None:
        yield "C-death", death


def matrix(output, roots):
    start = time.monotonic()
    all_results = {}
    recorded = q5.e2.load(HERE.parent / "m1-q4/results.json")["routes"]
    for name, (case, rule, prefix) in ROOTS.items():
        if name not in roots:
            continue
        source = recorded[f"{case}/{rule}"]
        actions = q5.e2.inputs(source)[:prefix]
        folder = output / name
        kwargs = dict(case=case, prefix=prefix, cross_mechanism=name)
        parent = q5.execute(folder / "parent", source, actions, **kwargs)
        search = q5.e2.load(folder / "parent/search.json")
        print(name, search["status"], parent["matched"], parent["firstDifference"], flush=True)
        validation = {}
        seen = {}
        for label, route in representatives(search):
            decisions = route["decisions"]
            if route["stop"] not in {"common_horizon", "death", "victory", "action_cap"} or not decisions:
                validation[label] = {"notReplayed": route["stop"]}
                continue
            suffix = [item["input"] for item in decisions]
            key = json.dumps(suffix, sort_keys=True)
            if key in seen:
                validation[label] = {"sameRouteAs": seen[key]}
                continue
            assert time.monotonic() - start < 180, "Q6 launch deadline"
            seen[key] = label
            outcome = q5.execute(folder / label, source, actions + suffix, decisions, **kwargs)
            native = q5.e2.load(folder / label / "fast.json")
            outcome["permanentResourcesUnchanged"] = native["initialResources"] == native["finalResources"]
            validation[label] = outcome
            print(name, label, outcome["matched"], outcome["planned"], outcome["nativeStatus"], flush=True)
        all_results[name] = {"parent": parent, "search": search, "validation": validation}
    return all_results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--root", choices=ROOTS)
    args = parser.parse_args()
    assert hashlib.sha256(q5.e2.BASELINE.read_bytes()).hexdigest() == "d286a18c7c0a06769aa636ec00cac53f3fb71de749028858c1e1a7062282ab13"
    output = args.output.resolve()
    output.mkdir(parents=True)
    q5.save(output / "results.json", matrix(output, [args.root] if args.root else ROOTS))


if __name__ == "__main__":
    main()
