"""External frozen trajectory replay and per-C model-input diagnostics."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import time
from client import Client,ROOT
from hot_produce import panel
from models import strategic
from condition import key
from semantic import torch


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    specs=json.load(gzip.open(ROOT/"experiments/m1-core5d/evidence/panel.gz"))["train"]
    rows={r["i"]:r for p in (ROOT/"experiments/m1-core5d/evidence").glob("train-V2-*.gz") for r in map(json.loads,gzip.open(p))}
    torch.set_num_threads(1)
    client=Client(out/"transport");start=time.perf_counter();cpu=time.process_time()
    try:
        with (out/"replay.jsonl").open("x") as file:
            for i in panel():
                row=rows[i];index=0;chosen=None
                evidence=dict(i=i,status="failed",cuts=[],steps=0)
                try:
                    st=client.call("open",spec=specs[i]["spec"])
                    for turn,action in row["trace"]:
                        if st["status"]=="choice":
                            if chosen is None:chosen=action;continue
                            if not 0<=chosen<len(st["options"]) or action!=0:raise ValueError("choice/confirmation")
                            action=chosen;chosen=None
                        elif st["status"]!="active" or st["facts"]["turn"]!=turn:raise ValueError("turn_or_terminal")
                        st=client.call("step",index=action);evidence["steps"]+=1
                        if st.get("observed_c"):
                            cut=st["observed_c"];actual=strategic(cut["facts"],cut["draw"])
                            expected=row["states"][index];index+=1
                            changed=[k for k in expected if actual.get(k)!=expected[k]]
                            diff=dict(turn=actual["turn"],different=changed,tensor_equal=key(actual)==key(expected))
                            if "enemies" in changed:
                                diff["enemy_fields"]=sorted({k for e,f in zip(expected["enemies"],actual["enemies"]) for k in e if e[k]!=f.get(k)})
                            if "belief" in changed:
                                diff["belief_fields"]=[k for k in expected["belief"] if expected["belief"][k]!=actual["belief"].get(k)]
                            if "card_state" in changed:
                                diff["card_fields"]=sorted({k for z in expected["card_state"] for e,f in zip(expected["card_state"][z],actual["card_state"][z]) for k in e if e[k]!=f.get(k)})
                            evidence["cuts"].append(diff)
                    t=row["terminal"] or {};f=st.get("facts") or {}
                    matches=st["status"]=={"death":"Defeat","predicted_win":"Victory"}.get(row["status"]) and all(f.get(k)==t.get(k) for k in ("hp","max_hp","gold"))
                    evidence.update(status="matched_terminal" if matches else "terminal_gap",expected=row["status"],actual=st["status"])
                except (RuntimeError,ValueError,KeyError,IndexError) as e:evidence["reason"]=str(e)[:240]
                file.write(json.dumps(evidence)+"\n");file.flush()
        host=client.call("metrics")
    finally:client.close()
    (out/"ledger.json").write_text(json.dumps(dict(wall=time.perf_counter()-start,python_cpu=time.process_time()-cpu,host=host)))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("output",type=Path);run(p.parse_args().output)
