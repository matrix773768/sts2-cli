"""Compare isolated and settled-map resident artificial combat roots."""
import argparse
from contextlib import nullcontext
import importlib.util
from pathlib import Path
from threading import Event
from time import monotonic, perf_counter

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("f5_probe", HERE.parent / "m1-f5a/probe.py")
f5 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f5)
bank = f5.bank
equal = f5.f3a.equal
ORDER = ("A", "B", "A")


class Session(bank.Session):
    def request(self, cmd, **args):
        response = super().request(cmd, **args)
        self.phase_ms = response.pop("_b1a_ms", {})
        return response


def session(output):
    return Session(output, monotonic() + 120, Event())


def predict(game, spec):
    clock = perf_counter()
    public = game.request("synthetic_start", spec=spec)
    phases = game.phase_ms
    initialize_ms = bank.elapsed(clock)
    equal("player play decision", "combat_play", public["decision"])
    clock = perf_counter()
    native = game.request("synthetic_snapshot")
    identity = game.request("f1_begin")
    snapshot_ms = bank.elapsed(clock)
    equal("root deck", spec["deck"], native["deck"])
    equal("root continuation", identity["live"], bank.f1.digest(native["continuation"].encode()))
    before = game.request("f1_audit")
    clock = perf_counter()
    response = game.request("i1_f3b", arm="C", potions=False, cap=512, rejected=[])
    rpc_ms = bank.elapsed(clock)
    equal("live source after search", before, game.request("f1_audit"))
    result = response["search"]
    equal("proof-of-feasibility prediction", ("predicted_win", True), (result["status"], result["root_unchanged"]))
    return dict(initialize_ms=initialize_ms, native_phases_ms=phases, snapshot_ms=snapshot_ms,
                prediction_prepare_ms=response["root_prepare_ms"], search_rpc_ms=rpc_ms,
                hot_ms=result["hot_ms"], cpu_ms=result["cpu_ms"],
                peak_bytes=result["peak_working_set_bytes"],
                root_sha256=bank.stamp([public, native, identity]), live=identity["live"],
                winner_key=result["winner_key"], transitions=result["transitions"],
                actions=result["actions"], prediction_stamps=result["stamps"]), result


def retire(game, result, before_profile):
    clock = perf_counter()
    game.teacher_frames = []
    game.teacher_choices = []
    game.request("i1_begin")
    frames = []
    reply = None
    for action in result["actions"]:
        reply = game.request("i1_step", action=f5.s2c.f3b.action_for_wire(action))
        equal("native retirement action", "i1_state", reply["type"])
        frames.append(reply["state"])
    equal("native retirement victory", (True, "card_reward"), (reply["terminal"], reply["decision"]["decision"]))
    equal("settled map", "map_select", game.request("action", action="skip_card_reward")["decision"])
    equal("release replay capture", "i1_released", game.request("i1_release")["type"])
    equal("settled worker reset", "reset", game.request("b1a_reset")["type"])
    cleanup = game.phase_ms
    equal("profile restored", before_profile, game.request("b1a_profile")["value"])
    terminal = reply["state"][0]
    stamps = [bank.f1.digest(frame[0]["exact_continuation_state"].encode()) for frame in frames]
    mismatch_steps = [index for index, (native, predicted) in enumerate(
        zip(stamps, result["stamps"], strict=True), 1) if native != predicted]
    return dict(elapsed_ms=bank.elapsed(clock), cleanup_ms=cleanup, native_frames_sha256=bank.stamp(frames),
                prediction_stamp_mismatch_steps=mismatch_steps, hp=terminal["player_hp"],
                max_hp=terminal["player_max_hp"], gold=terminal["player_gold"],
                potions=terminal["player_potions"], rng=terminal["rng_counters"])


def batch(output, cases, resident, reference):
    started = perf_counter()
    rows = []
    with session(output) if resident else nullcontext() as worker:
        for index, case in enumerate(ORDER):
            with nullcontext(worker) if resident else session(output) as game:
                clock = perf_counter()
                row, result = predict(game, cases[case])
                row.update(case=case, pid=game.engine.proc.pid, prediction_wall_ms=bank.elapsed(clock),
                           handshake_ms=game.startup_ms if not resident or index == 0 else 0)
                expected_row, expected = reference.setdefault(case, (row, result))
                equal("full root observation", expected_row["root_sha256"], row["root_sha256"])
                differences = f5.compare(expected, result)
                equal("all prediction semantics", [], differences)
                row["prediction_differences"] = differences
                # The hot worker may re-enter only after legal settlement and guarded reset.
                if resident:
                    profile = game.request("b1a_profile")["value"]
                    if index == 0:
                        initial_profile = profile
                    equal("profile at root", initial_profile, profile)
                    row["retirement"] = retire(game, result, initial_profile)
                rows.append(row)
    return dict(resident=resident, elapsed_ms=bank.elapsed(started), rows=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    contract = bank.read(HERE / "cases.json")
    equal("input contract", 1, contract["contract_version"])
    cases = contract["cases"]
    versions = bank.versions_for_host(args.output, "m1-b1a-build")
    reference, batches = {}, []
    # An active combat must never be retired by the settled-map protocol.
    try:
        with session(args.output) as game:
            predict(game, cases["A"])
            game.request("b1a_reset")
    except bank.f1.i2.StopRun as error:
        if "Reset requires an idle, settled map boundary" not in str(error):
            raise
        guard = dict(rejected=True, error=str(error), exit_code=game.engine.proc.returncode)
    else:
        raise ValueError("Live combat reset was accepted")
    try:
        with session(args.output) as game:
            game.request("synthetic_start", spec=cases["A"])
            game.cancelled.set()
            game.request("synthetic_snapshot")
    except bank.f1.i2.engine_client.EngineCancelled:
        cancellation = dict(discarded=game.engine.proc.returncode is not None,
                            exit_code=game.engine.proc.returncode)
        equal("cancelled host discarded", True, cancellation["discarded"])
    else:
        raise ValueError("Cancelled host continued serving")

    data = dict(versions=versions, input=contract, active_reset=guard, cancellation=cancellation,
                batches=batches)
    for resident in (False, True, False, True):
        batches.append(batch(args.output, cases, resident, reference))
        bank.atomic(args.output / "results.json", data)
    controls = {}
    for case in ("A", "B"):
        with session(args.output) as game:
            row, result = predict(game, cases[case])
            equal("cold control root", reference[case][0]["root_sha256"], row["root_sha256"])
            control = retire(game, result, game.request("b1a_profile")["value"])
        for measured in (row for batch in batches if batch["resident"] for row in batch["rows"]
                         if row["case"] == case):
            equal("cold vs resident native retirement frames", control["native_frames_sha256"],
                  measured["retirement"]["native_frames_sha256"])
        controls[case] = control
    bank.atomic(args.output / "results.json", data | {"cold_native_controls": controls})


if __name__ == "__main__":
    main()
