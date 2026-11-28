"""Produce the publicly precommitted root/plan and replication contract."""
from panel import HERE,slots
from experience import digest,sha,require
from produce_batch import write
import json

def register():
    code={n:sha(HERE/n) for n in ("panel.py","worlds.py","condition_worker.py","paired.py")}
    contract=dict(version="m1-infra2a-root-v1",suffix_policy="25740c4a3b29a5f378f6bd5723d3b594be6547a77e16b891e461bbf2bfcdcda7",
                  code=code,cohorts={n:sha(HERE/(n+".gz")) for n in ("dev","train","reserve")},slots=slots(),
                  candidate_order="hash(2a-root,slot,family) within assigned act and split; one root per family",
                  representative="first available stable exchangeable multitype root on assigned turn",
                  difference="add two public play signatures and two closed forecasts with distinct first indices and distinct (value, leaf count); no minimum utility gap",
                  plans="best complete V2 plan; representative next best distinct law; difference maximizes differing public power, card/resource, enemy and HP/block distribution channels",
                  scan_boundary="public observations and actions strictly before root; only observation and pre-action predictions at root",
                  repeat="up to 32 eligible main roots by preassigned rank, same programs and four disjoint seeds; development stays development",
                  budget="first 48 formal slots; forecast from measured worker cost and charge scan, use common 120-worker-minute envelope",
                  selection_fields_excluded=["future actions","root action","observed boundary","terminal outcomes","source admission"])
    contract["id"]=digest(contract)
    path=HERE/"registration.json"
    if path.exists():require(json.loads(path.read_bytes())==contract,"registration changed")
    else:write(path,contract)
if __name__=="__main__":register()
