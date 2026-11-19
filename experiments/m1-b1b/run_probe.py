"""Produce versioned prediction records with guarded native worker recycling."""
import argparse
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
from threading import Event, Timer
from time import monotonic, perf_counter

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


b1a = load("b1a_probe", HERE.parent / "m1-b1a/run_probe.py")
f5b = load("f5b_probe", HERE.parent / "m1-f5b/run_probe.py")
bank, equal, synth = b1a.bank, b1a.equal, f5b.synth
HOST = "m1-b1b-build"
CAP = f5b.CAP
ERRORS = (f5b.f3a.Difference, *bank.ERRORS)


class Session(b1a.Session):
    def request(self, cmd, **args):
        response = super().request(cmd, **args)
        if cmd == "synthetic_start":
            self.build_phases = self.phase_ms
        return response


def session(output):
    return Session(output, monotonic() + 240, Event())


def validate(spec):
    if set(spec) != {"schema", "character", "ascension", "encounter", "seed", "deck", "hp",
                     "max_hp", "relics", "potions", "act", "act_variant"}:
        raise ValueError("Expected explicit S2A schema-2 fields")
    if (spec["schema"] != 2 or spec["character"] not in {"Ironclad", "Silent"}
            or spec["act"] not in {1, 2} or not 0 <= spec["ascension"] <= 10
            or not 1 <= spec["hp"] <= spec["max_hp"] <= 999):
        raise ValueError("Unsupported character, act, ascension or HP")
    if not 1 <= len(spec["deck"]) <= 40 or any(
            set(c) != {"id", "upgrade"} or c["upgrade"] not in {0, 1} or c["id"] == "NEUTRALIZE"
            for c in spec["deck"]):
        raise ValueError("Unsupported deck or Neutralize adapter conflict")
    allowed = {"Ironclad": "BURNING_BLOOD", "Silent": "RING_OF_THE_SNAKE"}
    if spec["relics"] not in ([], [allowed[spec["character"]]]) or len(spec["potions"]) > 3 or any(
            p not in {None, "FLEX_POTION", "DEXTERITY_POTION"} for p in spec["potions"]):
        raise ValueError("Unsupported relic or potion slot")


def search(game, record, *, cap=CAP, refine_quality=True, predator_fixed=False):
    first = f5b.timed_request(game, "i1_f3b", cap=cap)
    history = first.pop("history", [])
    record["first"] = first
    if first["status"] != "predicted_win":
        return
    frame = history[first["winner_node"]]["frame"]
    seed = dict(key=first["winner_key"], hp=frame["hp"], hp_lost=frame["cumulative_loss"],
                max_hp=frame["max_hp"], gold=frame["gold"], potions=frame["potions"],
                actions=first["actions"], stamps=first["stamps"], at=0)
    first["winner"] = seed
    quality = f5b.refine(game, first, False, cap=cap) if refine_quality else None
    record["quality"] = quality
    if quality is not None and (quality.get("transitions") is None
                                or quality.get("seed_transitions") != len(seed["actions"])):
        record["quality_incomplete"] = True
    candidates = [c for c in (quality or {}).get("candidates", []) if c["potions"] == seed["potions"]]
    record["selected"] = max([seed, *candidates], key=lambda c: (c["hp"], -c["at"]))
    if not predator_fixed and f5b.terminal_risk(record["selected"]["actions"]):
        record["risks"].append("E3_PREDATOR_TERMINAL")
    if not predator_fixed and f5b.terminal_risk(seed["actions"]):
        record["risks"].append("E3_PREDATOR_FIRST_WIN")
    record["outcome"] = "predicted_win"


