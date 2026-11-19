"""Profile F4 and compare the opt-in lean path with the frozen resident baseline."""
import argparse
import gzip
import importlib.util
import json
from pathlib import Path
from threading import Event
from time import monotonic, perf_counter

HERE = Path(__file__).resolve().parent
B1B = HERE.parent / "m1-b1b"
spec = importlib.util.spec_from_file_location("f6a_b1b", B1B / "run_probe.py")
b1b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b1b)
bank, equal = b1b.bank, b1b.equal


class Session(b1b.Session):
    def __init__(self, output, lean, profile, local=False):
        super().__init__(output, monotonic() + 180, Event())
        self.lean = lean
        self.profile = profile
        self.runtime = self.phases = None
        self.local = local
        self.local_pairs = []

    def request(self, cmd, **args):
        if cmd == "i1_f4" and self.local:
            original = super().request("f1_audit")
            call_order = (False, True) if len(self.local_pairs) % 2 == 0 else (True, False)
            replies, stats = {}, {}
            for lean in call_order:
                reply = super().request(cmd, **(args | {"f6_lean": lean}))
                stats[str(lean).lower()] = reply.pop("f6_runtime") | {
                    "hot_ms": reply["search"]["hot_ms"], "rpc_ms": self.last_request_ms}
                replies[lean] = reply
                equal("source after independent F4", original, super().request("f1_audit"))
            equal("same-source F4 semantic parity", [],
                  b1b.f5b.f5a.compare(replies[False]["search"], replies[True]["search"]))
            self.local_pairs.append(dict(order=call_order, timings=stats,
                                         baseline=replies[False]["search"]["root_stamp"]))
            self.runtime = stats["false"]
            self.last_request_ms = stats["false"]["rpc_ms"]
            return replies[False]
        if cmd == "i1_f4":
            args.update(f6_lean=self.lean, f6_profile=self.profile)
        reply = super().request(cmd, **args)
        if cmd == "i1_f4":
            self.runtime = reply.pop("f6_runtime", None)
            self.phases = reply.pop("f6_profile", None)
        return reply


def cohort(output, order, cases, expected, lean, profile, local=False):
    started = perf_counter()
    rows = []
    with Session(output, lean, profile, local) as game:
        for index, key in enumerate(order):
            game.runtime = game.phases = None
            row = b1b.execute(game, cases[key], None)
            b1b.record_handshake(row, game.startup_ms if index == 0 else 0)
            row["ordinal"] = index + 1
            row["runtime"] = game.runtime
            row["profile"] = game.phases
            if local and len(game.local_pairs) > index:
                row["same_source_pair"] = game.local_pairs[-1]
            if profile and game.phases is not None and not row.get("discard_reason"):
                row["wire"] = game.request("f6_wire")["value"]
            ref = expected[key]
            row["matched_b1b"] = (all(row.get(field) == ref.get(field) for field in (
                "semantic_sha256", "root_sha256", "root_profile_sha256", "rng_sha256", "risks"))
                and row.get("retirement", {}).get("native_frames_sha256")
                == ref["retirement"]["native_frames_sha256"])
            rows.append(row)
            if (not row["matched_b1b"] or row.get("discard_reason")
                    or not row["runtime"] or row["runtime"]["lean"] != lean):
                game.engine.close(graceful=False)
                row["discard_exit_code"] = game.engine.proc.returncode
                break
    return dict(lean=lean, profile=profile, planned=len(order), rows=rows, elapsed_ms=bank.elapsed(started))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("pilot", "profile", "paired", "local"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    with gzip.open(B1B / "sequence.json.gz", "rt", encoding="utf-8") as stream:
        original = json.load(stream)
    expected = {r["input"]["id"]: r for r in original["cold"]["rows"]}
    manifest = bank.read(B1B / "inputs.json")
    cases = {r["id"]: r for r in manifest["cases"]}
    equal("frozen B1B inputs", {k: r["input"] for k, r in expected.items()}, cases)
    order = manifest["pilot"] if args.mode == "pilot" else manifest["sequence"][:12]
    flags = {"paired": (False, True, True, False), "local": (False,)}.get(args.mode, (False, True))
    versions = bank.versions_for_host(args.output, "m1-f6a-build")
    for key in ("game_sha256", "solver_sha256", "coreclr"):
        equal("frozen " + key, original["versions"][key], versions[key])
    data = dict(schema=1, mode=args.mode, versions=versions, config=original["config"], cohorts=[])
    for lean in flags:
        result = cohort(args.output, order, cases, expected, lean,
                        args.mode in {"pilot", "profile"}, local=args.mode == "local")
        data["cohorts"].append(result)
        bank.atomic(args.output / "results.json", data)
        if len(result["rows"]) != len(order) or "discard_exit_code" in result["rows"][-1]:
            raise SystemExit("F6A boundary failed. Inspect persisted results.json.")


if __name__ == "__main__":
    main()
