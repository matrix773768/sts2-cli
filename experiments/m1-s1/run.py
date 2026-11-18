"""Independently reconstruct synthetic roots and validate one frozen F3B route."""
import argparse
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
from threading import Event
from time import monotonic, perf_counter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-d1"))
import bank

module = importlib.util.spec_from_file_location("s1_f3b", HERE.parent / "m1-f3b/benchmark.py")
f3b = importlib.util.module_from_spec(module)
module.loader.exec_module(f3b)
f3a = f3b.f3a
HOST = "m1-s1-build"
CAP = 128
ROOT_KIND = "synthetic"


def capture(game, spec):
    clock = perf_counter()
    public = game.request("synthetic_start", spec=spec)
    start_ms = bank.elapsed(clock)
    f3a.equal("native play phase", "combat_play", public["decision"])
    f3a.equal("synthetic floor", 0, public["context"]["floor"])
    clock = perf_counter()
    snapshot = game.request("synthetic_snapshot")
    identity = game.request("f1_begin")
    snapshot_ms = bank.elapsed(clock)
    if spec["schema"] == 2:
        f3a.equal("synthetic act context",
                  (spec["act"], spec["act"], spec["act_variant"], snapshot["act_boss"]),
                  (public["context"]["act"], snapshot["act"], snapshot["act_variant"],
                   public["context"]["boss"]["id"]))
    resource = identity["resources"]
    pots = spec["potions"] + [None] * (len(resource["potions"]) - len(spec["potions"]))
    actual = (snapshot["seed"], snapshot["character"], snapshot["ascension"], identity["encounter"],
              snapshot["deck"], resource["hp"], resource["max_hp"], resource["relics"], resource["potions"])
    expected = (spec["seed"], spec["character"].upper(), spec["ascension"], spec["encounter"],
                spec["deck"], spec["hp"], spec["max_hp"], spec["relics"], pots)
    f3a.equal("synthetic loadout", expected, actual)
    f3a.equal("non-saving/no history", (False, False, 0), (
        snapshot["should_save"], snapshot["replay_writer_enabled"], snapshot["visited_map_nodes"]))
    for rng in (snapshot["run_rng"], snapshot["player_rng"]):
        streams = rng["rngs"]
        if not streams or any(set(values) != {"counter", "s0", "s1", "s2", "s3"}
                              for values in streams.values()):
            raise RuntimeError("Incomplete native RNG state")
    f3a.equal("native continuation digest", identity["live"],
              bank.f1.digest(snapshot["continuation"].encode("utf-8")))
    return dict(public_root=public, native=snapshot, identity=identity), dict(
        handshake_ms=game.startup_ms, initialize_ms=start_ms, snapshot_ms=snapshot_ms,
        root_ms=game.startup_ms + start_ms + snapshot_ms,
        peak_working_set_bytes=game.report["peak_working_set_bytes"])


def new_session(output):
    return bank.Session(output, monotonic() + 35, Event())


def sample(output, spec, versions, actions=0, *, session=new_session):
    with session(output) as game:
        surfaces, timing = capture(game, spec)
        root = dict(surfaces, id="synthetic-" + bank.stamp([spec, versions, surfaces["identity"]["live"]]),
                    spec=spec, versions=versions, source=ROOT_KIND, synthetic=True,
                    native_reachable="unknown" if spec["schema"] == 2 else False,
                    native_verified=False, level="unverified")
        frames = []
        clock = perf_counter()
        for tick in range(1, actions + 1):
            row = game.request("f1_step", step=tick, audit=True)
            f3a.equal("fallback choice failure", None, row["choice_failure"])
            frames.append({key: row[key] for key in (
                "action", "decision", "pre_audit", "post_audit", "choice_requests", "choice_checks")})
            if row["decision"]["decision"] != "combat_play":
                break
        if actions:
            timing["legal_action_ms"] = bank.elapsed(clock)
        timing["peak_working_set_bytes"] = game.report["peak_working_set_bytes"]
    return root, timing, frames


def verified_variant(output, spec, versions, actions=0, *, session=new_session):
    first, time_a, frames_a = sample(output, spec, versions, actions, session=session)
    second, time_b, frames_b = sample(output, spec, versions, actions, session=session)
    f3a.equal("independent synthetic root", first, second)
    f3a.equal("native legal action differential", frames_a, frames_b)
    f3a.equal("legal action coverage", actions, len(frames_a))
    first.update(native_verified=True, level="L0")
    return first, dict(rebuilds=[time_a, time_b], legal_action_frames=frames_a)


