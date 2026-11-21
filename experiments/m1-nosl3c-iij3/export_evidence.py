"""Export the II-J.3 targeted evidence."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--prefix", default="iij3")
    args = parser.parse_args()

    def read(folder, filename):
        return json.loads((Path("logs") / f"{args.prefix}-{folder}" / filename).read_bytes())

    native = read("native", "daggers.json")
    fixtures = read("fixtures", "daggers.json")
    for before, after in zip(native["cases"], fixtures["cases"]):
        assert before["native_state"] == after["native_state"]
        assert after["exact_stamp"] and after["pending"] == (after["count"] > 2)
    related = read("related", "related.json")["cases"][0]
    assert related["observed"]["steps"][6]["stamp"] and related["observed"]["steps"][8]["stamp"]
    run = read("resample", "0-000004.json")
    row, = run.pop("rows")
    run["decisions"] = len(row["transitions"])
    result = dict(build=read("solver", "build.json"), native=native, fixtures=fixtures,
                  historical=related, resample=run, guards=read("guards", "guards.json"),
                  quasar=read("quasar", "quasar.json"), cleanse=read("cleanse", "draw-instances.json"))
    args.output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
                           encoding="utf-8")


if __name__ == "__main__":
    main()
