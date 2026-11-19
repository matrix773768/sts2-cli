"""Replay two frozen development prefixes and retain both sides of every frame."""
import argparse
from functools import partial
import importlib.util
from pathlib import Path
from threading import Event
from time import monotonic

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("e3_s2c", HERE.parent / "m1-s2c/benchmark.py")
s2c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s2c)
bank, f3a, f3b = s2c.bank, s2c.f3a, s2c.f3b
CASES = {
    "predator": "660d09b29ecc5a9d1cb32efa98792b7eb6551c7cb8c1a5ff6f1b1fad6b47d98d",
    "predator_with_potion": "44ffda5ac21adc5e1a4f2f6fb9643cb9997b708c0b4c0326006dba034a6fa65d",
    "enemy_side": "a85bf9f7e504cb280c8ccebae816a2bb6446326ca28bacca9c9bfa813f3bd520",
}


def replay(output, root, failure):
    restore = partial(s2c.s2b.synth.rebuild,
                      session=lambda folder: bank.Session(folder, monotonic() + 60, Event()))
    if any(c["id"] == "NEUTRALIZE" for c in root["spec"]["deck"]):
        restore = partial(s2c.s2b.quality.native_neutralize, restore=restore)
    actions = [f3b.action_for_wire(action) for action in failure["minimal_action_prefix"]]
    prep, plan = f3a.search(output, root, f3a.BUDGETS[0], actions, restore=restore)
    if not plan or len(plan.get("frames", [])) != len(actions):
        raise ValueError("Frozen prediction prefix failed to reconstruct")
    predicted_stamps = [bank.f1.digest(frame[0]["exact_continuation_state"].encode())
                        for frame in plan["frames"]]
    f3a.equal("historical winning prediction stamps", failure["expected_search_sha256"], predicted_stamps)
    samples = []
    with restore(output, root) as (game, _):
        game.teacher_frames = []
        game.teacher_choices = []
        f3a.equal("root", plan["root"], game.request("i1_begin")["state"])
        for i, (action, predicted) in enumerate(zip(actions, plan["frames"], strict=True), 1):
            response = game.request("i1_step", action=action)
            if response["type"] != "i1_state":
                raise ValueError(f"Native prefix stopped at {i}: {response}")
            native = response["state"]
            samples.append(dict(step=i, action=action, predicted=predicted, native=native,
                                differences=s2c.diffs(predicted, native, limit=100),
                                terminal=response["terminal"], before_window=response.get("before_window"),
                                terminal_window=response.get("terminal_window"),
                                decision=response["decision"]))
    return dict(preparation=prep, root_frame=plan["root"], original=failure, samples=samples)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    selection = bank.read(s2c.SELECTION)
    selection["selection"] = [r for r in selection["selection"]
                              if r["split"] == "development" and r["id"] in CASES.values()]
    selection["pilot"] = list(CASES.values())
    plan, done = s2c.inputs(s2c.ROOT / "logs/m1-s2b/formal", selection, "pilot")
    versions = bank.versions_for_host(args.output, s2c.s2b.quality.HOST) | {
        "synthetic_spec": 2, "initializer": "m1-s2a-v1"}
    f3a.equal("pinned frozen host", plan["versions"], versions)
    cases = {}
    for name, case_id in CASES.items():
        archived = s2c.s2b.checked(s2c.ROOT / "logs/m1-s2c/formal-v2/audit" / f"{case_id}.json.gz")
        root = done[case_id]["root"]
        f3a.equal("development audit source", (case_id, "development", root["id"], root["spec"]),
                  (archived["case_id"], archived["split"], archived["root_id"], archived["spec"]))
        failure = next(f for f in archived["failures"] if f["policy"] == "f3b")
        cases[name] = dict(case_id=case_id, spec=root["spec"]) | replay(args.output, root, failure)
        bank.atomic(args.output / "results.json", dict(versions=versions, cases=cases))


if __name__ == "__main__":
    main()
