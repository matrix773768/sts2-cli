"""Summarize formal PRE1 artifacts and compare the inference routes."""
import argparse
from hashlib import sha256
from itertools import zip_longest
import gzip
import json
from pathlib import Path


def digest(path):
    result = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(2**20):
            result.update(chunk)
    return result.hexdigest()


def compare(first, second):
    paired = difference = decisions = 0
    max_logp = 0.
    with gzip.open(first,"rt",encoding="utf-8") as a, gzip.open(second,"rt",encoding="utf-8") as b:
        for left,right in zip_longest(a,b):
            if left is None or right is None:
                raise ValueError("Inference arms have different root counts")
            x,y = json.loads(left),json.loads(right)
            if x["root"] != y["root"]:
                raise ValueError("Inference arms have different root order")
            paired += 1
            same = all(x[k]==y[k] for k in ("status","terminal","length","reason"))
            for p,q in zip(x["steps"],y["steps"]):
                equal = all(p[k]==q[k] for k in ("observation","action","position","advanced"))
                same &= equal
                if equal:
                    decisions += 1
                    max_logp = max(max_logp,abs(p["behavior_logp"]-q["behavior_logp"]))
            difference += int(not same)
    return dict(paired=paired, different=difference, decisions=decisions,max_logp_delta=max_logp)


def collect(formal):
    paths = [formal/"features/manifest.json", formal/"corpus.json", formal/"development/summary.json"]
    for branch in ("weights","behavior-stable","transfer-stable"):
        paths.extend(formal/branch/name for name in ("initial.pt","final.pt","encoder.pt","curve.json","summary.json"))
    paths.append(formal/"weights/mechanism.pt")
    conditional = formal/"mechanism-conditions.json"
    if conditional.is_file():
        paths.append(conditional)
    evaluation = json.loads((formal/"development/summary.json").read_bytes())
    pairing = compare(Path(evaluation["joint"]["trajectories"]),Path(evaluation["grouped_joint"]["trajectories"]))
    return dict(contract="sts2.pre1.evidence.v1", paired_inference=pairing,
                files={str(path):dict(sha256=digest(path),bytes=path.stat().st_size) for path in paths})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("formal",type=Path)
    parser.add_argument("output",type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(collect(args.formal),indent=2),encoding="utf-8")
