"""Lock epoch zero, selected policy, and the independently evaluated trained challenger."""
import json,hashlib
from statistics import mean
from panel5e import E,FIVE,rows
from assessment import utility
def run():
    fit=json.loads((E/"fit.json").read_bytes())
    decisions={}
    baseline=None
    for arm in ("V2","mc","td"):
        rs=sorted(rows(E/f"selection-{arm}-0.gz"),key=lambda r:r["i"])
        if len(rs)!=36:raise ValueError("Incomplete selection panel")
        cur=[(r["family"],r["seed"]) for r in rs]
        if baseline is None:baseline=cur
        else:assert baseline==cur
        metric=fit["epoch0"] if arm=="V2" else fit[arm]["curve"][fit[arm]["winner"]-1]
        decisions[arm]=dict(mse=metric["mse"],nll=metric["nll"],wins=sum(r["status"]=="predicted_win" for r in rs),
            resolved=sum(r["terminal"] is not None for r in rs),
            utility=mean(utility(r) if r["terminal"] else -50. for r in rs))
    old=decisions["V2"]
    better=[k for k in ("mc","td") if decisions[k]["resolved"]==old["resolved"]==36 and
        decisions[k]["mse"]<old["mse"] and decisions[k]["wins"]>=old["wins"] and decisions[k]["utility"]>old["utility"]]
    def order(k):return decisions[k]["utility"],-decisions[k]["mse"],decisions[k]["wins"]
    selected=max(better,key=order) if better else "V2"
    challenger=selected if better else max(("mc","td"),key=order)
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    (E/"selection.json").write_text(json.dumps(dict(selected=selected,challenger=challenger,arms=decisions,
        epoch0=sha(FIVE/"evidence/v2.pt"),challenger_sha=sha(E/(challenger+".pt"))),indent=2))
if __name__=="__main__":run()
