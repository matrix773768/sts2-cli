"""Exercise the 5D prefix/Headbutt and ordered-vs-multiset witnesses on both hosts."""
from infra_assets import ROOT
import json
import os
from pathlib import Path
import sys
from time import perf_counter

def run(mode):
    out=ROOT/"logs/infra0-runs"/("fixture-final-"+mode)
    out.mkdir(parents=True,exist_ok=False)
    os.environ["STS2_CORE5C_HOST"]=str(ROOT/"logs"/("core5c-host" if mode=="baseline" else "infra0-profile-host"))
    sys.path.insert(0,str(ROOT/"experiments/m1-core5d"))
    import audit5d
    import battle5d,experience5d
    if mode=="aggregate":
        from meter import Meter
        meter=Meter()
        meter.install(battle5d,experience5d)
    start=perf_counter()
    host,g2,net,plan=battle5d.configure(out,"V2low")
    lane=battle5d.Lane(host,0)
    try:
        result=dict(cases=audit5d.cases(lane,g2,net,plan),relic=audit5d.relic(lane,plan))
    finally:
        lane.close()
        host.close()
    from semantic_check import digest
    expected=json.loads((ROOT/"experiments/m1-core5d/evidence/audit.json").read_bytes())
    expected.pop("seconds")
    report=dict(seconds=perf_counter()-start,semantic_sha=digest(result),historical_sha=digest(expected),
                matches=digest(result)==digest(expected))
    (out/"result.json").write_text(json.dumps(report,indent=2))
    if not report["matches"]:raise ValueError("Historical fixture changed")
if __name__=="__main__":
    if sys.argv[1] not in ("baseline","aggregate"):raise ValueError("Expected baseline or aggregate")
    run(sys.argv[1])
