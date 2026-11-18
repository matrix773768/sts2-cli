"""Generate, audit and label an append-only bank of native synthetic combats."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from functools import partial
import gzip
import importlib.util
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic, perf_counter

HERE = Path(__file__).resolve().parent
VERSION = "m1-s2b-v1"
SCHEMA = 1
SPLITS = ("development", "validation", "test")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generator = load_module("s2a_generator", HERE.parent / "m1-s2a/generate.py")
quality = load_module("f4_label", HERE.parent / "m1-f4/run.py")
synth, bank, f3a, f3b = quality.synth, quality.bank, quality.f3a, quality.f3b
ERRORS = (*bank.ERRORS, TimeoutError)


def planned(config, cohort, replicas, catalog, versions):
    if config["schema"] != SCHEMA or not 1 <= replicas <= 256:
        raise ValueError("Invalid cohort schema or repeat count")
    if len({e["id"] for e in config["encounters"]}) != len(config["encounters"]):
        raise ValueError("Each encounter must belong to exactly one split")
    profiles = list(config["profiles"])
    if not profiles:
        raise ValueError("At least one resource profile is required")
    cases, keys = [], {}
    for replica in range(replicas):
        for i, (name, rule) in enumerate(config["rules"].items()):
            for j, encounter in enumerate(config["encounters"]):
                if cohort == "pilot" and not encounter["pilot"]:
                    continue
                if encounter["split"] not in SPLITS:
                    raise ValueError("Unknown split")
                profile = profiles[(i + j + replica // 2) % len(profiles)]
                encounter_id = encounter["id"]
                native_profile = config["profiles"][profile] | {
                    "act": encounter["act"], "act_variant": encounter["act_variant"],
                    "encounters": [encounter_id]}
                inputs = {"rules": config["rules"], "generator_seed": config["generator_seed"],
                          "profiles": {profile: native_profile}}
                generated = generator.generate_case(inputs, name, profile, catalog,
                    instance=[VERSION, cohort, encounter_id, replica])
                case_id = bank.stamp([VERSION, cohort, name, encounter_id, replica])
                keys[name, encounter_id, replica] = case_id
                cases.append(generated | dict(id=case_id, rule=name, replica=replica,
                    generator=VERSION, synthetic=True, native_reachable="unknown",
                    split=encounter["split"], family=[rule["character"], name, encounter_id]))
    evaluation = [keys[tuple(key)] for key in config["evaluation"][cohort]]
    if len(set(evaluation)) != len(evaluation):
        raise ValueError("Duplicate evaluation picks")
    return dict(schema=SCHEMA, generator=VERSION, cohort=cohort, config=config,
                config_sha256=bank.stamp(config), catalog_sha256=bank.stamp(catalog),
                versions=versions, cases=cases, evaluation_ids=evaluation)


def pinned(path, proposed, extend):
    if path.exists():
        current = bank.read(path)
        if current == proposed:
            return
        old, new = current["cases"], proposed["cases"]
        header = {k: v for k, v in current.items() if k != "cases"}
        if (not extend or len(old) >= len(new) or new[:len(old)] != old
                or header != {k: v for k, v in proposed.items() if k != "cases"}):
            raise ValueError("Frozen plan differs; --extend only appends replicas under the same contract")
    bank.atomic(path, proposed)


def read_archive(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def archive(path, data, limits):
    payload = gzip.compress(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode(), mtime=0)
    limits.check(len(payload))
    stage = path.with_suffix(".tmp")
    with stage.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    stage.replace(path)


def envelope(record):
    return {"sha256": bank.stamp(record), "record": record}


def checked(path):
    data = read_archive(path)
    if data["sha256"] != bank.stamp(data["record"]):
        raise ValueError(f"Payload hash mismatch: {path}")
    return data["record"]


def native_key(root):
    return bank.stamp([root["versions"]["native_identity"], root["identity"]["live"]])


def records(directory, plan):
    by_id = {case["id"]: case for case in plan["cases"]}
    result = {}
    for path in sorted((directory / "roots").glob("*.json.gz")):
        row = checked(path)
        case = by_id.get(path.name.removesuffix(".json.gz"))
        if case is None or row["case"] != case:
            raise ValueError(f"Artifact does not match frozen candidate: {path}")
        root = row.get("root")
        if row["status"] == "verified" and (
                root is None or root["spec"] != case["spec"] or root["versions"] != plan["versions"]
                or root["native_reachable"] != "unknown" or not root["synthetic"]
                or not root["native_verified"] or root["level"] != "L0"
                or len(row["audit"]["rebuilds"]) != 2
                or root["identity"]["live"] != bank.f1.digest(root["native"]["continuation"].encode())
                or row["native_key"] != native_key(root)):
            raise ValueError(f"Native root integrity check failed: {path}")
        result[case["id"]] = row
    return result


def validate_ownership(plan, done):
    for field in ("spec_sha256", "native_key"):
        keys = set()
        for case in plan["cases"]:
            row = done.get(case["id"], {})
            if row.get("status") != "verified":
                continue
            key = case[field] if field == "spec_sha256" else row[field]
            if key in keys:
                raise ValueError(f"Verified root duplicate: {case['id']}")
            keys.add(key)
    for key, row in done.items():
        if row["status"] not in ("duplicate_spec", "duplicate_live"):
            continue
        owner = done.get(row["duplicate_of"], {})
        field = "spec_sha256" if row["status"] == "duplicate_spec" else "native_key"
        left, right = ((row["case"], owner.get("case", {})) if field == "spec_sha256" else (row, owner))
        if not left.get(field) or left[field] != right.get(field) or key == row["duplicate_of"]:
            raise ValueError(f"Invalid deduplication record: {key}")


def disk_size(directory):
    total = 0
    for folder, _, names in os.walk(directory):
        for name in names:
            try:
                total += (Path(folder) / name).stat().st_size
            except FileNotFoundError:
                # Another worker may have removed its temporary directory.
                continue
    return total


def bounded_metadata(path, value, limits):
    encoded = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    size = len(encoded.replace("\n", os.linesep).encode())
    if disk_size(limits.directory) + size <= limits.disk_bytes:
        bank.atomic(path, value)
    else:
        print(f"disk limit prevented writing {path.name}; root artifacts remain resumable", flush=True)


class BatchStop(Exception):
    pass


class Limits:
    def __init__(self, directory, args, memory):
        self.directory = directory
        self.deadline = monotonic() + args.batch_seconds
        self.case_seconds = args.case_seconds
        self.disk_bytes = args.disk_mib * 1024**2
        self.memory_bytes = args.memory_mib * 1024**2
        self.memory = memory
        self.cancelled = Event()

    def check(self, extra=0, *, disk=True):
        reason = None
        if monotonic() >= self.deadline:
            reason = "batch_timeout"
        elif (self.memory.batch_peak or 0) > self.memory_bytes:
            reason = "memory_limit"
        elif disk:
            used = disk_size(self.directory)
            if used + extra > self.disk_bytes:
                reason = "disk_limit"
        if reason:
            self.cancelled.set()
            raise BatchStop(reason)

    def session(self, output, deadline):
        return bank.Session(output, min(self.deadline, deadline), self.cancelled, self.memory)

    def factory(self):
        return partial(self.session, deadline=monotonic() + self.case_seconds)


def native_files(output):
    def fail_unless_removed(error):
        # Parallel collectors remove their isolated process directories on exit.
        if not isinstance(error, FileNotFoundError):
            raise error

    return [name for _, _, files in os.walk(output, onerror=fail_unless_removed)
            for name in files if name.lower().endswith((".save", ".save.json", ".mcr"))]


def generate_one(scratch, case, versions, limits):
    with TemporaryDirectory(dir=scratch) as folder:
        output = Path(folder)
        try:
            root, audit = synth.verified_variant(output, case["spec"], versions, session=limits.factory())
            row = dict(status="verified", root=root, audit=audit, native_key=native_key(root))
        except f3a.Difference as error:
            row = dict(status="strict_difference", phase=error.phase,
                       expected_sha256=bank.stamp(error.expected), actual_sha256=bank.stamp(error.actual))
        except ERRORS as error:
            row = bank.failure(error)
        if native_files(output):
            row = dict(status="unexpected_native_persistence", files=native_files(output))
        return row | dict(case=case)


def catalogs(scratch, limits):
    with TemporaryDirectory(dir=scratch) as folder:
        output = Path(folder)
        session = limits.factory()
        with session(output) as first:
            catalog = first.request("synthetic_catalog")
        with session(output) as second:
            f3a.equal("independent native catalog", catalog, second.request("synthetic_catalog"))
        f3a.equal("catalog disk isolation", [], native_files(output))
    return catalog


def summary(plan, done):
    rows = []
    for case in plan["cases"]:
        spec = case["spec"]
        result = done.get(case["id"], {"status": "pending"})
        row = {key: case[key] for key in ("id", "split", "rule", "profile", "case_seed", "spec_sha256")}
        row.update({key: spec[key] for key in ("character", "act", "act_variant", "encounter", "seed", "hp")})
        row["status"] = result["status"]
        if "root" in result:
            row.update(root_id=result["root"]["id"], live=result["root"]["identity"]["live"])
        elif row["status"] != "pending":
            row["detail"] = {key: val for key, val in result.items() if key != "case"}
        rows.append(row)
    verified = [row for row in rows if row["status"] == "verified"]
    dimensions = ("split", "rule", "profile", "character", "act", "encounter")
    return dict(schema=SCHEMA, generator=VERSION, cohort=plan["cohort"], versions=plan["versions"],
                plan_sha256=bank.stamp(plan), evaluation_ids=plan["evaluation_ids"],
                synthetic=True, native_reachable="unknown", rows=rows,
                status_counts=dict(Counter(row["status"] for row in rows)),
                coverage={key: dict(Counter(str(row[key]) for row in verified)) for key in dimensions})


def under_budget(limits, future):
    while True:
        limits.check()
        try:
            return future.result(timeout=0.25)
        except FutureTimeout:
            if future.done():
                return future.result()


def generate(directory, config, args, versions):
    roots, scratch = directory / "roots", directory / ".work"
    roots.mkdir(exist_ok=True)
    scratch.mkdir(exist_ok=True)
    clock = perf_counter()
    mode = args.cohort
    replicas = args.replicas if args.replicas is not None else config["cohorts"][mode]
    done, published, reason = {}, [], "complete"
    plan, planning_ms = None, None
    with bank.MemorySampler() as memory:
        limits = Limits(directory, args, memory)
        try:
            limits.check()
            catalog = catalogs(scratch, limits)
            started = perf_counter()
            plan = planned(config, mode, replicas, catalog, versions)
            limits.check(2 * len(json.dumps(plan).encode()))
            pinned(directory / "plan.json", plan, args.extend)
            done = records(directory, plan)
            validate_ownership(plan, done)
            planning_ms = bank.elapsed(started)
            pending = [case for case in plan["cases"] if case["id"] not in done]
            existing = {row["case"]["spec_sha256"]: key for key, row in done.items()
                        if row["status"] == "verified"}
            live = {row["native_key"]: key for key, row in done.items() if row["status"] == "verified"}
            source = iter(pending)
            queue = []
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                try:
                    while True:
                        while len(queue) < args.workers and (case := next(source, None)) is not None:
                            limits.check()
                            duplicate = existing.get(case["spec_sha256"])
                            future = None if duplicate else pool.submit(generate_one, scratch, case, versions, limits)
                            queue.append((case, future))
                        if not queue:
                            break
                        case, future = queue.pop(0)
                        case_id, spec_key = case["id"], case["spec_sha256"]
                        row = under_budget(limits, future) if future else None
                        if spec_key in existing:
                            row = dict(case=case, status="duplicate_spec", duplicate_of=existing[spec_key])
                        elif row["status"] == "verified":
                            key = row["native_key"]
                            if key in live:
                                row = dict(case=case, status="duplicate_live", duplicate_of=live[key],
                                           native_key=key)
                            else:
                                existing[spec_key] = live[key] = case_id
                        archive(roots / f"{case_id}.json.gz", envelope(row), limits)
                        done[case_id] = row
                        published.append(row)
                        if len(published) % 16 == 0:
                            print("generated", len(done), "/", len(plan["cases"]), flush=True)
                finally:
                    limits.cancelled.set()
        except BatchStop as stop:
            reason = str(stop)
        except KeyboardInterrupt:
            reason = "interrupt"
    if planning_ms is not None:
        bounded_metadata(directory / "index.json", summary(plan, done), limits)
    timing = [t for row in published if "audit" in row for t in row["audit"]["rebuilds"]]
    statistics = dict(stop=reason, workers=args.workers, new_records=len(published),
                      cold_rebuilds=len(timing), planning_ms=planning_ms, elapsed_ms=bank.elapsed(clock),
                      peak_working_set_bytes=memory.batch_peak, memory_samples=memory.samples,
                      reconstruction_ms={k: sum(t[k] for t in timing) for k in (
                          "root_ms", "handshake_ms", "initialize_ms", "snapshot_ms")},
                      largest_worker_bytes=max((t["peak_working_set_bytes"] for t in timing), default=None))
    report = directory / "batches.json"
    bounded_metadata(report, (bank.read(report) if report.exists() else []) + [statistics], limits)
    print(json.dumps(statistics), flush=True)

def prepare_plan(directory):
    plan = bank.read(directory / "plan.json")
    if (plan["schema"] != SCHEMA or plan["generator"] != VERSION
            or plan["config_sha256"] != bank.stamp(plan["config"])
            or len({case["id"] for case in plan["cases"]}) != len(plan["cases"])
            or any(case["spec_sha256"] != bank.stamp(case["spec"]) for case in plan["cases"])):
        raise ValueError("Frozen plan integrity check failed")
    return plan


def proof_level(trials):
    if any(n.get("status") == "win" and n.get("strict_terminal")
           and n.get("root_verified") for n in (t.get("verification", {}) for t in trials)):
        return "L3"
    if any(t["status"] == "predicted_win" for t in trials):
        return "L2"
    return "L0"


def store_label(path, result, limits):
    if native_files(limits.directory):
        raise ValueError("Bank contains an unexpected native save or replay")
    archive(path, envelope(result), limits)


def label_id(case_id, policy, cap, versions, code):
    return bank.stamp([VERSION, case_id, policy, cap, versions, code])


def label_one(directory, case, root, cap, algorithm, limits, code):
    labels = directory / "labels"
    case_id = case["id"]
    versions = root["versions"]
    ids = {policy: label_id(case_id, policy, cap, versions, code) for policy in ("f3b", "f4")}
    paths = {policy: labels / f"{value}.json.gz" for policy, value in ids.items()}
    if paths["f3b"].exists() and (algorithm == "f3b" or paths["f4"].exists()):
        return [checked(paths[policy]) for policy in ("f3b", "f4")
                if policy == "f3b" or algorithm != "f3b"]

    def identify(policy):
        return dict(id=ids[policy], root_id=root["id"], case_id=case_id, split=case["split"],
                    policy=policy, cap=cap, versions=versions, implementation=code,
                    offline_oracle=True, uses_hidden_rng=True, active_potions=False)

    session = limits.factory()
    restore = partial(synth.rebuild, session=session)
    if any(c["id"] == "NEUTRALIZE" for c in root["spec"]["deck"]):
        restore = partial(quality.native_neutralize, restore=restore)
    with TemporaryDirectory(dir=directory / ".work") as folder:
        stage = Path(folder)
        if paths["f3b"].exists():
            baseline = checked(paths["f3b"])
        else:
            control = f3b.run_cell(stage, root, "C", False, cap, restore=restore,
                                   charge_fixed=True, keep_frames=True)
            trials = quality.history(stage / control["history"])
            level = proof_level(trials)
            selected = None
            if level == "L3":
                win = trials[-1]
                selected = dict(key=win["winner_key"], resources=quality.accepted_resources(win["verification"]))
            baseline = identify("f3b") | dict(status=control["status"], level=level, selected=selected,
                                               win_feasibility="confirmed" if level == "L3" else "unknown",
                                               cell=control, trials=trials, total_charged=control["total_charged"])
            limits.check()
            store_label(paths["f3b"], baseline, limits)
        if algorithm == "f3b":
            return [baseline]
        if baseline["level"] == "L3":
            refined = quality.refine(stage, root, baseline["trials"][-1], baseline["total_charged"],
                                     cap, restore, {}, keep_frames=True)
            evidence = {name: quality.history(stage / filename) for name, filename in (
                ("prediction", "quality.json.gz"), ("native", "native-evidence.json.gz"))
                if (stage / filename).exists()}
            result = dict(status="native_win", level="L3", selected=refined["selected"],
                          refinement=refined, evidence=evidence, total_charged=refined["total_charged"])
        else:
            result = {key: baseline[key] for key in ("status", "level", "selected", "total_charged")}
        result |= identify("f4") | {"control_label": baseline["id"],
                                    "win_feasibility": baseline["win_feasibility"]}
        limits.check()
        store_label(paths["f4"], result, limits)
        return [baseline, result]


def verify_labels(directory, plan, done):
    labels = {}
    for path in (directory / "labels").glob("*.json.gz"):
        label = checked(path)
        case = done.get(label["case_id"], {})
        root = case.get("root", {})
        if (label["id"] != path.name.removesuffix(".json.gz") or not root
                or label["root_id"] != root["id"] or label["split"] != case["case"]["split"]
                or label["versions"] != plan["versions"] or not label["offline_oracle"]
                or not label["uses_hidden_rng"] or not 0 <= label["total_charged"] <= label["cap"]
                or label_id(label["case_id"], label["policy"], label["cap"], plan["versions"],
                            label["implementation"]) != label["id"]):
            raise ValueError(f"Invalid label identity or budget: {path}")
        labels[label["id"]] = label
    for label in labels.values():
        if label["policy"] == "f3b":
            if label["level"] != proof_level(label["trials"]):
                raise ValueError(f"Invalid F3B level: {label['id']}")
            routes = {t.get("winner_key"): t.get("verification", {}) for t in label["trials"]}
        elif label["policy"] == "f4":
            control = labels[label["control_label"]]
            if (control["policy"] != "f3b" or label["case_id"] != control["case_id"]
                    or label["cap"] != control["cap"] or label["level"] != control["level"]
                    or label["implementation"] != control["implementation"]
                    or label["total_charged"] < control["total_charged"]):
                raise ValueError(f"Invalid control label: {label['id']}")
            routes = {t.get("winner_key"): t.get("verification", {}) for t in control["trials"]}
            routes.update({e["key"]: e["native"] for e in label.get("evidence", {}).get("native", [])})
        else:
            raise ValueError(f"Unknown policy: {label['policy']}")
        if label["level"] == "L3":
            native = routes[label["selected"]["key"]]
            plan_frames = native["fixed_plan"]["frames"]
            trace = native["trace"]
            if (native["status"] != "win" or not native["root_verified"] or not native["strict_terminal"]
                    or not 0 < len(trace) == native["matched_actions"] == len(plan_frames)
                    or not trace[-1]["terminal"] or any(
                        s["expected_sha256"] != s["actual_sha256"] or
                        f3a.frame_hash(frame) != s["expected_sha256"]
                        for frame, s in zip(plan_frames, trace))
                    or quality.accepted_resources(native) != label["selected"]["resources"]):
                raise ValueError(f"Invalid L3 native evidence: {label['id']}")
    return labels


def label_bank(directory, plan, done, args, versions):
    f3a.equal("label binaries", plan["versions"], versions)
    labels, scratch = directory / "labels", directory / ".work"
    labels.mkdir(exist_ok=True)
    scratch.mkdir(exist_ok=True)
    pick = list(dict.fromkeys(args.root or plan["evaluation_ids"]))
    catalog = {case["id"]: case for case in plan["cases"]}
    if any(case_id not in catalog for case_id in pick):
        raise ValueError("Requested label root is outside the frozen plan")
    cap = args.budget or plan["config"]["evaluation"]["budget"]
    code = bank.stamp([bank.f1.digest(file.read_bytes()) for file in (
        Path(__file__), Path(quality.__file__), Path(f3b.__file__))])
    clock = perf_counter()
    outputs = []
    with bank.MemorySampler() as memory, ThreadPoolExecutor(max_workers=1) as pool:
        limits = Limits(directory, args, memory)
        try:
            for case_id in pick:
                limits.check()
                case = catalog[case_id]
                if done.get(case_id, {}).get("status") != "verified":
                    outputs.append(dict(case_id=case_id, split=case["split"], status="root_unavailable"))
                    continue
                job = pool.submit(label_one, directory, case, done[case_id]["root"],
                                  cap, args.algorithm, limits, code)
                reports = under_budget(limits, job)
                for label in reports:
                    extract = {key: label[key] for key in (
                        "id", "case_id", "split", "policy", "cap", "level", "status", "selected", "total_charged")}
                    if label["policy"] == "f3b":
                        extract["search_ms"] = label["cell"]["hot_ms"]
                        extract["wall_ms"] = label["cell"]["wall_ms"]
                        extract["native_attempts"] = len([t for t in label["trials"] if "verification" in t])
                        extract["native_status"] = [t["verification"]["status"] for t in label["trials"]
                                                    if "verification" in t]
                        extract["first_prediction"] = label["cell"]["first_prediction"]
                        extract["first_native"] = label["cell"]["first_native"]
                    elif "refinement" in label:
                        refine = label["refinement"]
                        extract["wall_ms"] = refine["elapsed_ms"]
                        extract["refinement_status"] = refine["quality_status"]
                        extract["native_attempts"] = len(refine["validation"])
                        extract["native_status"] = [t["status"] for t in refine["validation"]]
                    outputs.append(extract)
                    print(case["rule"], case["spec"]["encounter"], label["policy"], label["status"],
                          label["level"], label["total_charged"], flush=True)
            status = "complete"
        except (BatchStop, KeyboardInterrupt) as error:
            status = str(error) if isinstance(error, BatchStop) else "interrupt"
        finally:
            limits.cancelled.set()
    verify_labels(directory, plan, done)
    report = dict(status=status, labels=outputs, elapsed_ms=bank.elapsed(clock),
                  peak_working_set_bytes=memory.batch_peak)
    bounded_metadata(directory / "last-label-run.json", report, limits)
    print(json.dumps({key: value for key, value in report.items() if key != "labels"}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("generate", "verify", "label"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--config", type=Path, default=HERE / "config.json")
    parser.add_argument("--cohort", choices=("pilot", "formal"), default="formal")
    parser.add_argument("--replicas", type=int)
    parser.add_argument("--extend", action="store_true")
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--memory-mib", type=int, default=900)
    parser.add_argument("--disk-mib", type=int, default=512)
    parser.add_argument("--case-seconds", type=int, default=100)
    parser.add_argument("--batch-seconds", type=int, default=900)
    parser.add_argument("--algorithm", choices=("f3b", "f4", "compare"), default="compare")
    parser.add_argument("--budget", type=int, choices=range(1, 2049), metavar="1..2048")
    parser.add_argument("--root", action="append")
    args = parser.parse_args()
    if min(args.memory_mib, args.disk_mib, args.case_seconds, args.batch_seconds) <= 0:
        parser.error("resource and time budgets must be positive")
    directory = args.directory.resolve()
    if args.operation == "generate":
        directory.mkdir(parents=True, exist_ok=True)
    sys.addaudithook(f3b.deny_reference_open)
    with bank.writer(directory):
        if args.operation == "generate":
            versions = bank.versions_for_host(directory, quality.HOST) | {
                "synthetic_spec": 2, "initializer": "m1-s2a-v1"}
            generate(directory, bank.read(args.config), args, versions)
        else:
            plan = prepare_plan(directory)
            done = records(directory, plan)
            validate_ownership(plan, done)
            f3a.equal("bank disk isolation", [], native_files(directory))
            if args.operation == "label":
                versions = bank.versions_for_host(directory, quality.HOST) | {
                    "synthetic_spec": 2, "initializer": "m1-s2a-v1"}
                label_bank(directory, plan, done, args, versions)
            else:
                index = summary(plan, done)
                if (directory / "index.json").exists():
                    f3a.equal("derived bank index", index, bank.read(directory / "index.json"))
                labels = verify_labels(directory, plan, done)
                print(json.dumps({"roots": index["status_counts"], "coverage": index["coverage"],
                    "labels": dict(Counter(label["level"] for label in labels.values())),
                    "disk_bytes": disk_size(directory)}, indent=2))


if __name__ == "__main__":
    main()
