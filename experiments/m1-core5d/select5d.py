"""Select V3 on development full battles, with the offline shortlist fixed first."""
import json,shutil
from statistics import mean
from panel5d import E,OUT,rows
from assessment import utility
def select():
    fit=json.loads((E/"fit.json").read_bytes())
    candidates=[]
    for ep in fit["shortlist"]:
        data=list(rows(E/f"selection-epoch{ep}-0.gz"))
        if len(data)!=24:raise ValueError("Missing selection worlds")
        candidates.append(dict(epoch=ep,resolved=sum(bool(r["terminal"]) for r in data),
            utility=mean(utility(r) if r["terminal"] else -50. for r in data),wins=sum(r["status"]=="predicted_win" for r in data),
            offline=fit["curve"][ep-1]["score"]))
    winner=max(candidates,key=lambda z:(z["resolved"],z["utility"],z["wins"],-z["offline"]))
    shutil.copyfile(OUT/"full-fit"/f"epoch{winner['epoch']}.pt",E/"v3.pt")
    (E/"selection.json").write_text(json.dumps(dict(winner=winner["epoch"],candidates=candidates),indent=2))
if __name__=="__main__":select()
