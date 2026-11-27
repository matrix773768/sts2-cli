"""Collect completed 0A receipts and check semantic and measurement invariants."""
from pathlib import Path
from collections import Counter
import gzip
import json
import zipfile
from infra_assets import ROOT,E
from semantic_check import compare
from summarize import summarize

def collect():
    runs=ROOT/"logs/infra0-runs"
    results={}; measured={};checks={}
    with zipfile.ZipFile(E/"smoke-ledgers.zip","w",compression=zipfile.ZIP_DEFLATED) as out:
        for kind in ("natural","pairs"):
            for mode in ("baseline","aggregate","diagnostic"):
                name=f"qa-{kind}-{mode}"
                dest=runs/name
                w=dest/"worker-0"
                a=json.loads((dest/"result.json").read_bytes())
                assert a["totals"]["valid"]==1
                meta=json.loads((w/"worker.json").read_bytes())
                assert meta["host_resources"][0]["cpu_s"]>0
                if mode!="baseline":
                    assert meta["host"][0]["jit"][-1]["stage"]=="exit"
                    assert len(meta["host"])==1 and meta["stages"]["G2/forward_inputs"]>0
                    assert meta["stages"]["zlib/compress/n"]>0 and meta["root_cumulative"]
                    checks[name]=compare(runs/f"qa-{kind}-baseline",dest)
                results[name]=a
                for file in [dest/"result.json",*(w/k for k in ["process.json","worker.json","semantic.json","task.json"]),
                             w/"evidence"/meta["closed"]["file"]]:
                    out.write(file,str(file.relative_to(runs)))
                out.writestr(name+"/summary.json",json.dumps(summarize(dest)))
        for prefix in ("fixtures","fixture-verified","fixture-final"):
            for mode in ("baseline","aggregate"):
                name=f"{prefix}-{mode}"
                if not (runs/name/"result.json").exists():continue
                d=json.loads((runs/name/"result.json").read_bytes())
                if prefix=="fixture-final":
                    assert d["matches"]
                    checks[name]=d
                measured[name]=d["seconds"]
        native=json.loads((runs/"native-reload/native.json").read_bytes())
        assert len(native)==3 and all(r["matched"] for r in native)
        checks["native"]=native
        measured["native"]=sum(r["seconds"] for r in native)
        for file in runs.glob("*/worker-*/process.json"):
            if not file.parents[1].name.startswith(("qa-","smoke-","check-","verified-")):continue
            proc=json.loads(file.read_bytes())
            measured[file.parents[1].name]=(proc["end"]-proc["start"])/1e9
        for name in ("infra0-meter","infra0-host-v2","infra0-profile-host"):
            if not (ROOT/"logs"/name/"build.json").exists():continue
            measured["build_"+name]=json.loads((ROOT/"logs"/name/"build.json").read_bytes())["build_seconds"]
    measured["failed_build_msbuild_reported"]=23.09
    measured["5B_5C_5D_test_bodies"]=5.466+.291+2.963
    report=dict(checks=checks,receipts=results,seconds_by_run=measured,accounted_s=sum(measured.values()),
                formal_worker_s=0,unmetered="checkout, preparation, process/imports outside fixture and unittest timers, early configure/handshake probes, planning and packaging")
    (E/"acceptance.json").write_text(json.dumps(report,indent=2))
    print("accounted worker seconds",report["accounted_s"])
if __name__=="__main__":
    collect()
