"""Verify native baseline parity, blind input isolation and a known safe-prefix repair."""
import argparse
import gzip
import json
from pathlib import Path
import sys
from time import perf_counter

from benchmark import (deny_reference_open, expect_native, f1, f3a, load,
                       run_cell, stage_roots)


def history(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def q1_native(output, root):
    f1.Session = f3a.Session
    f1.play = f3a.control_play
    return f1.measure(output, root, "B")


def compare_q1(output, roots, benchmark):
    summaries = []
    rows = [r for r in load(benchmark / "results.json") if r["arm"] == "A"]
    for root in roots:
        trial = next(r for r in rows if r["id"] == root["id"])
        search = history(benchmark / trial["history"])[0]
        step_ids = search["routes"][0]["nodes"][1:]
        by_id = {n["id"]: n for n in search["history"]}
        predicted = [(a["turn"], a["card_id"], a.get("target_combat_id"))
                     for a in (by_id[i]["action"] for i in step_ids)]
        native = q1_native(output, root)
        observed = []
        for line in native["trace"]:
            if line.get("phase") == "choice":
                continue
            card = line.get("selected") or {}
            observed.append((line["round"], card.get("id", ""), card.get("target")))
        assert native["root_verified"]
        summaries.append(dict(id=root["id"], candidate_steps=len(predicted), native_steps=len(observed),
                              action_parity=predicted == observed, native_outcome=native["status"],
                              candidate_outcome=trial["status"],
                              native_final=native.get("native_final")))
    return summaries


def verified_repair(output, f1_source):
    sub = output / "sentinel"
    sub.mkdir()
    root, = stage_roots(f1_source, sub, sentinel=True)
    with f3a.restored(sub, root) as (game, _):
        before = game.request("f1_audit")
        response = game.request("i1_f3b", arm="A", cap=128, potions=False, rejected=[],
                                repair_probe=dict(prefix_length=4, hand_index=3, target=1))
        assert before == game.request("f1_audit")
    result = response["search"]
    assert result["root_unchanged"] and result["status"] == "predicted_win"
    assert result["reused_prefix_transitions"] == 4 and result["routes"][1]["parent_unchanged"]
    native = expect_native(sub, root, result)
    assert native["status"] == "win" and native["strict_terminal"]
    assert native["native_final"]["outcome"]["final_hp"] == 21
    return dict(search=result, native=native)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("f1_source", type=Path)
    parser.add_argument("formal", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    sys.addaudithook(deny_reference_open)
    out = args.output.resolve()
    out.mkdir(parents=True)
    roots = stage_roots(args.source.resolve(), out, sentinel=False)
    assert not any("reference-routes" in p.name for p in out.iterdir())
    f3a.setup(out, "m1-f3b-build")
    cold = []
    for root in roots:
        start = perf_counter()
        with f3a.restored(out, root):
            cold.append(dict(id=root["id"], restore_ms=f1.ms(start)))
    checks = compare_q1(out, roots, args.formal)
    blind = run_cell(out, next(r for r in roots if r["id"] == "run1-offering-west-a2f03"), "C", True, 128)
    main_result = next(r for r in load(args.formal / "results.json") if
                       (r["id"], r["arm"], r["potions"]) == (blind["id"], "C", True))
    assert (blind["status"], blind["used"]) == (main_result["status"], main_result["used"])
    sentinel = verified_repair(out, args.f1_source.resolve())
    f1.write(out / "checks.json", dict(q1_native=checks, blind_prefix=blind, sentinel=sentinel,
                                      cold_native_roots=cold))
    print(f"Q1 parity {sum(r['action_parity'] for r in checks)}/5, blind prefix and native F1 repair verified")


if __name__ == "__main__":
    main()
