"""Check independent batches and publish compact performance evidence."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

from bank import HERE, atomic, read


def compare(manifest, reference):
    fields = ("id", "context", "public_root", "identity", "entry", "history", "partition",
              "map_public_sha256", "map_edges_sha256")
    for key in ("runs", "roots"):
        assert len(manifest[key]) == len(reference[key]), key
    assert manifest["occurrences"] == reference["occurrences"]
    for root, baseline in zip(manifest["roots"], reference["roots"]):
        for field in fields:
            assert root[field] == baseline[field], (root["id"], field)
    for run, baseline in zip(manifest["runs"], reference["runs"]):
        for field in ("status", "commands", "max_act", "history", "partition"):
            assert run[field] == baseline[field], (run["id"], field)
    legacy = read(HERE.parent / "m1-f3a/manifest.json")
    known = {r["identity"]["live"]: r for r in legacy["roots"]}
    found = set()
    for root in manifest["roots"]:
        if root["identity"]["live"] in known:
            old = known[root["identity"]["live"]]
            assert root["partition"] == "development" and root["offline_teacher_assisted"]
            assert root["public_root"] == old["public_root"] and root["identity"] == old["identity"]
            found.add(root["identity"]["live"])
    assert found == known.keys()
    for run in manifest["runs"]:
        assert len({r["partition"] for r in manifest["runs"] if r["history"] == run["history"]}) == 1


def profile(directory, manifest):
    runs = manifest["runs"]
    validations = [v for v in manifest["validations"] if v["kind"] == "native_root_restore"]
    elapsed = read(directory / "index.json")["metrics"]
    phases = Counter()
    for run in runs:
        phases.update(run.get("combat_timing_ms", {}))
    phases["f1_step_rpc_residual_ms"] = (phases["f1_step_rpc_ms"] - phases["observe_ms"] -
                                       phases["decision_ms"] - phases["execute_ms"])
    return dict(batches=manifest["collection_batches"], metrics=elapsed,
                aggregate_combat_ms=dict(phases),
                aggregate_run_action_rpc_ms=sum(r.get("rpc_ms", {}).get("action", 0) for r in runs),
                median_run_handshake_ms=median(r["startup_ms"] for r in runs),
                median_cold_audit_ms=median(v["elapsed_ms"] for v in validations),
                median_load_rpc_ms=median(v["rpc_ms"]["load_save"] for v in validations),
                median_audit_handshake_ms=median(v["startup_ms"] for v in validations))


def hot_profile(result):
    rows = {k: result[k] if k == "cold" else [b for w in result[k] for b in w["branches"]]
            for k in ("cold", "hot", "batch")}
    return dict(probe_sha256=result["probe_sha256"], comparisons=result["comparisons"],
                discarded=sorted(result["faults"]),
                fixed_boundary={k: dict(samples=len(v), median_wall_ms=median(r["wall"] for r in v),
                    median_recover_ms=median(r["recover"] for r in v),
                    peak_working_set_bytes=max(r["peak"] for r in v)) for k, v in rows.items()})


def metered_profile(directory, baseline):
    manifest = read(directory / "manifest.json")
    by_live = {r["identity"]["live"]: r for r in baseline["roots"]}
    for root in manifest["roots"]:
        expected = by_live[root["identity"]["live"]]
        for field in ("public_root", "identity", "entry", "map_public_sha256", "map_edges_sha256"):
            assert root[field] == expected[field], (root["id"], field)

    rows = defaultdict(list)
    for file in (directory / "engine").glob("game-*/stderr.log"):
        for line in file.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("[D1_TIMING] "):
                _, command, *values = line.split()
                rows[command].append(tuple(map(float, values)))
    commands = Counter()
    for row in manifest["runs"] + manifest["validations"]:
        commands.update(row.get("rpc_ms", {}))
    metrics = {}
    for command in ("start_run", "load_save", "action", "f1_step", "get_map", "f1_begin"):
        samples = rows[command]
        assert samples, command
        dispatch, public, wire_json, flush = map(sum, zip(*samples))
        rpc = commands[command]
        metrics[command] = dict(samples=len(samples), dispatch_ms=dispatch, public_combat_ms=public,
                                response_json_ms=wire_json, stdout_flush_ms=flush, rpc_ms=rpc,
                                rpc_residual_ms=rpc - dispatch - wire_json - flush)
    return dict(roots=len(manifest["roots"]), headless_sha256=manifest["versions"]["headless_sha256"],
                matches_uninstrumented_roots=True, commands=metrics)


def label_profile(manifest):
    first = {}
    for evaluation in manifest["evaluations"]:
        first.setdefault((evaluation["root_id"], evaluation["policy"]), evaluation)
    return {policy: dict(status=dict(Counter(r["status"] for (rid, p), r in first.items() if p == policy)),
                         elapsed_ms=sum(r["elapsed_ms"] for (rid, p), r in first.items() if p == policy),
                         median_wall_ms=median(r["elapsed_ms"] for (rid, p), r in first.items() if p == policy),
                         median_cold_root_ms=median(r["cold_root_ms"] for (rid, p), r in first.items()
                                                    if p == policy and "cold_root_ms" in r))
            for policy in {p for _, p in first}}



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial", type=Path)
    parser.add_argument("parallel", type=Path)
    parser.add_argument("hot", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--meter", type=Path)
    args = parser.parse_args()
    serial, parallel = [read(p / "manifest.json") for p in (args.serial, args.parallel)]
    compare(serial, parallel)
    result = dict(schema=1, serial=profile(args.serial, serial),
                  parallel=profile(args.parallel, parallel), fixed_boundary_probe=hot_profile(read(args.hot)),
                  serial_parallel_equal=True, first_evaluations=label_profile(parallel))
    if args.meter:
        result["metered_pilot"] = metered_profile(args.meter, parallel)
    atomic(args.output, result)
    print("Independent batches, splits and five F3A roots match")


if __name__ == "__main__":
    main()
