"""Independent native replay on the frozen middle-HP report sentinels."""
import argparse
from pathlib import Path
from time import perf_counter

from run_factorial import n2b, read, root_audit
from native_interaction import audit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study",type=Path)
    parser.add_argument("output",type=Path)
    args=parser.parse_args()
    output=args.output.resolve()
    output.mkdir(parents=True)
    state=read(args.study/"ledger.json")
    manifest=read(args.study/"manifest.json")
    if n2b.stamp(manifest) != state["manifest_sha256"]:
        raise ValueError("Manifest mismatch")
    base=n2b.base
    versions=base.s3a.solver_binding(output,base.s3a.FIXED,base.ROOT/"logs/m1-e3f/release")
    if any(versions[k]!=state["versions"][k] for k in ("solver_sha256","game_sha256","headless_sha256")):
        raise ValueError("Native audit host differs")
    identities={r["id"]:r["root_sha256"] for r in state["lifecycle"]}
    results=dict(versions=versions,manifest_sha256=state["manifest_sha256"],checks=[],lifecycle=[])
    for item in manifest["cases"]:
        c=item["case"]
        if c["diagnostic_split"]!="report" or c["complexity"]!="mid_hp" or c["seed_index"]!=0:
            continue
        id_=c["id"]
        row=next(r for r in state["rows"] if r["id"]==id_ and r["model"]=="initial-mean")
        started=perf_counter()
        with base.worker(output,item|{"root_sha256":identities[id_]},versions,results["lifecycle"]) as (game,surface):
            if root_audit(surface)!=state["root_audits"][id_]:
                raise ValueError("Root RNG audit differs")
            check=audit(game,surface["public_root"],row)
        results["checks"].append(dict(id=id_,elapsed_ms=base.ms(started),**check))
        base.bank.atomic(output/"native-audit.json",results)


if __name__=="__main__":
    main()
