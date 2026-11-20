"""Reproduce a held-out witness without a model or a policy decision."""
import argparse
import gzip
import json
from pathlib import Path

from admission import certify
from engine import bind
from nosl_experience import save_json

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("witness", type=Path)
    parser.add_argument("--solver", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    witness = json.loads(gzip.decompress(args.witness.read_bytes()))
    versions = bind(output, args.solver.resolve())
    result = certify(output, versions, witness["spec"], witness["row"])
    if (result["reason"], result.get("position")) != (witness["reason"], witness["position"]):
        raise ValueError("Witness failed at a different boundary")
    save_json(output / "replay.json", result)
