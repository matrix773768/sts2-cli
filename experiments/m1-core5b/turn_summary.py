"""Summarize only paired conditional worlds. Preserve the original seed as a separate observation."""
import json,gzip
import numpy as np
from turn_probe import E,source
from assessment import ci

def score(r,hp):
    if r["status"]=="death":return -50
    assert r["status"]=="predicted_win"
    return 100-hp+r["terminal"]["hp"]

def read_cases(tag):
    return [r for f in sorted(E.glob("turn-worlds-"+tag+"-*.gz")) for r in json.load(gzip.open(f))["rows"]]

def main():
    summary={}
    for tag in ("loss","rescue"):
        d=source(tag);rows=read_cases(tag);hp=d["spec"]["hp"]
        main={r["world"]:r for r in rows if r["name"]=="deployed" and r["world"] is not None}
        assert len(main)==48
        arms={}
        for name in sorted({r["name"] for r in rows}):
            pairs=[r for r in rows if r["name"]==name and r["world"] is not None]
            assert len(pairs)==len({r["world"] for r in pairs})==48
            original=next(r for r in rows if r["name"]==name and r["world"] is None)
            w=lambda r:r["status"]=="predicted_win"
            arms[name]=dict(original=dict(hp=original["terminal"]["hp"],status=original["status"],
                turn=original["terminal"]["turn"],C_value=original["actual_v"],actions=[a["action"] for a in original["actions"]]),
                wins=sum(map(w,pairs)),utility=float(np.mean([score(r,hp) for r in pairs])),
                win_loss=[sum(w(r) and not w(main[r["world"]]) for r in pairs),
                          sum(not w(r) and w(main[r["world"]]) for r in pairs)],
                delta_vs_deployed=ci([score(r,hp)-score(main[r["world"]],hp) for r in pairs]))
        summary[tag]=arms
    (E/"turn-summary.json").write_text(json.dumps(summary,indent=2))
if __name__=="__main__":main()