def semantic(record):
    def without_clocks(value):
        if isinstance(value, dict):
            return {k: without_clocks(v) for k, v in value.items()
                    if k not in {"hot_ms", "cpu_ms", "rpc_ms", "prepare_ms", "replay_ms", "frame_audit_ms",
                                 "menu_ms", "rollout_ms", "peak_working_set_bytes"}}
        if isinstance(value, list):
            return [without_clocks(v) for v in value]
        return value

    return bank.stamp(without_clocks({k: record.get(k) for k in (
        "root_sha256", "first", "quality", "selected", "outcome", "risks")}))


def execute(game, case, reference, *, search_root=search):
    start = perf_counter()
    record = dict(record_schema=1, input=case, synthetic=True, natural_reachability="unknown",
                  evidence_level="prediction_only", pid=game.engine.proc.pid, outcome="unresolved", risks=[])
    try:
        surfaces, timing = synth.capture(game, case["spec"])
        record.update(root_timing=timing, native_phases_ms=game.build_phases,
                      root_sha256=bank.stamp(surfaces), live=surfaces["identity"]["live"],
                      rng_sha256=bank.stamp([surfaces["native"][key] for key in ("run_rng", "player_rng")]),
                      initial_resources=surfaces["identity"]["resources"])
        if reference is not None:
            equal("frozen source surfaces", {k: reference[k] for k in surfaces}, surfaces)
        profile = json.loads(game.request("b1a_profile")["value"])
        profile.pop("unique_id", None)
        record["root_profile_sha256"] = bank.stamp(profile)
        baseline = game.request("b1b_initial_profile")["value"]
        search_root(game, record)
        record["predict_ms"] = bank.elapsed(start)
        record["semantic_sha256"] = semantic(record)
        if record["outcome"] != "predicted_win":
            record["discard_reason"] = "no_predicted_retirement_route"
        else:
            record["retirement"] = b1a.retire(game, record["first"]["winner"], baseline)
            if record["retirement"]["prediction_stamp_mismatch_steps"]:
                record["risks"].append("native_retirement_stamp_difference")
                if any(step != len(record["first"]["winner"]["actions"])
                       for step in record["retirement"]["prediction_stamp_mismatch_steps"]):
                    record["discard_reason"] = "active_native_stamp_difference"
        current, peak = game.read_memory(game.engine.proc) or (None, None)
        record.update(working_set_bytes=current, peak_working_set_bytes=peak)
    except ERRORS as error:
        record["failure"] = bank.failure(error)
        record["discard_reason"] = "failed_root"
    record["root_wall_ms"] = bank.elapsed(start)
    return record


def record_handshake(row, ms):
    row["handshake_ms"] = ms
    if "root_timing" in row:
        timing = row["root_timing"]
        timing["root_ms"] += ms - timing["handshake_ms"]
        timing["handshake_ms"] = ms


def batch(output, order, cases, references, resident, expected=None, journal=None):
    started = perf_counter()
    rows = []
    seen = {}
    with nullcontext() if not resident else session(output) as worker:
        for index, key in enumerate(order):
            with nullcontext(worker) if resident else session(output) as game:
                row = execute(game, cases[key], references.get(key))
                row["ordinal"] = index + 1
                record_handshake(row, game.startup_ms if not resident or index == 0 else 0)
                rows.append(row)
                control = expected[index] if expected is not None else seen.get(key)
                if control is not None:
                    row["matched_control"] = (bool(row.get("retirement")) and bool(control.get("retirement"))
                        and all(control.get(field) == row.get(field) for field in (
                            "semantic_sha256", "root_profile_sha256"))
                        and control["retirement"]["native_frames_sha256"]
                        == row["retirement"]["native_frames_sha256"])
                    if not row["matched_control"]:
                        row["discard_reason"] = "control_differential"
                if resident and not row.get("discard_reason"):
                    seen.setdefault(key, row)
                if row.get("discard_reason"):
                    game.engine.close(graceful=False)
                    row["discard_exit_code"] = game.engine.proc.returncode
                if journal is not None:
                    bank.atomic(journal / f"{index + 1:04d}.json", row)
                if resident and row.get("discard_reason"):
                    break
    return dict(resident=resident, planned=len(order), elapsed_ms=bank.elapsed(started), rows=rows)


