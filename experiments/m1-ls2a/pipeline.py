"""Discover, freeze and run bounded LS2A search campaigns."""
import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import closing
import os
from pathlib import Path
from threading import Event
from time import monotonic

from space import HERE, SCHEMA, VERSION, check_splits, digest, inventory, key, native_cases, read, synthetic
import engine
import store

bank = engine.bank


def validate_config(config):
    limits = config["limits"]
    if any(type(v) is not int or v < 1 for v in limits.values()):
        raise ValueError("Resource limits must be positive integers")
    if (type(config["synthetic_roots"]) is not int or config["synthetic_roots"] < 0
            or not config["namespace"]):
        raise ValueError("Invalid sample count or namespace")
    weights = config.get("room_weights", {})
    if any(type(w) is not int or w < 1 for w in weights.values()):
        raise ValueError("Room strata need positive integer weights")
    if len(config["split_percent"]) != 3 or sum(config["split_percent"]) != 100 or min(config["split_percent"]) < 0:
        raise ValueError("Expected three partition weights adding up to 100")
    sizes = config["deck_size"]
    if not 2 <= sizes[0] <= sizes[1] <= 40 or not 0 <= config["starter_count"][0] <= config["starter_count"][1] <= sizes[0]-2:
        raise ValueError("Deck and starter bounds cannot accommodate two native additions")
    tiers = ("standard", "quality", "candidate", "hard_escalation")
    if any(type(config[t+"_percent"]) is not int or not 0 <= config[t+"_percent"] <= 100 for t in tiers):
        raise ValueError("Tier selection percentages must be between 0 and 100")
    for tier, cap in config["profiles"].items():
        if type(cap) is not int or not 1 <= cap <= 2048 or (tier != "low" and (cap < 2 or cap % 2)):
            raise ValueError(f"Invalid Replay budget for {tier}")


def schedule(case, config):
    budget = config["profiles"]
    val = key(["tier-v1", case["id"]])
    certain = case["source"] == "native" or val % 100 < config["standard_percent"]
    quality = val // 100 % 100 < config["quality_percent"]
    probe = val // 10000 % 100 < config["candidate_percent"]
    adaptive = (not quality and not probe and certain and val // 1000000 % 100 <
                config["hard_escalation_percent"])
    profiles = [["low", "Q1", budget["low"]]]
    if certain or quality or probe:
        profiles.append(["standard", "C", budget["standard"]])
    if quality or adaptive:
        profiles.append(["quality", "C+F4", budget["quality"]])
    if probe:
        profiles.extend(["candidate", s, budget["candidate"]] for s in engine.STRATEGIES)
    return dict(profiles=profiles, adaptive=adaptive)


def make_plan(directory, name, config, catalog, versions, history_paths, existing=None):
    validate_config(config)
    native = native_cases(history_paths, ())
    prior = [] if existing is None else existing
    candidate = synthetic(catalog, config, config["synthetic_roots"], config["namespace"], [*prior, *native])
    cases = [*native, *candidate]
    check_splits([*prior, *cases])
    jobs = []
    for case in cases:
        case["schedule"] = schedule(case, config)
        profiles = case["schedule"]["profiles"]
        exact_request = (case["spec"] if case["source"] == "synthetic" else [
            case["restore"]["root"][k] for k in ("checkpoint_sha256", "entry", "identity")
        ])
        jobs.append(dict(id=case["id"], case=case, reserved=sum(p[2] for p in profiles),
                         cache=digest([versions, digest(catalog), case["source"], exact_request,
                                       case["schedule"], config["protocol"], case["split"]])))
    if sum(j["reserved"] for j in jobs) > config["limits"]["transitions"]:
        raise ValueError("Frozen campaign's first-attempt reservations exceed transition budget")
    if len({j["cache"] for j in jobs}) != len(jobs):
        raise ValueError("Duplicate exact requests in one plan")
    return dict(schema=SCHEMA, sampler=VERSION, name=name, config=config, versions=versions,
                catalog_sha256=digest(catalog), jobs=jobs)


def disk_bytes(directory):
    size = 0
    for parent, _, names in os.walk(directory):
        for name in names:
            try:
                size += (Path(parent) / name).stat().st_size
            except FileNotFoundError:
                continue
    return size


