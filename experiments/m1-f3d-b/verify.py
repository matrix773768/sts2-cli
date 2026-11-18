"""Recheck S2A's frozen six cells without projecting mismatched terminal frames."""
import argparse
from contextlib import contextmanager
from pathlib import Path
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-s1"))
import run as synth

bank, f3a, f3b = synth.bank, synth.f3a, synth.f3b
HOST = "m1-f3d-b-build"
ROOT = HERE.parents[1]


@contextmanager
def native_neutralize(output, root):
    """Use the native OnPlay in every phase, and preserve the original live root."""
    with synth.rebuild(output, root) as (game, state):
        before = game.request("f1_audit")
        reply = game.request("f1_unpatch_neutralize")
        f3a.equal("known F2 Neutralize patch", {"type": "f2_unpatched", "method": "NeutralizePrefix"}, reply)
        f3a.equal("unpatch live audit", before, game.request("f1_audit"))
        f3a.equal("unpatch full native snapshot", root["native"], game.request("synthetic_snapshot"))
        yield game, state


def reproduce_guard(output, root):
    start = perf_counter()
    try:
        f3b.search(output, root, "C", False, 1, [], restore=synth.rebuild)
    except bank.f1.i2.StopRun as error:
        detail = str(error)
        if not detail.startswith("PredictionUnsupportedException:") or "NeutralizePrefix" not in detail:
            raise
        return dict(status="compatibility_rejected", detail=detail, elapsed_ms=bank.elapsed(start))
    raise RuntimeError("Expected the patched Neutralize to be rejected by the mirror guard")


def run(output, source):
    reference = bank.read(HERE.parent / "m1-s2a/results.json")
    versions = bank.versions_for_host(output, HOST)
    for key in ("game_sha256", "solver_sha256", "coreclr"):
        f3a.equal(f"pinned {key}", reference["versions"][key], versions[key])
    start = perf_counter()
    cases = {}
    for name in reference["f3b_selection"]:
        case = output / name
        case.mkdir()
        pin = next(r for r in reference["cases"] if r["case"] == name)
        baseline = next(r for r in source["cases"] if r["case"] == name)["root"]
        f3a.equal("published spec", pin["spec"], baseline["spec"])
        f3a.equal("published live", pin["live"], baseline["identity"]["live"])
        f3a.equal("baseline already cold verified", True, baseline["native_verified"])
        root, timing, _ = synth.sample(case, pin["spec"], versions)
        for surface in ("public_root", "identity", "native"):
            f3a.equal(f"same original frozen root {surface}", baseline[surface], root[surface])
        root.update(native_verified=True, level="L0")
        use_native = any(card["id"] == "NEUTRALIZE" for card in root["spec"]["deck"])
        row = dict(spec=root["spec"], live=pin["live"], root_ms=timing["root_ms"],
                   native_neutralize=use_native, baseline_status=pin["f3b"]["status"])
        if use_native:
            row["patch_guard"] = reproduce_guard(case, root)
        row["cell"] = f3b.run_cell(case, root, "C", False, 128,
                                   restore=native_neutralize if use_native else synth.rebuild)
        cases[name] = row
    bank.atomic(output / "results.json", dict(cases=cases, versions=versions, wall_ms=bank.elapsed(start)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source", type=Path, default=ROOT / "logs/m1-s2a/formal/records.json")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    sys.addaudithook(f3b.deny_reference_open)
    run(output, bank.read(args.source))


if __name__ == "__main__":
    main()
