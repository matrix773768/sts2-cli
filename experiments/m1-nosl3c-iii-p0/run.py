"""Measure one frozen v4 batch without changing the production trainer."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import platform
import runpy
import sqlite3
import sys
from threading import Lock
from time import perf_counter
from types import FunctionType
from unittest.mock import patch

START = perf_counter()
HERE = Path(__file__).resolve().parent
EXPERIMENTS = HERE.parent
IIE = EXPERIMENTS / "m1-nosl3c-iie"
sys.path.insert(0, str(IIE))
spec = importlib.util.spec_from_file_location("p0_v4", IIE / "run.py")
v4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v4)
import torch
from nosl3b_store import tensors, unpack

accept = runpy.run_path(str(EXPERIMENTS / "m1-nosl3c-iik5/accept.py"))
Meter = runpy.run_path(str(EXPERIMENTS / "m1-nosl3c-ib/resources.py"))["Meter"]
digest, save = v4.digest, v4.save_json
targets, runner = v4.targets, v4.runner
engine = targets.train_interactive.open_worker.__globals__
runner_store = runner.Journal
SOLVER = Path("logs/iik3b-solver").resolve()
HOST = accept["HOST"] / "Headless/bin/Debug/net9.0"
RESOURCE_ERRORS = runner.FAILURES
ROOT_SEED = 73192026


def config():
    cfg = json.loads((IIE / "curriculum.json").read_bytes())
    stage = cfg["stages"][0]
    stage["updates"] = 1
    stage["distribution"]["seed"] = ROOT_SEED
    cfg["stages"] = [stage]
    return cfg


def verify_main():
    base = Path("logs/iik5-main-host/bin/Debug/net9.0")
    expected = {
        "Sts2Headless.dll": "44ae4ef8309691310038a0a3f5199386e34c984198dfeda4e0f5f997161b0259",
        "GodotSharp.dll": "66cea26b3cfb7d5c4047f0b3b10e49f5ec111753cdf88475305c9ee63266e5ff",
    }
    for name, stamp in expected.items():
        if sha256((base / name).read_bytes()).hexdigest() != stamp:
            raise AssertionError(f"Regular Headless hash mismatch: {name}")
    return expected


def observe_workers(meter, events):
    binding = engine["BINDING"]
    original = binding["attested"]
    lock = Lock()

    def attested(output, stack, versions):
        begin = perf_counter()
        game, identity = original(output, stack, versions)
        proc = game.engine.proc
        args = proc.args if isinstance(proc.args, (list, tuple)) else [proc.args]
        image = next((Path(arg).resolve() for arg in args
                      if str(arg).endswith("OfflineSearchHarness.dll")), None)
        if image != HOST / "OfflineSearchHarness.dll":
            raise AssertionError(f"Unexpected native process entry: {proc.args}")
        for file, key in ((image, "headless_sha256"), (image.with_name("GodotSharp.dll"), "godot_sha256")):
            if sha256(file.read_bytes()).hexdigest() != versions[key]:
                raise AssertionError(f"Worker binary hash mismatch: {file}")
        meter.add(proc.pid)
        stack.callback(meter.retire, proc.pid)
        with lock:
            events.append(dict(pid=proc.pid, image=str(image), solver=identity,
                               startup_s=perf_counter() - begin))
        return game, identity

    return patch.dict(binding, {"attested": attested})


def in_lanes(items, function, workers):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = []
        for start in range(0, len(items), workers):
            results.extend(pool.map(function, items[start:start + workers]))
        return results


def sample(output, versions, roots, cfg):
    torch.manual_seed(cfg["initialization_seed"])
    policy = v4.Policy().eval()
    model_hash = digest(v4.checkpoint_policy(policy))
    original = targets.train_interactive.collect.__wrapped__

    def feedback(state, action):
        return v4.terminal(state, action) | {
            "engine_accounting": {"cumulative_loss": (state.get("result") or {}).get("cumulative_loss")}
        }

    collector = torch.no_grad()(FunctionType(original.__code__, original.__globals__ | {
        "project": targets.project, "Decision": targets.Decision, "MODEL": v4.MODEL, "terminal": feedback,
    }))

    def one(entry):
        index, root = entry
        seed = int(digest([cfg["policy_seed"], 0, index])[:16], 16)
        tick = perf_counter()
        try:
            return collector(output, versions, root, policy, model_hash, seed, cfg["action_cap"])
        except RESOURCE_ERRORS as error:
            return dict(rows=[], error=str(error), timing={"total_ms": (perf_counter() - tick) * 1000})

    attempts = in_lanes(list(enumerate(roots)), one, cfg["workers"])
    return model_hash, attempts


def audit(output, versions, roots, attempts, cfg):
    auditors = v4.Auditors(cfg["resident_auditor_limit"])

    def one(item):
        root, attempt = item
        if not attempt["rows"]:
            return dict(status="prediction_failure", terminal_verified=False)
        row, = attempt["rows"]
        start = perf_counter()
        candidate = row["feedback"]["status"] in ("predicted_win", "death")
        try:
            evidence = v4.certify(output, versions, root, row, auditors.audit)
        except RESOURCE_ERRORS as error:
            evidence = dict(status="audit_failure", terminal_verified=False, detail=str(error))
        return evidence | dict(eligible=runner.admitted(row, evidence), candidate=candidate,
                               audit_ms=(perf_counter() - start) * 1000)

    try:
        return in_lanes(list(zip(roots, attempts, strict=True)), one, cfg["workers"])
    finally:
        auditors.close()


def train(output, cfg, roots):
    timing = {}
    original_save = runner_store.save
    original_optimize = v4.optimize
    original_report = runner.summarize

    def checkpoint(self, step, payload, stats):
        start = perf_counter()
        original_save(self, step, payload, stats)
        timing[f"sqlite_snapshot_{step}_s"] = perf_counter() - start

    def optimize(*args):
        start = perf_counter()
        result = original_optimize(*args)
        timing.update(optimizer_s=perf_counter() - start, actual_rows=len(args[2]),
                      actual_transitions=sum(len(row["transitions"]) for row in args[2]))
        return result

    def report(*args):
        timing["pre_report_s"] = args[3]
        original_report(*args)

    frozen = {key: value for key, value in cfg.items() if key != "stages"} | {"batches": [roots]}
    with patch.object(runner_store, "save", checkpoint), patch.object(v4, "optimize", optimize), \
            patch.object(runner, "summarize", report):
        v4.run(output, SOLVER, frozen, cfg["workers"], 1)
    return timing


def verify_training(output, attempts, audits, model_hash):
    differences = []
    uri = (output / "training.sqlite").as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        assert db.execute("PRAGMA quick_check").fetchone() == ("ok",)
        snapshots = {}
        for step, payload, stamp in db.execute("SELECT step,payload,sha FROM snapshots"):
            assert sha256(payload).hexdigest() == stamp
            snapshots[step] = tensors(payload)
        assert set(snapshots) == {0, 1}
        assert snapshots[0]["model_sha256"] == model_hash != snapshots[1]["model_sha256"]
        assert snapshots[1]["adam"]["state"] and isinstance(snapshots[1]["rng"], torch.Tensor)
        for snap in snapshots.values():
            policy = v4.Policy()
            policy.load_state_dict(snap["model"])
            assert digest(v4.checkpoint_policy(policy)) == snap["model_sha256"]
        rows = db.execute("SELECT root,rows,sha FROM roots JOIN root_hashes USING "
                          "(phase,step,root) WHERE phase='train' AND step=0 ORDER BY root")
        for (key, payload, stamp), attempt, audit_record in zip(rows, attempts, audits, strict=True):
            assert sha256(payload).hexdigest() == stamp
            batch = unpack(payload)
            evidence = json.loads((output / "audit" / f"000000-{key}.json").read_bytes())
            assert digest(evidence) == batch["evidence_sha256"]
            if not batch["rows"] or not attempt["rows"]:
                differences.append(dict(root=key, kind="missing_route"))
                continue
            before, = attempt["rows"]
            after, = batch["rows"]
            actions = lambda row: [item["action"] for item in row["transitions"]]
            checks = dict(actions=actions(before) == actions(after),
                          behavior=before["behavior"] == after["behavior"],
                          terminal=all(before["feedback"].get(k) == after["feedback"].get(k)
                                       for k in ("status", "observation", "actions")),
                          qualification=(audit_record["status"], audit_record["eligible"]) ==
                          (batch["status"], after["feedback"]["eligible"]),
                          terminal_stamp=audit_record.get("native_terminal_stamp") ==
                          evidence.get("native_terminal_stamp"))
            if not all(checks.values()):
                differences.append(dict(root=key, checks=checks))
    return dict(differences=differences, final_model_sha256=snapshots[1]["model_sha256"])


def main(output):
    output.mkdir(parents=True)
    cfg = config()
    verify_main()
    os.environ["STS2_DOTNET"] = str(Path("logs/m0-v5/dotnet9/dotnet.exe").resolve())
    os.environ["STS2_DOTNET_VERSION"] = "9.0.7"
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    targets.worker_bind = accept["bind"]
    targets.configure()
    summary = dict(host=platform.platform(), torch=str(torch.__version__), resources={},
                   graph_import_s=perf_counter() - START, training_config=cfg,
                   regular_headless=verify_main(), python=sys.version)
    events = []
    with Meter() as meter, observe_workers(meter, events):
        total = meter.start_phase()

        def phase(name, action):
            before = len(events)
            tick = meter.start_phase()
            result = action()
            summary["resources"][name] = meter.end_phase(tick) | {
                "processes": len(events) - before,
                "worker_startup_s": sum(event["startup_s"] for event in events[before:]),
            }
            save(output / "summary.json", summary)
            return result

        catalog = output / "catalog"
        catalog.mkdir()
        versions = accept["bind"](catalog, SOLVER)
        summary["engine"] = versions
        roots, = phase("catalog", lambda: v4.schedule(catalog, SOLVER, cfg))
        assert len(roots) == len({digest(root) for root in roots}) == 24
        assert all(root["hp"] == root["max_hp"] == 999 for root in roots)
        summary["root_sha256"] = digest(roots)
        predict, native, training = (output / name for name in ("prediction", "certification", "training"))
        for directory in (predict, native, training):
            directory.mkdir()
        model_hash, attempts = phase("prediction", lambda: sample(predict, versions, roots, cfg))
        save(predict / "routes.json", attempts)
        statuses = Counter(row["feedback"]["status"] for item in attempts for row in item["rows"])
        summary["prediction"] = dict(statuses=statuses, failures=sum(not item["rows"] for item in attempts),
                                     decisions=sum(len(row["transitions"]) for item in attempts for row in item["rows"]),
                                     worker_s=sum(item["timing"]["total_ms"] for item in attempts) / 1000,
                                     model_sha256=model_hash)
        audits = phase("certification", lambda: audit(native, versions, roots, attempts, cfg))
        save(native / "audits.json", audits)
        summary["certification"] = dict(statuses=Counter(item["status"] for item in audits),
                                        candidates=sum(item.get("candidate", False) for item in audits),
                                        audit_pairs_started=summary["resources"]["certification"]["processes"] -
                                        sum(item.get("candidate", False) and not item.get("auditor_reused", False)
                                            and item.get("status") != "audit_failure" for item in audits),
                                        admitted=sum(item.get("eligible", False) for item in audits),
                                        reused=sum(item.get("auditor_reused", False) for item in audits),
                                        worker_s=sum(item.get("audit_ms", 0) for item in audits) / 1000,
                                        retirement_worker_s=sum(item.get("retirement_ms", 0) for item in audits) / 1000)
        save(output / "summary.json", summary)
        assert summary["certification"]["admitted"], "Zero strict admissions"
        summary["training"] = phase("training", lambda: train(training, cfg, roots))
        details = json.loads((training / "update-000001.json").read_bytes())
        summary["training"]["update_report"] = details
        timing = summary["training"]
        timing["collection_s"] = timing["pre_report_s"] - timing["optimizer_s"]
        timing["ib_boundary_s"] = timing["pre_report_s"] + timing["sqlite_snapshot_1_s"]
        summary["verification"] = phase("verification", lambda: verify_training(training, attempts, audits, model_hash))
        summary["total_s_since_script_start"] = perf_counter() - START
        summary["cpu_count"] = meter.cores
        summary["whole_metered_cpu_s"] = meter.snapshot()[1] - total[1]
        summary["whole_metered_peak_mib"] = meter.peak / 2**20
        save(output / "summary.json", summary)
        save(output / "workers.json", events)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
