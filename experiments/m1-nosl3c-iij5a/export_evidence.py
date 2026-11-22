"""Compare cumulative targeted results with the recorded II-J acceptance evidence."""
import json
from pathlib import Path
import sys

from verify_quasar import TOOLS
from admission import route_key

HERE = Path(__file__).resolve().parent
HOST = "b3f8ce1d862bdb98000bfeb90d701239e50be17034739c5c2ed18e26716150f0"


def read(path):
    return json.loads(path.read_bytes())


def export(run, output):
    meta = read(run / "run.json")
    previous = {n: read(HERE.parent / f"m1-nosl3c-iij{n}/evidence.json") for n in range(1, 5)}
    files = {
        "quasar": "quasar.json", "cleanse": "draw-instances.json", "related": "related.json",
        "guards": "guards.json", "daggers": "daggers.json", "hammer-route": "route.json",
        "power": "power.json", "quasar-route": "route.json",
    }
    comparisons = []

    def compare(name, expected, actual):
        comparisons.append(dict(check=name, exact=expected == actual))
        if expected != actual:
            def first(left, right, path=()):
                if isinstance(left, dict) and isinstance(right, dict) and left.keys() == right.keys():
                    field = next(k for k in left if left[k] != right[k])
                    return first(left[field], right[field], (*path, field))
                if isinstance(left, list) and isinstance(right, list):
                    for index, (a, b) in enumerate(zip(left, right)):
                        if a != b:
                            return first(a, b, (*path, index))
                    return dict(path=list(path), expected_count=len(left), actual_count=len(right))
                return dict(path=list(path), expected=left, actual=right)
            comparisons[-1]["first_difference"] = first(expected, actual)

    actual = {name: read(run / name / filename) for name, filename in files.items()
              if (run / name / filename).exists()}
    expected = {
        "quasar": previous[1]["quasar"],
        "guards": previous[2]["guards"]["cases"],
        "daggers": previous[3]["fixtures"]["cases"],
        "hammer-route": previous[4]["after"]["result"],
        "power": previous[4]["power"]["cases"],
    }
    for name, old in expected.items():
        if name in actual:
            compare(name, old, actual[name].get("cases", actual[name].get("result")))
    if "related" in actual:
        compare("survivor and daggers history", previous[3]["historical"]["observed"],
                actual["related"]["cases"][0]["observed"])
    if "cleanse" in actual:
        compare("cleanse instance binding",
                {k: v for k, v in previous[1]["cleanse_instances"].items() if k != "engine"},
                {k: v for k, v in actual["cleanse"].items() if k != "engine"})
    if "quasar-route" in actual:
        route = actual["quasar-route"]["result"]
        steps = route["steps"]
        expected_stamp = previous[1]["resample_after"]["audit"]["native_terminal_stamp"]
        compare("quasar archive", (66, 58, "game_over", expected_stamp),
                (len(steps), sum("stamp" in step for step in steps),
                 route["native_decision"], steps[-1].get("stamp") if steps else None))

    samples = []
    for folder, filename, name, old, ledger in (
        ("quasar-sample", "0-000000.json", "II-E 1:000003", previous[1]["resample_after"], "iij1-resample"),
        ("guards-sample", "0-000020.json", "holdout 0:000020", previous[2]["resamples"][0], "iii9b-holdout"),
        ("guards-sample", "1-000005.json", "holdout 1:000005", previous[2]["resamples"][1], "iii9b-holdout"),
        ("daggers-sample", "0-000004.json", "pair16 0:000004", previous[3]["resample"], "iii9b-pair16"),
        ("hammer-sample", "0-000000.json", "II-E 1:000002", previous[4]["resample"], "iii9a-sample-1"),
    ):
        path = run / folder / filename
        if not path.exists():
            continue
        attempt = read(path)
        rows = attempt.pop("rows")
        proof = attempt["evidence"]
        result = dict(witness=name, decisions=len(rows[0]["transitions"]) if rows else 0, **attempt)
        old_proof = old.get("audit", old.get("evidence"))
        fields = ("status", "certification", "boundaries", "terminal_verified", "native_terminal_stamp", "route")
        historical = dict(decisions=len(old["actions"]) if "actions" in old else old["decisions"],
                          behavior=old["behavior"], cap=128,
                          proof={k: old_proof.get(k) for k in fields})
        current = {k: result[k] for k in ("decisions", "behavior", "cap")} | {
            "proof": {k: proof.get(k) for k in fields}}
        # The strict route hash includes engine identity. Compare the same
        # observations and actions under the original identity as well.
        if rows:
            step, root = filename.removesuffix(".json").split("-")
            spec = TOOLS["batch"](ledger, int(step), root)["spec"]
            current["proof"]["route"] = route_key(old_proof["versions"], spec, rows[0])
        result["route_under_historical_identity"] = current["proof"]["route"]
        result["historical"] = historical
        compare(name, historical, current)
        samples.append(result)

    identity = dict(solver="0.51.5-iij.4", solver_sha256=meta["build"]["patched_sha256"],
                    headless_sha256=HOST, game="0.113.1/26660232", coreclr="9.0.7")
    for name, evidence in list(actual.items()) + [(s["witness"], s) for s in samples]:
        compare(f"{name} build identity", identity,
                {k: evidence["engine"].get(k) for k in identity})
    for check in meta["checks"]:
        if check["exit"]:
            check["log"] = (run / f"{check['name']}.log").read_text(encoding="utf-8", errors="replace")
    passed = len(actual) == len(files) and len(samples) == 5 and (
        all(c["exact"] for c in comparisons) and all(not c["exit"] for c in meta["checks"]))
    result = dict(run=meta, passed=passed, comparisons=comparisons, fixtures=actual, samples=samples)
    TOOLS["save_json"](output, result)
    print(f"{meta['seconds']:.2f}s, {len(samples)} samples, passed={passed}")
    for c in comparisons:
        if not c["exact"]:
            print(c["check"], str(c["first_difference"])[:800])
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(export(*(Path(arg) for arg in sys.argv[1:])))
