"""Independent audit of fixed new report sentinels, selected by recipe."""
import argparse
from pathlib import Path
from time import perf_counter

from repeat_study import n2b, read
from native_interaction import audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study",type=Path)
    parser.add_argument("output",type=Path)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    state = read(args.study/"ledger.json")
    locked = read(args.study/"models.json")
    digest = locked.pop("sha256")
    manifest = read(args.study/"manifest.json")
    if digest != n2b.stamp(locked) or digest != manifest["locked_sha256"] or digest != state["locked_sha256"]:
        raise ValueError("Model lock mismatch")
    if state["new_manifest_sha256"] != n2b.stamp(manifest):
        raise ValueError("New manifest mismatch")
    base = n2b.base
    versions = base.s3a.solver_binding(args.output,base.s3a.FIXED,base.ROOT/"logs/m1-e3f/release")
    for key in ("solver_sha256","game_sha256","headless_sha256"):
        if versions[key] != state["versions"][key]:
            raise ValueError(f"Audit environment differs for {key}")
    report = state["passes"][-1]
    roots = {r["id"]:r["root_sha256"] for r in report["lifecycle"]}
    sentinels = {}
    for item in manifest["cases"]:
        c = item["case"]
        if c["complexity"] == "mid_hp" and c["template"] == ("strength" if c["arm"]=="new_seed" else "shiv"):
            sentinels[c["spec"]["encounter"],c["arm"]] = item
    targets = ["initial-mean",next(m["id"] for m in locked["models"]
                                   if m.get("repeat") == "r2" and m.get("method") == "cem")]
    result = dict(versions=versions,locked_sha256=digest,checks=[],lifecycle=[])
    for item in sentinels.values():
        root = item["case"]["id"]
        for model in targets:
            row = next(r for r in report["rows"] if (r["id"],r["model"])==(root,model))
            started = perf_counter()
            with base.worker(args.output,item|{"root_sha256":roots[root]},versions,result["lifecycle"]) as (game,surface):
                check = audit(game,surface["public_root"],row)
            result["checks"].append(dict(id=root,model=model,elapsed_ms=base.ms(started),**check))
            base.bank.atomic(args.output/"audit.json",result)


if __name__ == "__main__":
    main()
