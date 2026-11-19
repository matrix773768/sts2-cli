"""Run one isolated projected trajectory per strategy on open development roots."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
diagnose = runpy.run_path(str(HERE.parent / "m1-s3b/diagnose.py"))
s3a, bank, f3a = (diagnose[key] for key in ("s3a", "bank", "f3a"))
s3a.HOST = "m1-n1-build"
BASELINE = ("Q1", "AGGRO", "DEFENSIVE", "ENGINE")
EXPERIMENT = ("THREAT_V1", "DURABLE_V1")
SPECIAL = "f2f29fd990637955"


def inputs():
    for case in bank.read(HERE / "s2b-early.json"):
        if case["split"] != "development" or case["profile"] != "early":
            raise ValueError("Unexpected S2B split or profile")
        yield dict(cohort="S2B-early", case=case, synthetic=True, natural_reachability="unknown")
    for path in ("m1-s3a/hard.json.gz", "m1-s3b/development.json.gz"):
        with gzip.open(HERE.parent / path, "rt", encoding="utf-8") as stream:
            for row in json.load(stream)["rows"]:
                case = row["input"]
                if case["split"] != "development":
                    raise ValueError("Unexpected closed split")
                yield dict(cohort="S3B", case=case, root_sha256=row["root_sha256"],
                           synthetic=True, natural_reachability="unknown")
    source = ROOT / "logs/m1-f3a-formal"
    roots = bank.read(source / "manifest.json")["roots"]
    pinned = bank.read(HERE.parent / "m1-f3a/manifest.json")["roots"]
    if [(r["id"], r["identity"]) for r in roots] != [(r["id"], r["identity"]) for r in pinned]:
        raise ValueError("Unexpected F3A development roots")
    for root in roots:
        yield dict(cohort="F3A", case=root, synthetic=False, natural_reachability="assisted_history")


def run(game, strategies):
    before = game.request("f1_audit")
    for strategy in strategies:
        try:
            reply = game.request("i1_f3b", initial=strategy, arm="A", potions=False, cap=48, rejected=[])
        except bank.f1.i2.StopRun as error:
            if "PredictionUnsupportedException" not in str(error):
                raise
            reply = dict(status="unsupported", detail=str(error))
        result = reply.get("search", reply)
        result.update(strategy=strategy, root_prepare_ms=reply.get("root_prepare_ms"))
        if "history" in result:
            if result["action_count"] != len(result["history"]) - 1:
                raise ValueError("Action count differs from the recorded path")
            if any(node["parent"] != idx - 1 for idx, node in enumerate(result["history"]) if idx):
                raise ValueError("Expected one linear route")
        if before != game.request("f1_audit"):
            raise ValueError("Rollout changed the live root")
        yield result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--synthetic-prefix", type=Path, help="Reuse a completed synthetic baseline prefix")
    parser.add_argument("--baseline", type=Path, help="Completed baseline required for the experimental run")
    args = parser.parse_args()
    cases = list(inputs())
    prefix = []
    if args.synthetic_prefix:
        if args.baseline:
            parser.error("Cannot reuse a synthetic prefix in the experimental run")
        with gzip.open(args.synthetic_prefix, "rt", encoding="utf-8") as stream:
            prefix = [json.loads(line) for line in stream]
        expected = [(c["case"], strategy) for c in cases if c["synthetic"] for strategy in BASELINE]
        if [(r["case"], r["result"]["strategy"]) for r in prefix] != expected:
            raise ValueError("Unexpected synthetic baseline prefix")
        cases = [c for c in cases if not c["synthetic"]]
    baseline_sha256 = None
    if args.baseline:
        with gzip.open(args.baseline, "rt", encoding="utf-8") as stream:
            baseline = [json.loads(line) for line in stream]
        expected = [(item["cohort"], item["case"]["id"], policy) for item in cases for policy in BASELINE]
        observed = [(r["cohort"], r["case"]["id"], r["result"]["strategy"]) for r in baseline]
        if observed != expected:
            raise ValueError("Expected the completed frozen baseline")
        baseline_sha256 = hashlib.sha256(args.baseline.read_bytes()).hexdigest()
    output = args.output.resolve()
    output.mkdir(parents=True)
    versions = s3a.solver_binding(output, s3a.FIXED, ROOT / "logs/m1-e3f/release")
    if not prefix and sum(item["cohort"] == "S3B" for item in cases) != 96:
        raise ValueError("Expected 96 S3B cases")
    with gzip.open(output / "results.jsonl.gz", "wt", encoding="utf-8") as stream:
        for record in prefix:
            stream.write(json.dumps(record) + "\n")
        for item in cases:
            case = item["case"]
            if args.baseline and (item["cohort"] != "S3B" or case["spec"]["encounter"] != "BOWLBUGS_NORMAL"):
                continue
            strategies = EXPERIMENT[:1] if args.baseline else BASELINE
            if args.baseline and case["id"] == SPECIAL:
                strategies = EXPERIMENT
            if item["cohort"] == "F3A":
                if s3a.HOST != "m1-n1-real-build":
                    s3a.HOST = "m1-n1-real-build"
                    versions = s3a.solver_binding(output, s3a.FIXED, ROOT / "logs/m1-e3f/release")
                restore = f3a.restored(ROOT / "logs/m1-f3a-formal", case)
            else:
                restore = diagnose["restored"](output, case, versions, item.get("root_sha256"))
            with restore as (game, metadata):
                for result in run(game, strategies):
                    record = dict(item, versions=versions, evidence="prediction_only", result=result,
                                  baseline_sha256=baseline_sha256)
                    if "root_sha256" in metadata:
                        record["root_sha256"] = metadata["root_sha256"]
                    stream.write(json.dumps(record) + "\n")
            stream.flush()
            print(item["cohort"], case["id"], flush=True)


if __name__ == "__main__":
    main()



