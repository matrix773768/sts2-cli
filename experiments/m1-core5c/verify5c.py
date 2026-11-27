"""Re-run every measured battle that used the unordered shortcut after bounded enumeration hardening."""
import gzip,json
from time import perf_counter
from panel5c import OUT,E
from complete import setup
from deploy5b import Lane,fight
def run():
    start=perf_counter()
    panel=json.load(gzip.open(E/"protocol.gz"))
    checks=[]
    for group,arm in (("fresh","V1complete"),("fresh","V2complete"),("regression","V2complete")):
        out=OUT/("verify-"+group+"-"+arm)
        out.mkdir(parents=True,exist_ok=True)
        host,g2,net,plan=setup(out,arm)
        lane=Lane(host,0)
        for path in sorted(E.glob(f"{group}-{arm}-*.gz")):
            for row in map(json.loads,gzip.open(path)):
                if not any(q["grouped"] for q in row["queries"]):
                    continue
                s=panel[group][row["i"]]["spec"]
                r=fight(lane,g2,s,arm,net,planner=plan)
                lane.reset()
                assert r["terminal"]==row["terminal"] and r["actions"]==row["actions"]
                assert len(r["queries"])==len(row["queries"])
                for q,old in zip(r["queries"],row["queries"]):
                    for key in ("turn","used","result","calls","grouped","candidate_mass","reference_mass"):
                        assert q.get(key)==old.get(key),(row["i"],key)
                    for key in ("value","reference"):
                        assert abs(q[key]-old[key])<0.0001
                checks.append(dict(group=group,arm=arm,i=row["i"],verified=len(r["queries"])))
        lane.close()
        host.close()
    (E/"verification.json").write_text(json.dumps(dict(rows=checks,seconds=perf_counter()-start),indent=2))
if __name__=="__main__":
    run()
