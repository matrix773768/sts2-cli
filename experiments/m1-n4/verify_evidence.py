"""Verify frozen files, independently retrained parameters, and record supplemental audit evidence."""
import argparse
from pathlib import Path
from collections import Counter
from zipfile import ZipFile
from cohort import HERE, ROOT, checksum, read, write


def verify(evidence):
    report=read(evidence/"results.json.gz")
    for ref in report["archives"]:
        file=evidence/ref["file"]
        if checksum(file)!=ref["sha256"]:
            raise ValueError(f"Changed archive {file}")
        with ZipFile(file) as z:
            if z.testzip():
                raise ValueError(f"Damaged archive {file}")
    d=ROOT/"logs"
    fits={}
    for p in sorted((d/"n4-v2-fit").glob("*.pt")):
        second=d/"n4-v2-refit"/p.name
        if checksum(p)!=checksum(second):
            raise ValueError(f"Refit differs for {p.name}")
        fits[p.stem]=checksum(p)
    if len(fits)!=8:
        raise ValueError("Expected eight models")
    worlds=read(d/"n4-v2-worldcheck/worlds.json")
    abandoned={}
    for p in sorted(d.glob("n4-set-*")):
        rows=[read(f) for f in p.glob("*.json.gz")]
        files=[f for f in p.rglob("*") if f.is_file()]
        abandoned[p.name]=dict(finalized_rows=len(rows),seconds_in_rows=sum(r["seconds"] for r in rows),
            file_activity_s=max(f.stat().st_mtime for f in files)-min(f.stat().st_mtime for f in files))
    out=evidence/"verification.json"
    if out.exists():
        raise FileExistsError(out)
    summary={}
    for arm,metrics in report["offline"].items():
        b=metrics["k24"]
        summary[arm]=dict(accuracy=b["acc"],delta_mae=b["delta_mae"],regret=b["regret"],q_nll=b["q_nll"],
            death_brier=b["q_brier"],wins={str(budget):report["combat"][arm+"-"+str(budget)]["statuses"]["predicted_win"]
                                         for budget in (0,24)})
    write(out,dict(checkpoints=fits,summary=summary,retraining_seconds=read(d/"n4-v2-refit/run.json")["seconds"],
        primary_seconds=report["seconds_sum"],worlds=worlds,abandoned_v1=abandoned,smoke=read(d/"n4-throughput/run.json")["seconds"],
        protocol=dict(version="n4.synthetic-conditional-opening.v2",actor="projected_public_history_only",
            initial_seed="independent keyed native initialization per proposal",accepted_world_weight="1/accepted block size",
            action_weight="uniform over recorded support within root",train_worlds=4,primary_eval_worlds_per_block=6,
            replicate_worlds_per_block=24,training_rows="complete balanced blocks only",death=-50,
            maximum_rejections="fixed proposal count per block, see manifest",rank_training_labels=False)))


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("evidence",type=Path,default=HERE/"evidence",nargs="?")
    verify(p.parse_args().evidence)
