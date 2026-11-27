"""INFRA-1A records use a separate append-only ledger and immutable run tags."""
from pathlib import Path
import json
import sys
import time
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE.parent / "m1-infra0"
sys.path.insert(0, str(OLD))
from infra_assets import sha

RUNS = ROOT / "logs/infra0-runs"
BOOK = ROOT / "logs/infra1a/campaign.jsonl"
E = HERE / "evidence"

def entries():
    return [json.loads(line) for line in BOOK.read_text().splitlines()] if BOOK.exists() else []

def charged(label, args, reserve, success=None):
    previous = entries()
    if any(row["label"] == label for row in previous):
        raise ValueError(f"Already attempted {label}")
    left = 7200 - sum(r["seconds"] for r in previous)
    if left < reserve:
        raise RuntimeError(f"Insufficient budget: {left:.1f}s for {label}")
    BOOK.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    with (BOOK.parent / (label+".log")).open("xb") as log:
        process = subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        try:
            process.wait(timeout=min(left, max(180, 3*reserve)))
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill","/PID",str(process.pid),"/T","/F"],check=False)
            process.wait()
    row = dict(label=label, seconds=time.perf_counter()-start, exit=process.returncode, args=list(map(str,args)))
    try:
        if process.returncode:
            raise RuntimeError(f"Inspect {label}.log")
        if success:
            row.update(success())
        row["success"] = True
    finally:
        row.setdefault("success",False)
        with BOOK.open("a",encoding="utf8") as f:
            f.write(json.dumps(row)+"\n")
    print(label, round(row["seconds"],1), flush=True)
    return row
