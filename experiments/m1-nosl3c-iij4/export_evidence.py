"""Export the fixed-route, lifecycle, resampling and regression evidence."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--prefix", default="iij4-proof")
    parser.add_argument("--before", type=Path, default=Path("logs/iij4-before"))
    parser.add_argument("--solver", type=Path, default=Path("logs/iij4-solver"))
    args = parser.parse_args()

    def read(folder, filename):
        return json.loads((Path("logs") / f"{args.prefix}-{folder}" / filename).read_bytes())

    before = json.loads((args.before / "route.json").read_bytes())
    after = read("after", "route.json")
    prior = before["result"]
    fixed = after["result"]
    assert prior["position"] == 42 and set(prior["differences"]) == {"P"}
    assert prior["steps"][:42] == fixed["steps"][:42]
    assert fixed["steps"][42]["stamp"] and fixed["steps"][42]["native_terminal"]
    resample = read("resample", "0-000000.json")
    row, = resample.pop("rows")
    resample["decisions"] = len(row["transitions"])
    archive = Path(__file__).resolve().parent.parent / "m1-nosl3c-iii9a/evidence.json"
    prior_samples = json.loads(archive.read_bytes())["resampled"]
    source, = [item for item in prior_samples if (item["ledger"], item["step"], item["root"])
               == ("II-E", 1, "000002")]
    assert resample["behavior"] == source["observed"]["behavior"]
    assert resample["cap"] == source["budget"]
    regressions = {
        "forge": "forge.json", "blade": "history.json", "hammer": "hammer.json",
        "plot": "plot.json", "quasar": "quasar.json", "guards": "guards.json",
        "daggers": "daggers.json", "cleanse": "draw-instances.json",
    }
    result = dict(build=json.loads((args.solver / "build.json").read_bytes()),
                  archive_case={k: source[k] for k in ("ledger", "step", "root", "config_sha256")},
                  before=before, after=after, resample=resample, power=read("power", "power.json"),
                  regressions={name: read(name, filename) for name, filename in regressions.items()})
    args.output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
                           encoding="utf-8")


if __name__ == "__main__":
    main()
