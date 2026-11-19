"""Probe the frozen host's cross-root admission before permitting reuse."""
import argparse
from contextlib import nullcontext
import importlib.util
from pathlib import Path
from threading import Event
from time import monotonic, perf_counter

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("s2c", HERE.parent / "m1-s2c/benchmark.py")
s2c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s2c)
bank, f3a = s2c.bank, s2c.f3a
synth, quality = s2c.s2b.synth, s2c.s2b.quality


def compare(expected, actual):
    clocks = {"hot_ms", "cpu_ms", "replay_ms", "frame_audit_ms", "menu_ms",
              "rollout_ms", "peak_working_set_bytes"}

    def semantic(result):
        if isinstance(result, dict):
            return {k: semantic(v) for k, v in result.items() if k not in clocks}
        if isinstance(result, list):
            return [semantic(v) for v in result]
        return result

    return s2c.diffs(semantic(expected), semantic(actual))


def probe(output, roots, resident, reference=None):
    clock = perf_counter()
    rows, predictions = [], []
    def session():
        return bank.Session(output, monotonic() + 90, Event())
    with session() if resident else nullcontext() as reused:
        for index, root in enumerate(roots):
            row = {"root_id": root["id"], "position": index}
            rows.append(row)
            before_requests = None
            try:
                with nullcontext(reused) if resident else session() as game:
                    row["handshake_ms"] = game.startup_ms if not resident or index == 0 else 0
                    before_requests = game.rpc_ms.copy()
                    surfaces, timing = synth.capture(game, root["spec"])
                    row.update({k: timing[k] for k in ("initialize_ms", "snapshot_ms")})
                    f3a.equal("reconstructed source", {key: root[key] for key in surfaces}, surfaces)
                    before = game.request("f1_audit")
                    # Reproduce the frozen S2C compatibility path on cold roots.
                    # Keep this probe on roots without Neutralize to avoid patch reuse.
                    response = game.request("i1_f3b", arm="C", potions=False, cap=512, rejected=[])
                    row["prediction_prepare_ms"] = response.get("root_prepare_ms")
                    f3a.equal("native source", before, game.request("f1_audit"))
                    result = response.get("search", response)
                    row["hot_ms"] = result.get("hot_ms")
                    row["cpu_ms"] = result.get("cpu_ms")
                    if row["prediction_prepare_ms"] is not None and row["hot_ms"] is not None:
                        row["rpc_residual_ms"] = (game.rpc_ms["i1_f3b"] - before_requests["i1_f3b"]
                                                  - row["prediction_prepare_ms"] - row["hot_ms"])
                    row["transitions"] = result.get("transitions")
                    row["peak_working_set_bytes"] = game.report["peak_working_set_bytes"]
                    row["difference"] = compare(reference[index], result) if reference is not None else []
                    row["status"] = "mismatch" if row["difference"] else result["status"]
                    predictions.append(result)
                    if row["difference"]:
                        break
            except (f3a.Difference, *bank.ERRORS) as error:
                row.update(bank.failure(error))
                break
            finally:
                if before_requests is not None:
                    row["request_ms"] = dict(game.rpc_ms - before_requests)
    return dict(resident=resident, rows=rows, elapsed_ms=bank.elapsed(clock)), predictions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    selection = bank.read(HERE / "selection.json")
    picked = [r for r in selection["selection"] if
              r["split"] == "development" and r["character"] == "Ironclad"]
    pair = [picked[0], next(r for r in picked if r["encounter"] != picked[0]["encounter"])]
    selection.update(selection=pair, pilot=[r["id"] for r in pair])
    plan, done = s2c.inputs(s2c.ROOT / "logs/m1-s2b/formal", selection, "pilot")
    versions = bank.versions_for_host(args.output, quality.HOST) | {
        "synthetic_spec": 2, "initializer": "m1-s2a-v1"}
    f3a.equal("frozen benchmark host", plan["versions"], versions)
    first, second = (item["root"] for item in done.values())
    roots = [first, second, first]
    if any(card["id"] == "NEUTRALIZE" for root in roots for card in root["spec"]["deck"]):
        raise ValueError("Probe requires roots without the Neutralize compatibility override")
    data = []
    for _ in range(2):
        cold, expected = probe(args.output, roots, False)
        data.append(cold)
        cold["repeat_difference"] = compare(expected[0], expected[2]) if len(expected) == 3 else None
        if len(expected) != 3 or cold["repeat_difference"]:
            bank.atomic(args.output / "results.json", dict(versions=versions, cases=pair, batches=data))
            raise ValueError("Independent cold repeat failed")
        hot, _ = probe(args.output, roots, True, expected)
        data.append(hot)
        bank.atomic(args.output / "results.json", dict(versions=versions, cases=pair, batches=data))


if __name__ == "__main__":
    main()