@contextmanager
def rebuild(output, root, *, session=new_session):
    if root["source"] != ROOT_KIND or not root["native_verified"] or root["native_reachable"] not in (False, "unknown"):
        raise ValueError("Expected an independently verified synthetic root")
    if bank.f1.digest(bank.f1.DLL.read_bytes()) != root["versions"]["headless_sha256"]:
        raise ValueError("Synthetic host binary differs from the recorded root")
    with session(output) as game:
        surfaces, _ = capture(game, root["spec"])
        f3a.equal("reconstructed source", {key: root[key] for key in surfaces}, surfaces)
        yield game, surfaces["public_root"]


def verify_f3b(output, root):
    report = dict(arm="C", cap=CAP, potions=False, uses_hidden_rng=True, status="not_run")
    clock = perf_counter()
    try:
        result = f3b.search(output, root, "C", False, CAP, [], restore=rebuild)
        f3b.save_history(output / "f3b-private.json.gz", result)
        report.update(search_status=result["status"], status=result["status"],
                      search_ms=bank.elapsed(clock), transitions=result["transitions"],
                      search_hot_ms=result.get("hot_ms"), search_peak_working_set_bytes=result.get("peak_working_set_bytes"),
                      prediction_prepare_ms=result.get("prediction_prepare_ms"))
        if result["status"] == "predicted_win":
            prep, plan = f3b.prepare_native(output, root, result, restore=rebuild)
            report["fixed_prediction"] = prep
            report["status"] = prep["status"]
            if plan is not None:
                row = report["native_replay"] = {}
                report["actions"] = plan["actions"]
                clock = perf_counter()
                with rebuild(output, root) as (game, state):
                    f3a.replay_live(game, state, plan, row)
                    row["peak_working_set_bytes"] = game.report["peak_working_set_bytes"]
                row["elapsed_ms"] = bank.elapsed(clock)
                report["status"] = row["status"]
                if row["status"] == "win" and row["strict_terminal"]:
                    root["level"] = "L3"
    except f3a.Difference as error:
        report.update(status="strict_difference", phase=error.phase,
                      expected_sha256=bank.stamp(error.expected), actual_sha256=bank.stamp(error.actual))
    except (AssertionError, *bank.ERRORS) as error:
        report.update(bank.failure(error))
    return report


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("output", type=Path)
    cli.add_argument("--cases", type=Path, default=HERE / "cases.json")
    args = cli.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True)
    sys.addaudithook(f3b.deny_reference_open)
    versions = bank.versions_for_host(out, HOST) | {"synthetic_spec": 1, "initializer": "m1-s1-v1"}
    cases = bank.read(args.cases)
    clock = perf_counter()
    samples = {}
    for name in ("base", "seed", "upgrade"):
        spec = cases[name]
        root, audit = verified_variant(out, spec, versions, actions=3 if name == "base" else 0)
        samples[name] = dict(root=root, audit=audit)
        print(name, root["identity"]["live"][:16], "independent match", flush=True)
    base, seed, upgrade = (samples[k]["root"] for k in ("base", "seed", "upgrade"))
    f3a.equal("seed-only spec delta", base["spec"] | {"seed": seed["spec"]["seed"]}, seed["spec"])
    if (base["native"]["run_rng"]["rngs"] == seed["native"]["run_rng"]["rngs"]
            or base["native"]["player_rng"]["rngs"] == seed["native"]["player_rng"]["rngs"]
            or base["identity"]["live"] == seed["identity"]["live"]):
        raise RuntimeError("Changed seed did not change native RNG and continuation")
    f3a.equal("upgrade-only spec delta", base["spec"] | {"deck": upgrade["spec"]["deck"]}, upgrade["spec"])
    f3a.equal("one upgraded card", 1, sum(x != y for x, y in
        zip(base["native"]["deck"], upgrade["native"]["deck"], strict=True)))
    if base["identity"]["live"] == upgrade["identity"]["live"]:
        raise RuntimeError("Changed deck did not change native continuation")

    report = verify_f3b(out, base)
    generated_saves = [p for p in out.rglob("*") if p.is_file() and p.suffix.lower() in {".save", ".mcr"}]
    f3a.equal("no native saves or combat replay files", [], generated_saves)
    bank.atomic(out / "results.json", dict(schema=1, variants=samples, f3b=report,
                 end_to_end_ms=bank.elapsed(clock), native_save_or_replay_files=0))
    print("F3B", report["status"], report.get("transitions"), flush=True)


if __name__ == "__main__":
    main()