def run(db, directory, manifest, catalog, workers, max_new=None):
    name, config, versions = (manifest[k] for k in ("name", "config", "versions"))
    limits = config["limits"]
    if not 1 <= workers <= limits["workers"]:
        raise ValueError("Worker count outside frozen limits")
    attempts_max = limits["attempts_per_root"]
    jobs = {j["id"]: j for j in manifest["jobs"]}
    stats = dict(dispatched=0, cached=0, recovered=store.recover(db, name, attempts_max), completed=0)
    previous = [store.unpack(r[0]) for r in db.execute("SELECT data FROM batches WHERE plan=?", (name,))]
    began = monotonic()
    deadline = began + max(0, limits["wall_seconds"] - sum(r["wall_seconds"] for r in previous))
    cancelled = Event()
    active = {}
    static = inventory(catalog)
    executed = 0
    reason = None
    with bank.MemorySampler() as memory, ThreadPoolExecutor(max_workers=workers) as pool:
        pending = iter(store.pending(db, name))
        while True:
            if not reason:
                if monotonic() >= deadline:
                    reason = "wall_limit"
                elif (memory.batch_peak or 0) > limits["engine_rss_mib"] * 2**20:
                    reason = "memory_limit"
                elif executed % 16 == 0 and disk_bytes(directory) > limits["disk_mib"] * 2**20:
                    reason = "disk_limit"
                if reason:
                    cancelled.set()
            while not reason and len(active) < workers:
                if max_new is not None and stats["dispatched"] >= max_new:
                    reason = "dispatch_limit"
                    break
                task = next(pending, None)
                if task is None:
                    reason = "queue_exhausted"
                    break
                id_, cache, cap = task
                if store.payload(db, cache) is not None:
                    store.reserve(db, name, id_, cap, hit=True)
                    stats["cached"] += 1
                elif store.charged(db, name) + cap > limits["transitions"]:
                    reason = "transition_limit"
                else:
                    attempt = store.reserve(db, name, id_, cap)
                    job = jobs[id_]
                    future = pool.submit(engine.execute, directory, job["case"], config,
                                         job["case"]["schedule"]["profiles"], versions, static,
                                         min(deadline, monotonic() + limits["root_seconds"]), cancelled, memory)
                    active[future] = job, attempt
                    stats["dispatched"] += 1
            if not active:
                if reason == "queue_exhausted" and (retry := store.pending(db, name)):
                    reason = None
                    pending = iter(retry)
                    continue
                break
            done, _ = wait(active, timeout=.5, return_when=FIRST_COMPLETED)
            for future in done:
                job, attempt = active.pop(future)
                result = future.result()
                state = store.finish(db, name, job, attempt, result, attempts_max)
                stats["completed"] += state == "done"
                executed += 1
                if executed % 32 == 0 or result["outcome"] != "complete":
                    print(name, executed, "settled", result["outcome"], "charged",
                          store.charged(db, name), flush=True)
    stats.update(reason=reason, wall_seconds=monotonic()-began, workers=workers,
                 aggregate_engine_rss_bytes=memory.batch_peak, memory_samples=memory.samples,
                 max_engine_peak_bytes=max(memory.process_peaks.values(), default=None),
                 disk_bytes=disk_bytes(directory), charged=store.charged(db, name))
    store.batch(db, name, stats)
    print(stats, flush=True)
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("catalog", "prepare", "run"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--config", type=Path, default=HERE / "config.json")
    parser.add_argument("--name", default="main")
    parser.add_argument("--history-bank", action="append", default=[], type=Path)
    parser.add_argument("--workers", default=1, type=int)
    parser.add_argument("--max-new", type=int)
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with bank.writer(directory):
        if args.operation == "catalog":
            versions = engine.bind(directory)
            path = directory / "catalog.json"
            value = engine.catalog(directory, versions)
            if path.exists() and read(path) != value:
                raise ValueError("Catalog drift in existing campaign")
            if not path.exists():
                bank.atomic(path, value)
            print("catalog", digest(value), flush=True)
            return
        with closing(store.open_store(directory / "search.sqlite")) as db:
            row = db.execute("SELECT manifest FROM plans WHERE plan=?", (args.name,)).fetchone()
            if args.operation == "prepare":
                if row:
                    raise ValueError("Plan already frozen. Use run to resume.")
                catalog = read(directory / "catalog.json")
                versions = engine.bind(directory)
                config = read(args.config)
                prior = [j["case"] for r in db.execute("SELECT manifest FROM plans")
                         for j in store.unpack(r[0])["jobs"]]
                manifest = make_plan(directory, args.name, config, catalog, versions,
                                     [path.resolve() for path in args.history_bank], prior)
                store.register(db, manifest, manifest["jobs"])
                print("frozen", args.name, len(manifest["jobs"]), digest(manifest), flush=True)
            else:
                if not row:
                    raise ValueError("Prepare and freeze a plan before running")
                manifest = store.unpack(row[0])
                versions = engine.bind(directory)
                catalog = read(directory / "catalog.json")
                if manifest["versions"] != versions or manifest["catalog_sha256"] != digest(catalog):
                    raise ValueError("Runtime or catalog differs from frozen campaign")
                run(db, directory, manifest, catalog, args.workers, args.max_new)


if __name__ == "__main__":
    main()
