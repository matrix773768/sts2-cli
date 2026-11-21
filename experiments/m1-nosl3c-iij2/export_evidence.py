"""Export the targeted acceptance evidence from the local proof directories."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--prefix", default="iij2")
    parser.add_argument("--solver", type=Path, default=Path("logs/iij2-solver-final"))
    parser.add_argument("--guards-suffix", default="guards")
    args = parser.parse_args()

    def proof(suffix, filename):
        return json.loads((Path("logs") / f"{args.prefix}-{suffix}" / filename).read_bytes())

    before = json.loads((Path(__file__).parent.parent /
                         "m1-nosl3c-iij1/evidence.json").read_bytes())
    previous = {f"{c['step']}:{c['root']}": c["observed"]["public"]["decision"]
                for c in before["related_after"]["cases"] if c["suite"] == "holdout"}
    guards = proof(args.guards_suffix, "guards.json")
    resamples = []
    for filename in ("0-000020.json", "1-000005.json"):
        run = proof("resample", filename)
        row, = run["rows"]
        resamples.append({k: run[k] for k in ("root", "behavior", "cap", "common_prefix", "status")} |
                         dict(decisions=len(row["transitions"]),
                              first_changed=row["transitions"][run["common_prefix"]]["action"],
                              evidence=run["evidence"]))
    survivor = proof("survivor", "related.json")["cases"][0]["observed"]
    assert survivor["steps"][6]["action"]["kind"] == "confirm_selection" and survivor["steps"][6]["stamp"]
    evidence = dict(build=json.loads((args.solver / "build.json").read_bytes()),
                    previous=previous, guards=guards, resamples=resamples,
                    quasar=proof("quasar", "quasar.json"),
                    cleanse=proof("instances", "draw-instances.json"),
                    survivor=survivor["steps"][4:8])
    args.output.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n",
                           encoding="utf-8")


if __name__ == "__main__":
    main()
