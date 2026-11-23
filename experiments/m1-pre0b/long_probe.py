"""Continue action-budget witnesses under the same frozen v4 policy and root."""
import argparse
from contextlib import closing
import gzip
import json
import os
from pathlib import Path
import runpy
import sqlite3
import sys


def probe(source, output, host, cap):
    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    runtime = runpy.run_path(str(here / "run.py"))
    output.mkdir()
    os.environ["STS2_DOTNET"] = str(Path("logs/m0-v5/dotnet9/dotnet.exe").resolve())
    os.environ["STS2_DOTNET_VERSION"] = "9.0.7"
    torch, v4, p0 = (runtime[k] for k in ("torch", "v4", "p0"))
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(p0["config"]()["initialization_seed"])
    policy = v4.Policy().eval()
    model = runtime["digest"](v4.checkpoint_policy(policy))
    args = argparse.Namespace(output=output, host=host)
    versions = runtime["bind_host"](args)
    result = []
    with closing(sqlite3.connect(source.resolve().as_uri()+"?mode=ro", uri=True)) as db, p0["Meter"]() as meter:
        manifest = json.loads(db.execute("SELECT json FROM manifest").fetchone()[0])
        if manifest["behavior"] != model or manifest["versions"] != versions:
            raise ValueError("Not the original solver, host or frozen v4 identity")
        config = manifest["config"] | {"action_cap": cap}
        lane = runtime["Lane"](output, versions, meter, 1, 512 * 2**20)
        for ordinal, raw, recipe in db.execute("""
            SELECT ordinal, payload, recipe FROM trajectories
            JOIN private_tasks USING(id) WHERE complete = 0 ORDER BY ordinal
        """):
            old = json.loads(gzip.decompress(raw))
            if old["status"] != "truncated" or old["reason"] != "action_cap":
                continue
            original = [step["action"] for step in old["steps"] if step["advanced"]]
            job = old["id"], ordinal, json.loads(recipe), old["split"], old["family"], old["room"]
            new, _ = runtime["collect"](versions, policy, policy, model, config,
                                        set(manifest["allowed_cards"]), job, lane, True)
            match = original == [step["action"] for step in new["steps"][:len(original)]]
            result.append(dict(ordinal=ordinal, encounter=old["root"]["encounter"],
                               prefix_actions_match=match, before=len(original), after=new["length"],
                               outcome=new["status"], complete=new["complete"], terminal=new["terminal"]))
    (output / "probe.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--cap", type=int, default=512, choices=range(257, 513))
    args = parser.parse_args()
    print(json.dumps(probe(args.dataset, args.output, args.host, args.cap), indent=2))
