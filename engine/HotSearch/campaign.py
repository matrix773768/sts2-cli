"""Share the frozen campaign's 120 worker-minute ceiling across labelled runs."""
import importlib.util
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
path=ROOT/"experiments/m1-infra1h/campaign.py"
spec=importlib.util.spec_from_file_location("worker_budget",path)
budget=importlib.util.module_from_spec(spec);spec.loader.exec_module(budget)
budget.LOG=ROOT/"logs/hotsearch-h4/campaign"
budget.BOOK=budget.LOG/"ledger.jsonl"


if __name__=="__main__":
    label,script,*args=sys.argv[1:]
    budget.charge(label,[sys.executable,"-B",HERE/script,*args])
