"""Run one existing F3B cell on a D1 root and append its evidence to the bank."""
import argparse
import gzip
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from threading import Event
from time import monotonic
from uuid import uuid4

import bank as d1

spec = importlib.util.spec_from_file_location("d1_f3b", d1.HERE.parent / "m1-f3b/benchmark.py")
f3b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f3b)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bank", type=Path)
    parser.add_argument("root", help="Unambiguous root ID prefix")
    parser.add_argument("--arm", choices=("A", "B", "C", "D"), default="C")
    parser.add_argument("--cap", type=int, choices=f3b.TIERS, default=128)
    parser.add_argument("--potions", action="store_true")
    args = parser.parse_args()
    sys.addaudithook(f3b.deny_reference_open)
    bank = args.bank.resolve()
    with d1.writer(bank):
        manifest_path = bank / "manifest.json"
        manifest = d1.read(manifest_path)
        roots = [r for r in manifest["roots"] if r["id"].startswith(args.root)]
        if manifest["schema"] != d1.SCHEMA or len(roots) != 1:
            parser.error("Expected a v1 bank and one unambiguous root")
        root = roots[0]
        f3b.f3a.setup(bank, "m1-f3b-build")
        if d1.f1.digest(f3b.f1.DLL.read_bytes()) != root["versions"]["headless_sha256"]:
            parser.error("F3B host differs from the bank's pinned host")
        # D1 and F3B import separate F1 modules, but share the engine transport.
        audit = d1.audit(bank, root, monotonic() + 14, Event())
        if audit["status"] != "pass":
            raise RuntimeError(audit)
        uid = uuid4().hex
        output = bank / "search" / uid
        output.mkdir(parents=True)
        shutil.copyfile(bank / root["checkpoint"], output / root["checkpoint"])
        row = f3b.run_cell(output, root, args.arm, args.potions, args.cap)
        d1.atomic(output / "result.json", row)
        with gzip.open(output / row["history"], "rt", encoding="utf-8") as stream:
            trials = json.load(stream)
        for trial in trials:
            if trial["status"] != "predicted_win":
                continue
            rid = uuid4().hex
            manifest["routes"].append(dict(
                id=rid, root_id=root["id"], kind="solver_prediction", complete=True,
                search_id=uid, policy_version="M1-F3B-v1", arm=args.arm, potions=args.potions,
                uses_hidden_rng=True, transition_budget=args.cap, transitions=trial["transitions"],
                actions=trial["actions"], stamps=trial["stamps"]))
            native = trial["verification"]
            manifest["validations"].append(dict(
                id=uuid4().hex, kind="solver_native_replay", root_id=root["id"], route_id=rid,
                status=native["status"], matched_actions=native.get("matched_actions", 0),
                strict_terminal=native.get("strict_terminal", False), evidence=f"search/{uid}/{row['history']}"))
        searches = manifest.setdefault("searches", [])
        searches.append(dict(id=uid, root_id=root["id"], cap=args.cap, arm=args.arm, potions=args.potions,
                             uses_hidden_rng=True, policy_version="M1-F3B-v1",
                             **{k: row[k] for k in ("status", "used", "first_prediction", "first_native",
                                                     "wall_ms", "hot_ms", "cpu_ms")}))
        d1.atomic(manifest_path, manifest)
        d1.atomic(bank / "index.json", d1.index(manifest))


if __name__ == "__main__":
    main()
