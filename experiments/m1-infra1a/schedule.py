"""Preserve coverage before optional repeats; stop at a safe full-treatment boundary."""
import sys
from common import entries
from campaign1a import run, KINDS

def remaining():
    return 7200-sum(r["seconds"] for r in entries())

def estimate(kind, variant):
    prior=[r["seconds"] for r in entries() if r.get("kind")==kind and not r.get("smoke") and
           r.get("variant") in ("original","batch") and r.get("mode")=="baseline"]
    if prior:return max(prior)*1.12
    return {"natural":800,"pairs":330,"initial-train":150,"initial-dev":180,"audit":320}[kind]

def primary():
    for idx,kind in enumerate(KINDS):
        order=("original","batch") if idx%2==0 else ("batch","original")
        for j,v in enumerate(order):
            run(kind,v,"cross"+str(j+1))

def reverse(kind):
    order=("batch","original") if KINDS.index(kind)%2==0 else ("original","batch")
    if remaining()<2*estimate(kind,"batch"):
        print("No reserve for both reverse passes of",kind,flush=True)
        return False
    for j,v in enumerate(order,3):run(kind,v,"cross"+str(j))
    return True

if __name__=="__main__":
    if sys.argv[1]=="primary":primary()
    elif sys.argv[1]=="profile":
        # The measured candidate and the scalar 0B trace share source-level counters.
        for k in sys.argv[2:]:run(k,"batch","profile","aggregate")
    elif sys.argv[1]=="reuse":
        for k in sys.argv[2:]:run(k,"reuse","bounded")
    elif sys.argv[1]=="attribution":
        for k in sys.argv[2:]:run(k,"batch-attribution","profile","aggregate")
    elif sys.argv[1]=="scores":
        run("natural","g2-check","encoded",smoke=True)
    elif sys.argv[1]=="cache-control":
        for k in sys.argv[2:]:run(k,"original","cache-control")
    elif sys.argv[1]=="cache-repeat":
        for k in sys.argv[2:]:run(k,"reuse","cache-repeat")
    elif sys.argv[1]=="scalar-profile":
        for k in sys.argv[2:]:run(k,"original","profile","aggregate")
    elif sys.argv[1]=="reverse":
        for k in sys.argv[2:]:reverse(k)
