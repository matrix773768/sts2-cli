"""Rebuild the complete study in a fresh directory, keeping all previous runs immutable."""
import argparse
from pathlib import Path
from subprocess import run
import sys
HERE=Path(__file__).resolve().parent

def reproduce(logs):
    logs.mkdir(parents=True,exist_ok=False);out=logs/"evidence"
    def job(script,*args):
        run([sys.executable,str(HERE/script),*map(str,args)],check=True)
    old=sorted((HERE.parent/"m1-core3/evidence").glob("fights*.gz"))
    for i in range(6):job("core4_roots.py",logs/f"c4-nat{i}",i,6)
    job("train_value4.py",logs/"c4-base","base",*old,*sorted(logs.glob("c4-nat*/rows.gz")))
    v0=logs/"c4-base/model.pt";v1=logs/"c4-update/model.pt"
    for i in range(6):job("play_loop.py",logs/f"c4-policy{i}",v0,"train","v0",408,i,6)
    job("play_loop.py",logs/"c4-val",v0,"dev","v0",52,0,1)
    job("train_value4.py",logs/"c4-update",v0,*sorted(logs.glob("c4-policy*/rows.gz")),logs/"c4-val/rows.gz")
    for arm,model,n in (("G2",v0,1),("G2search",v0,1),("core3",HERE.parent/"m1-core3/evidence/simple.pt",2),("v0",v0,2),("v1",v1,2)):
        for i in range(n):job("play_loop.py",logs/f"c4-test-{arm}-{i}",model,"confirm",arm,100,i,n)
        for rep in (1,2,3):job("play_loop.py",logs/f"c4-rep-{rep}-{arm}",model,"confirm",arm,100,0,1,rep)
    job("package_run.py",logs,out)
    job("reference_cost.py",out,logs/"c4-reference")
    job("assessment.py",out)
    job("paired_check.py",out,logs/"c4-paired")
    job("audit.py",out,logs/"c4-audit")
    job("play_loop.py",logs/"c4-mass-audit",v1,"confirm","v1",100,0,1)
    job("mass_audit.py",out,logs/"c4-mass-audit/rows.gz")
    for encounter in ("HAUNTED_SHIP_NORMAL","NIBBITS_NORMAL"):
        for arm in ("G2","v1"):
            job("transfer.py",logs/f"c4-transfer-legal-{encounter}-{arm}",arm,encounter,v1)
    job("transfer.py","summarize",logs,out)
    job("study_metrics.py",out,logs)
    job("manifest.py",out)
if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("new_directory",type=Path)
    reproduce(parser.parse_args().new_directory)
