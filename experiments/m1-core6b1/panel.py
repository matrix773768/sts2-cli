"""Freeze open diagnostic roots using only current public menus and prefixes."""
import gzip, hashlib, json, time
from pathlib import Path

H=Path(__file__).resolve().parent
E=H/"evidence"
CORE=H.parents[1]
S=H.parent/"m1-core6a/evidence"
W=CORE/"logs/core6b1"
def read(p):return json.loads(p.read_bytes())
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def gz(p):return json.load(gzip.open(p))
def save(p,obj):
    with gzip.open(p,"wt",encoding="utf8") if p.suffix==".gz" else p.open("w",encoding="utf8") as f:
        json.dump(obj,f,ensure_ascii=False,separators=(",",":"),allow_nan=False)

def main():
    start=time.perf_counter()
    W.mkdir(parents=True,exist_ok=True)
    donors={r["id"]:r for r in read(CORE/"logs/m1-dc1-formal/roots/families.json")}
    source=sorted(gz(H.parent/"m1-core5d/evidence/panel.gz")["train"],key=lambda r:digest(["6a-donor",r["family"]]))
    assert sha(CORE/"lib/sts2.dll")=="62ecbe91093e1fa862de4329aac865209dcb297804caf0f0520d92d8c0b4a9c3"
    mp={x["type"].upper() for x in read(E/"native-mp.json") if x.get("il")=="172A" and x["method"]=="get_MultiplayerConstraint"}
    cases={(0,18,8):"A",(0,35,0):"B1",(0,35,4):"B2",(0,35,8):"B3"}
    humans={}; pool=[]; prefixes={}
    for shard in range(4):
        name=f"confirm-low-{shard}"; receipt=read(S/(name+".json"))
        folder=CORE/"logs/core6a"/receipt.get("directory",name)
        assert sha(folder/"public.gz")==receipt["public"]
        if shard==0:assert receipt["public"]=="b89dc969095d0f4434171566c4d9664d6067f3a68c4b67c9603f6c2c1e4ef0d6"
        jobs=read(folder/"jobs.json")
        for i,(job,view) in enumerate(zip(jobs,map(json.loads,gzip.open(folder/"public.gz","rt")),strict=True)):
            assert view["seed"]==job["spec"]["seed"]
            steps=view["segment"]["steps"]; used=set()
            donor=donors[source[((shard*64+i)//2)%len(source)]["family"]]
            for j,x in enumerate(steps):
                o=x["observation"];f=o["facts"];turn=f["turn"]
                if o["status"]!="active" or len(f["actions"])<2 or turn in used:continue
                used.add(turn)
                plays=[f["hand"][a["card"]] for a in f["actions"] if a["kind"]=="PlayCard"]
                types=[]
                if len(f["enemies"])>=2 and any(not e["attack_hits"] or e["powers"] for e in f["enemies"]):types.append("enemy")
                if any(c["vars"].get("Cards",0)>0 or c["vars"].get("Energy",0)>0 for c in plays):types.append("draw")
                if len({a["target"] for a in f["actions"] if a["target"] is not None})>=2 or any(c["id"] in ("BODY_SLAM","PRIMAL_FORCE","BLOOD_WALL") for c in plays):types.append("combo")
                k=digest([job["family"],view["seed"],j,o["view"]])
                row=dict(key=k,family=job["family"],seed=view["seed"],shard=shard,battle=i,index=j,turn=turn,hp=f["hp"],act=job["spec"]["act"],
                         encounter=job["spec"]["encounter"],source=donor["source"],package=donor["package"],mp=[c["id"] for c in job["spec"]["deck"] if c["id"].replace("_","") in mp],
                         behavior=receipt["policy"]["id"],view=o["view"],classes=types,actual=x["index"])
                prefixes[k]=dict(spec=job["spec"],steps=steps[:j],root=o)
                if (shard,i,j) in cases:
                    ident=cases[shard,i,j];humans[ident]=row|dict(id=ident,group="human")
                pool.append(row)
    assert len(humans)==4 and humans["B2"]["seed"]=="488B8A8FE5F35D10" and humans["A"]["seed"]=="3D9019F1288C617C"
    rows=list(humans.values()); taken={r["family"] for r in rows}
    for group,capacity in [("enemy",8),("draw",8),("combo",8),("ordinary",12)]:
        count=0
        for r in sorted(pool,key=lambda x:digest(["6b1",group,x["key"]])):
            if r["family"] in taken or group!="ordinary" and group not in r["classes"]:continue
            rows.append(r|dict(id=f"{group}-{count+1:02}",group=group));taken.add(r["family"]);count+=1
            if count==capacity:break
        assert count==capacity
    save(E/"prefixes.gz",{r["id"]:prefixes[r["key"]] for r in rows})
    save(E/"panel.json",dict(roots=rows,seconds=time.perf_counter()-start,protocol=sha(H/"protocol.md"),prefixes=sha(E/"prefixes.gz")))
if __name__=="__main__":main()
