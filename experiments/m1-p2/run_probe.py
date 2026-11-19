"""Reproduce the snapshot import barrier and the frozen F3B RPC load test."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
from threading import Barrier, Event
from time import monotonic, perf_counter

HERE = Path(__file__).resolve().parent
F5 = HERE.parent / "m1-f5a"
spec = importlib.util.spec_from_file_location("f5_probe", F5 / "probe.py")
f5 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f5)
bank, s2c, synth = f5.bank, f5.s2c, f5.synth


def selected(ids):
    selection = bank.read(F5 / "selection.json")
    rows = [r for r in selection["selection"] if r["id"] in ids]
    selection.update(selection=rows, pilot=ids)
    plan, done = s2c.inputs(s2c.ROOT / "logs/m1-s2b/formal", selection, "pilot")
    return plan, [done[key]["root"] for key in ids]


def session(output, memory=None):
    return bank.Session(output, monotonic() + 75, Event(), memory)


def capture(game, root):
    surfaces, timings = synth.capture(game, root["spec"])
    s2c.f3a.equal("exact frozen root", {key: root[key] for key in surfaces}, surfaces)
    if any(card["id"] == "NEUTRALIZE" for card in root["spec"]["deck"]):
        s2c.f3a.equal("native Neutralize", {"type": "f2_unpatched", "method": "NeutralizePrefix"},
                      game.request("f1_unpatch_neutralize"))
        s2c.f3a.equal("unpatched root", root["native"], game.request("synthetic_snapshot"))
    return timings


def boundary(output):
    cases = bank.read(F5 / "admission.json")["cases"]
    _, roots = selected([case["id"] for case in cases])
    versions = bank.versions_for_host(output, "m1-p2-build")
    exports, inputs = [], []
    for root in roots:
        with session(output) as game:
            timing = capture(game, root)
            before = game.request("f1_audit")
            reply = game.request("i1_p2_export")
            s2c.f3a.equal("live audit", before, game.request("f1_audit"))
        continuation = reply.pop("continuation")
        s2c.f3a.equal("native continuation", root["native"]["continuation"], continuation)
        metadata = reply.pop("root_metadata")
        inputs.append(dict(continuation=continuation, root_metadata=reply.pop("root_json", metadata)))
        exports.append(dict(root_id=root["id"], pid=game.engine.proc.pid,
                            continuation_sha256=bank.f1.digest(continuation.encode()),
                            timing=timing, observation=reply))
    attempts = []
    with session(output) as game:
        handshake_ms = game.startup_ms
        for index in (0, 1, 0):
            reply = game.request("i1_p2_import", **inputs[index])
            attempts.append(dict(root_id=exports[index]["root_id"], pid=game.engine.proc.pid,
                                 continuation_sha256=exports[index]["continuation_sha256"], observation=reply,
                                 request_ms=game.last_request_ms))
    return dict(versions=versions, cases=cases, exports=exports, import_handshake_ms=handshake_ms,
                imports=attempts)


def timed_search(output, root, memory, gate):
    clock = perf_counter()
    row = dict(root_id=root["id"], phase="startup")
    try:
        with session(output, memory) as game:
            row["pid"] = game.engine.proc.pid
            row["phase"] = "root"
            row["root"] = capture(game, root)
            before = game.request("f1_audit")
            row["phase"] = "search"
            reply = game.request("i1_f3b", arm="C", potions=False, cap=512, rejected=[])
            result = reply.get("search", reply)
            row["prediction_prepare_ms"] = reply.get("root_prepare_ms")
            row.update({key: result.get(key) for key in (
                "hot_ms", "cpu_ms", "transitions", "peak_working_set_bytes")})
            row["phase"] = "post_audit"
            s2c.f3a.equal("live after search", before, game.request("f1_audit"))
            row["status"] = result["status"]
            row["phase"] = "complete"
            row["result"] = result
    except (s2c.f3a.Difference, *bank.ERRORS) as error:
        row.update(bank.failure(error))
    row["release_ms"] = gate
    row["elapsed_ms"] = bank.elapsed(clock)
    if "game" in locals():
        row["request_ms"] = dict(game.rpc_ms)
        row["exit_code"] = game.engine.proc.returncode
    return row


def load(output):
    f5_results = bank.read(F5 / "results.json")
    ids = [r["case"]["id"] for r in f5_results["rows"] if "retry" in r]
    plan, roots = selected(ids)
    versions = bank.versions_for_host(output, f5.quality.HOST) | {
        "synthetic_spec": 2, "initializer": "m1-s2a-v1"}
    s2c.f3a.equal("frozen benchmark host", plan["versions"], versions)
    reference, batches = {}, []
    for workers in (1, 6, 2, 6):
        clock = perf_counter()
        with bank.MemorySampler() as memory, ThreadPoolExecutor(max_workers=workers) as pool:
            barrier = Barrier(workers, timeout=15)

            def task(root):
                barrier.wait()
                return timed_search(output, root, memory, bank.elapsed(clock))

            rows = list(pool.map(task, roots))
        for row in rows:
            result = row.pop("result", None)
            if result is not None:
                if workers == 1 and row["phase"] == "complete":
                    reference[row["root_id"]] = result
                first = reference.get(row["root_id"])
                row["prediction_difference"] = f5.compare(first, result) if first is not None else None
                row["root_stamp"] = result.get("root_stamp")
                row["winner_key"] = result.get("winner_key")
                row["route_and_frames_sha256"] = bank.stamp([result.get("actions"), result.get("stamps")])
        batches.append(dict(workers=workers, rows=rows, elapsed_ms=bank.elapsed(clock),
                            peak_working_set_bytes=memory.batch_peak, samples=memory.samples))
        bank.atomic(output / "load.json", dict(versions=versions, cases=ids, batches=batches))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("boundary", "load"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    if args.operation == "boundary":
        bank.atomic(args.output / "boundary.json", boundary(args.output))
    else:
        load(args.output)


if __name__ == "__main__":
    main()