def faults(output, spec):
    outcomes = {}
    for key in ("active_reset", "cancel", "timeout"):
        clock = perf_counter()
        try:
            with session(output) as game:
                game.request("synthetic_start", spec=spec)
                if key == "active_reset":
                    game.request("b1a_reset")
                else:
                    cancel = Timer(.25, game.cancelled.set) if key == "cancel" else None
                    if cancel:
                        cancel.start()
                    try:
                        game.request("b1b_fault_delay")
                    finally:
                        if cancel:
                            cancel.cancel()
        except ERRORS as error:
            if key == "cancel" and not isinstance(error, bank.f1.i2.engine_client.EngineCancelled):
                raise
            if key == "timeout" and not isinstance(error, TimeoutError):
                raise
            if key == "active_reset" and "Reset requires an idle, settled map boundary" not in str(error):
                raise
            outcomes[key] = dict(failure=bank.failure(error), elapsed_ms=bank.elapsed(clock),
                                 exit_code=game.engine.proc.returncode)
        else:
            raise ValueError(f"Fault request unexpectedly completed: {key}")
    return outcomes


def main():
    import sys

    if sys.argv[1:2] == ["produce"]:
        if "--legacy" not in sys.argv[2:]:
            load("s3a_production", HERE.parent / "m1-s3a/produce.py").main()
            return
        sys.argv.remove("--legacy")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("pilot", "sequence", "faults", "produce"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--input", type=Path, default=HERE / "inputs.json")
    args = parser.parse_args()
    manifest = bank.read(args.input)
    equal("manifest version", 1, manifest["input_schema"])
    cases = {r["id"]: r for r in manifest["cases"]}
    order = manifest["pilot" if args.mode == "pilot" else "sequence"]
    if len(cases) != len(manifest["cases"]) or not order or set(order) - cases.keys():
        raise ValueError("Expected unique cases and a sequence of known IDs")
    for case in cases.values():
        validate(case["spec"])
    references = {}
    if args.mode != "produce":
        selection = bank.read(f5b.F5A / "selection.json")
        ids = {case["source_case"] for case in cases.values()}
        selection.update(selection=[r for r in selection["selection"] if r["split"] == "development"
                                    and r["id"] in ids], pilot=[])
        if {r["id"] for r in selection["selection"]} != ids:
            raise ValueError("Benchmark requires frozen development roots")
        _, done = f5b.s2c.inputs(f5b.s2c.ROOT / "logs/m1-s2b/formal", selection, "all")
        for key, case in cases.items():
            references[key] = done[case["source_case"]]["root"]
            equal("frozen artificial input", references[key]["spec"], case["spec"])
    args.output.mkdir(parents=True, exist_ok=False)
    versions = bank.versions_for_host(args.output, HOST)
    data = dict(schema=1, versions=versions, config=dict(policy="F3B-C/F4-fixed", cap=CAP,
                active_potions=False, offline_oracle=True, uses_hidden_rng=True), mode=args.mode)
    path = args.output / "results.json"
    if args.mode == "faults":
        data["faults"] = faults(args.output, cases[order[0]]["spec"])
    elif args.mode == "produce":
        journal = args.output / "records"
        journal.mkdir()
        bank.atomic(args.output / "contract.json", data)
        data["resident"] = batch(args.output, order, cases, references, True, journal=journal)
    else:
        data["cold"] = batch(args.output, order, cases, references, False)
        bank.atomic(path, data)
        data["resident"] = batch(args.output, order, cases, references, True, data["cold"]["rows"])
    bank.atomic(path, data)
    resident = data.get("resident")
    if resident and (len(resident["rows"]) != len(order)
                     or any(row.get("discard_reason") for row in resident["rows"])):
        raise SystemExit("Resident batch stopped at a failed or unsafe root. See results.json.")


if __name__ == "__main__":
    main()
