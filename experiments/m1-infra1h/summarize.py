"""Print descriptive full-panel times and attributed work from verified receipts."""
from collections import Counter
import json
from pathlib import Path
from statistics import median
from campaign import E

PANELS=("natural","pairs","initial-train","initial-dev","audit")
def main():
    runs=json.loads((E/"runs.json").read_bytes())
    baselines={r["kind"]:r for r in runs if not r["smoke"] and r["variant"]=="original" and r["mode"]=="baseline"}
    for r in runs:
        if r["smoke"]:continue
        k=r["kind"]
        if k not in baselines:continue
        cpu=r["python_cpu"]+r["host_cpu"]
        print(r["label"],round(r["wall"],2),round(r["worker"],2),round(cpu,2),
              round(baselines[k]["wall"]/r["wall"],3),r["totals"]["valid"],round(r["rates"]["valid"],4),r["matches"])
        if r["timers"] or r["stages"]:
            s=r["stages"]
            print("  RPC",sum(v for k,v in s.items() if k.startswith("rpc/") and k.endswith("/n")),
                "sent/received MiB",*[round(sum(v for k,v in s.items() if k.startswith(t))/2**20,2) for t in ("bytes_sent/","bytes_received/")],
                "host_seconds",{k:round(v,3) for k,v in r["timers"].items()})
        if r["counts"]:
            print("  physical",r["counts"],"public guards",r["reasons"],"model",r.get("models"))
        if r["private"]:
            print("  private",dict(Counter((x["stage"],str(x["detail"]).split("/")[0]) for x in r["private"])))
        roots=r["by_root_s"]
        times=sorted(roots.values())
        print("  root p50/p95/max seconds",round(median(times),2),round(times[(95*len(times)+99)//100-1],2),
            max(roots,key=roots.get),round(max(times),2),"root 123",round(roots.get("123",0),2))
if __name__=="__main__":main()
