"""Compare two frozen S2A roots and audit explicit Survivor discard instances."""
import argparse
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-s1"))
import run as synth

bank, f3a, f3b = synth.bank, synth.f3a, synth.f3b
CASES = ("shiv-lean", "shiv-hive-stocked")
BASELINE = "m1-s2a-build"
FIXED = "m1-f3d-a-build"


def survivor_child(result):
    return next(node for node in result["history"] if node.get("parent") == 0
                and node["action"].get("card_id") == "SURVIVOR")


def fixed_prefix(output, root, action):
    start = perf_counter()
    with synth.rebuild(output, root) as (game, _):
        pre = game.request("f1_audit")
        response = game.request("i1_capture", node_budget=1000, fixed_actions=[action], fixed_prefix=True)
        f3a.equal("fixed prediction source unchanged", pre, game.request("f1_audit"))
    f3a.equal("prefix result", "fixed_prefix", response["status"])
    return response, pre, bank.elapsed(start)


def compare_prefix(output, root, action, expected, pre):
    start = perf_counter()
    with synth.rebuild(output, root) as (game, _):
        f3a.equal("independent original RNG and identity", pre, game.request("f1_audit"))
        before = game.request("i1_begin")["state"]
        f3a.equal("prefix root frame", expected["root"], before)
        game.teacher_frames, game.teacher_choices = [], []
        step = game.request("i1_step", action=action)
        f3a.equal("nonterminal prefix", False, step["terminal"])
        f3a.equal("full native survivor frame", expected["frames"][0], step["state"])
        after = game.request("f1_audit")
        game.request("i1_release")
    return dict(elapsed_ms=bank.elapsed(start), choice=step["choice_evidence"],
                pre_audit=pre, post_audit=after, native_action=step["native_action"],
                native_frame_sha256=f3a.frame_hash(step["state"]),
                predicted_frame_sha256=f3a.frame_hash(expected["frames"][0]),
                decision=step["decision"])


def duplicate_action(action, menu):
    matches = [card for card in menu if card["id"] == "DEFEND_SILENT"]
    first, second = matches[:2]
    f3a.equal("duplicate test exact state key", first["key"], second["key"])
    result = deepcopy(action)
    token = result["choice"]["cards"][0]
    token.update(card_id=second["id"], upgrade_level=second["upgrade"], state_key=second["key"],
                 source_occurrence=1, option_occurrence=1)
    return result, second["index"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True)
    start = perf_counter()
    sys.addaudithook(f3b.deny_reference_open)
    source = bank.read(HERE.parent / "m1-s2a/results.json")
    base_versions = bank.versions_for_host(out, BASELINE)
    f3a.equal("pinned old host", source["versions"]["headless_sha256"], base_versions["headless_sha256"])
    evidence = {}
    for name in CASES:
        artifact = next(row for row in source["cases"] if row["case"] == name)
        case = out / name
        case.mkdir()
        root, audit = synth.verified_variant(case, artifact["spec"], base_versions)
        f3a.equal("frozen S2A live", artifact["live"], root["identity"]["live"])
        clock = perf_counter()
        old = f3b.search(case, root, "C", False, 128, [], restore=synth.rebuild)
        old_ms = bank.elapsed(clock)
        node = survivor_child(old)
        f3a.equal("baseline survivor", (None, "PendingChoice"), (
            node["action"].get("choice"), node["frame"]["boundary"]))
        with synth.rebuild(case, root) as (game, _):
            natural = game.request("f1_step", step=1, audit=True)
            f3a.equal("baseline native uses Survivor", ("SURVIVOR", None), (
                natural["selected"]["id"], natural["choice_failure"]))
        f3b.save_history(case / "baseline-search.json.gz", old)
        evidence[name] = dict(root=root, baseline_audit=audit,
            baseline=dict(status=old["status"], transitions=old["transitions"], elapsed_ms=old_ms,
                          node=node, native=natural))

    versions = bank.versions_for_host(out, FIXED)
    for name, row in evidence.items():
        case = out / name
        root, audit = synth.verified_variant(case, row["root"]["spec"], versions)
        for surface in ("public_root", "native", "identity"):
            f3a.equal(f"cross-build {surface}", row["root"][surface], root[surface])
        row["fixed_root"] = root
        row["fixed_audit"] = audit
        row["search"] = synth.verify_f3b(case, root)
        with gzip.open(case / "f3b-private.json.gz", "rt", encoding="utf-8") as stream:
            result = json.load(stream)
        node = survivor_child(result)
        f3a.equal("predicted survivor resumes", ("active", "None", False), (
            node["frame"]["stop"], node["frame"]["boundary"], node["frame"]["risk"]))
        row["fixed_survivor_node"] = node
        wire = f3b.action_for_wire(node["action"])
        prefix, pre, elapsed = fixed_prefix(case, root, wire)
        f3a.equal("fixed-prefix stable", ("None", False, False), (
            prefix["prefix_boundary"], prefix["prefix_risk"], prefix["prefix_terminal"]))
        f3a.equal("search vs fixed prefix exact continuation", node["frame"]["stamp"],
                  bank.f1.digest(prefix["frames"][0][0]["exact_continuation_state"].encode()))
        replay = compare_prefix(case, root, wire, prefix, pre)
        row["prefix"] = replay | {"fixed_prediction_ms": elapsed}
        natural = row["baseline"]["native"]
        f3a.equal("F2 resolved decision and RNG", (natural["decision"], natural["post_audit"]),
                  (replay["decision"], {k: replay["post_audit"][k] for k in ("stamp", "rng")}))
        request, = natural["choice_requests"]
        f3a.equal("F2 selected candidate index", request["indexes"][0], replay["choice"]["binding"]["option"])
        f3a.equal("verified native instance destination", True, replay["choice"]["destination_verified"])

        if name == "shiv-lean":
            duplicate, index = duplicate_action(wire, request["candidates"])
            expected, before, elapsed = fixed_prefix(case, root, duplicate)
            f3a.equal("fixed duplicate stable", "None", expected["prefix_boundary"])
            check = compare_prefix(case, root, duplicate, expected, before)
            binding = check["choice"]["binding"]
            f3a.equal("second identical instance bound and discarded", (index, index, True),
                      (binding["option"], binding["source_index"], check["choice"]["destination_verified"]))
            row["duplicate"] = check | {"fixed_prediction_ms": elapsed, "expected_index": index}
        print(name, row["search"]["status"], row["search"].get("transitions"), flush=True)

    bank.atomic(out / "results.json", dict(cases=evidence, baseline_versions=base_versions,
                 versions=versions, wall_ms=bank.elapsed(start), cap=128, arm="C", potions=False))


if __name__ == "__main__":
    main()
