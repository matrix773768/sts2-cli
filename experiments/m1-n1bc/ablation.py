"""Post-training input ablation on the open qualified report group; no model selection."""
from pathlib import Path
import json
import sys

from arena import ROOT, digest, torch
from learn import records, metrics, restore
from features import CARD_FEATURES, PLAYER_FEATURES, ENEMY_FEATURES


def run(out):
    torch.set_num_threads(1)
    data=ROOT/"logs/n1bc-cohort"
    behavior=digest(json.loads((data/"run.json").read_bytes())["definition"])
    result={}
    for arm in ("mech","wide"):
        net,encoder,slot=restore(ROOT/f"logs/n1bc-clean-{arm}/model.pt")
        batches,_=records(data,encoder,slot,behavior,True)
        rows=batches["report"]
        reference=metrics(net,rows)
        encodings={"card":("instances",CARD_FEATURES),"enemy":("enemies",ENEMY_FEATURES),
                   "player":("player",PLAYER_FEATURES)}
        for group in ("card","enemy","player","all"):
            masked=[]
            for row in rows:
                row=row.copy()
                for key in encodings if group=="all" else [group]:
                    field,offset=encodings[key]
                    row[field]=row[field].copy()
                    row[field][...,offset:]=0
                masked.append(row)
            metric=metrics(net,masked)
            result[f"{arm}-{group}"]=dict(top_changed=sum(a!=b for a,b in zip(reference["top"],metric["top"],strict=True)),
                n=metric["n"],q_nll_delta=metric["q_nll"]-reference["q_nll"],
                v_nll_delta=metric["v_nll"]-reference["v_nll"])
    out.write_text(json.dumps(result,indent=2))


if __name__=="__main__":
    run(Path(sys.argv[1]))
