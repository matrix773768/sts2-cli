"""Native whole-trajectory review; reuse only exact witnesses on the same native executable/game."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import time
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/"engine/HotSearch"))
from client import BUILD
from native_audit import check
from hot_produce import peak_rss
from release import pack,rows,sha
LOG=ROOT/"logs/hotsearch-h4"

def fingerprint(r):
    fields=("seed","status","trace","choices","boundaries","terminal")
    return hashlib.sha256(json.dumps([r.get(k) for k in fields],sort_keys=True,separators=(",",":")).encode()).hexdigest()

def run(name,others):
    out=LOG/("review-"+name)
    source=rows(LOG/name/"natural.jsonl.gz")
    if out.is_dir() and any(out.iterdir()):
        raise FileExistsError(out)
    out.mkdir(exist_ok=True)
    oracle_dir=Path(os.environ.get("HOTSEARCH_ORACLE_DIR",BUILD/"oracle"))/"bin/Release/net9.0"
    oracle=sha(oracle_dir/"OfflineSearchHarness.dll")
    godot=sha(oracle_dir/"GodotSharp.dll")
    baseline=LOG/"oracle/bin/Release/net9.0"
    baseline_oracle,baseline_godot=sha(baseline/"OfflineSearchHarness.dll"),sha(baseline/"GodotSharp.dll")
    game=sha(ROOT/"lib/sts2.dll")
    known={}
    for original,verdict in zip(rows(LOG/"quality32/natural.jsonl.gz"),rows(LOG/"reviewed32/results.jsonl")):
        if original["i"]!=verdict["i"]:raise ValueError("native review alignment")
        if verdict["status"]=="matched" and (oracle,godot)==(baseline_oracle,baseline_godot):
            known[fingerprint(original)]=("quality32",original["i"])
    for prev in others:
        q=LOG/("review-"+prev)
        meta=json.loads((q/"ledger.json").read_bytes())
        if (meta["oracle"],meta["game"],meta.get("godot",baseline_godot))!=(oracle,game,godot):continue
        for old in rows(q/"review.jsonl.gz"):
            if old["status"]=="matched":
                known[old["signature"]]=(prev,old["i"])
    if name.startswith("open-"):
        specs=json.loads((HERE/"evidence/open-specs.json").read_bytes())
    else:
        specs=json.load(gzip.open(ROOT/"experiments/m1-core5d/evidence/panel.gz"))["train"]
    start=time.perf_counter();cpu=time.process_time()
    records=[];admitted=[];host_cpu=0.;peak=0;audits=0
    for row in source:
        sig=fingerprint(row)
        record=dict(i=row["i"],signature=sig,status="incomplete")
        if row["terminal"]:
            if sig in known:
                record.update(status="matched",reused=known[sig])
            else:
                audits+=1; meter={};tick=time.perf_counter()
                try:record.update(check(out,specs[row["i"]]["spec"],row,meter=meter))
                except (OSError,KeyError,ValueError,IndexError,RuntimeError,TimeoutError) as e:
                    record.update(status="native_error",reason=str(e)[:400])
                meter["wall"]=time.perf_counter()-tick;record["cost"]=meter
                host_cpu+=meter.get("cpu",0);peak=max(peak,meter.get("peak_rss",0))
            if record["status"]=="matched":admitted.append(row)
        records.append(record)
    pack(out/"review.jsonl.gz",records)
    pack(out/"reviewed.jsonl.gz",admitted)
    (out/"ledger.json").write_text(json.dumps(dict(attempts=len(source),audited=audits,reused=sum("reused" in r for r in records),
        reviewed=len(admitted),C=sum(len(r["states"]) for r in admitted),wall=time.perf_counter()-start,
        python_cpu=time.process_time()-cpu,python_peak_rss=peak_rss(),host_cpu=host_cpu,host_peak_rss=peak,oracle=oracle,game=game,godot=godot)))

if __name__=="__main__":run(sys.argv[1],sys.argv[2:])
