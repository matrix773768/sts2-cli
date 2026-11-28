"""Freeze the independent comparison once, then run fixed jobs in balanced arm order."""
import gzip,json,random,sys,subprocess,time
from concurrent.futures import ThreadPoolExecutor
from branch import Actor,H,E,W
from common6 import read,save,sha
from results6 import paired

def lock():
    dev={a:read(E/f"dev-{a}-0.json") for a in ("v2","low","expand","target","general")}
    delta=paired(dev["general"]["rows"],dev["target"]["rows"])["utility"]["mean"]
    reg=json.load(gzip.open(E/"regression.gz"))
    for arm in ("target","general"):
        b=reg["roots"]["B2"]["arms"][arm]
        o=b["options"][b["best"]]
        assert o["q"]["index"]==7 and o["q"]["style"]=="branch-target" and o["q"]["coverage"]==1
        assert all(all(e[1]!="BOWLBUG_NECTAR" for e in l["alive"]) for l in o["successors"])
    challenger="general" if delta>0 else "target"
    cost={a:r["process_seconds"]/len(r["rows"]) for a,r in dev.items()}
    matched=min(("v2","low","expand"),key=lambda a:abs(cost[a]-cost[challenger]))
    arms=list(dict.fromkeys(["v2","low",challenger,matched]))
    entries=json.load(gzip.open(E/"confirm.gz"))
    assert len(entries)==384 and len({r["family"] for r in entries})==192
    jobs=[]
    for i in range(6):
        order=arms.copy()
        random.Random(62101+i).shuffle(order)
        jobs.extend([a,i] for a in order)
    trial=dict(challenger=challenger,matched=matched,arms=arms,jobs=jobs,dev_cost=cost,dev_general_minus_target=delta,
        projected_worker_seconds=sum(cost[a]*len(entries) for a in arms),
        panel_sha=sha(E/"confirm.gz"),protocol_sha=sha(H/"protocol.md"),
        policies={a:Actor(a).identity("tactical",32)["id"] for a in arms})
    save(E/"selection.json",trial)
    return trial

def execute(job):
    arm,index=job
    receipt=E/f"confirm-{arm}-{index}.json"
    if receipt.exists():return
    name=f"confirm-{arm}-{index}"
    with (W/(name+".log")).open("xb") as log:
        subprocess.run([sys.executable,"-B",str(H/"battle.py"),"confirm",arm,str(index)],
                       stdout=log,stderr=subprocess.STDOUT,check=True,timeout=245)
    print(name,flush=True)

if __name__=="__main__":
    frozen=read(E/"selection.json") if (E/"selection.json").exists() else lock()
    assert frozen["panel_sha"]==sha(E/"confirm.gz") and frozen["protocol_sha"]==sha(H/"protocol.md")
    assert len(frozen["jobs"])*245+900<7200
    tick=time.perf_counter()
    with ThreadPoolExecutor(3) as pool:list(pool.map(execute,frozen["jobs"]))
    save(E/"schedule.json",dict(workers=3,wall_seconds=time.perf_counter()-tick,jobs=frozen["jobs"]))
