"""Check native terminals for every distinct battle route with a pending choice and no enemies."""
import sys
from pathlib import Path
from time import perf_counter
from cohort import BUILD, CFG, ROOT, Host, digest, plan, read, write
from loop_battle import Lane
from native import check


class Cursor:
    def __init__(self,lane):
        self.lane,self.last,self.position=lane,None,None

    def request(self,cmd,**args):
        result=self.lane.request(cmd,**args)
        if cmd in ("synthetic_start","action"):
            self.last=result.get("decision")
        if cmd in ("pre0_start","i1_n2_step"):
            self.position=result["episode"]["actions"]
        return result


def certify(host,j,row):
    lanes=[Lane(host,i) for i in range(2)]
    left,right=map(Cursor,lanes)
    try:
        for l in lanes:
            l.open()
        return dict(strict=check(left,right,j,row,host.project))
    except (RuntimeError,ValueError,AssertionError) as exc:
        tail=row["steps"][left.position:]
        passive=bool(tail) and all(not s["observation"]["enemies"] and
            s["observation"]["decision"].get("effect")=="MoveToDrawTop" and
            s["action"]["kind"] in ("select_candidate","confirm_selection") for s in tail)
        stamp=right.lane.request("i1_iib_native_stamp")
        f=stamp["state"][0]
        actual=[f[k] for k in ("player_hp","player_max_hp","player_gold","player_potions")]
        t=row["terminal"]
        wanted=[t["hp"],t["max_hp"],t["gold"],",".join(p or "-" for p in t["potions"])]
        verified=bool(stamp["terminal"] and right.last=="card_reward" and passive and
                      row["status"]=="predicted_win" and actual==wanted)
        return dict(position=left.position,decision=right.last,locked=stamp["terminal"],native=actual,
                    predicted=wanted,terminal_verified=verified,suffix=len(tail),detail=str(exc))
    finally:
        for l in lanes:
            l.close()


def audit(out):
    out.mkdir(parents=True,exist_ok=False)
    host=Host(out,BUILD,CFG)
    jobs=plan()
    start=perf_counter()
    report={}
    for directory in sorted((ROOT/"logs").glob("n4-v2-battle-*")):
        for folder in sorted(directory.glob("*-*")):
            for p in sorted(folder.glob("*.gz")):
                r=read(p)["row"]
                if not any(not s["observation"]["enemies"] and s["observation"]["decision"]["phase"]=="choice" for s in r["steps"]):
                    continue
                j=jobs[int(p.name[:3])]
                key=digest([j[0],[s["action"]["index"] for s in r["steps"]]])
                if key not in report:
                    report[key]=dict(id=j[0],arms=[],check=certify(host,j,r))
                report[key]["arms"].append(folder.name)
    host.close()
    write(out/"terminal.json",dict(seconds=perf_counter()-start,routes=report))


if __name__=="__main__":
    audit(Path(sys.argv[1]))
