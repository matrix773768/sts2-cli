"""Bind both diagnostic programs to the identical recorded B2 public root."""
import time
from freeze import E,H,CORE,read,gz,sources,save
from survey import s,Actor,recover

def main():
    start=time.perf_counter()
    host=s.SearchClient(CORE/"logs/core-mcs0/b2-trace",False)
    root=sources()["B2"]
    model=Actor("v2")
    old=gz(H.parent/"m1-core6b2/evidence/regression.gz")["roots"]["B2"]["arms"]["general"]
    best=read(E/"b2.json")["witness"]
    rows={}
    try:
        for name,policy in [("general",old["options"][old["best"]]["policy"]),("single_successor",best["policy"])]:
            st,_=recover(host,model,root)
            node=0
            trace=[]
            while True:
                edge=next(e for e in policy if e["parent"]==node and e["view"]==st["view"])
                f=st["facts"]
                a=f["actions"][edge["index"]]
                trace.append(dict(action=a,card=f["hand"][a["card"]]["id"] if a["kind"]=="PlayCard" else None))
                st=host.call("step",index=edge["index"])
                node=edge["node"]
                if st.get("observed_c") or st["status"] in ("Victory","Defeat"):break
            rows[name]=dict(trace=trace,enemies=st["facts"]["known_enemies"],hp=st["facts"]["hp"])
    finally:host.close()
    save("b2-trace.json",dict(roots=rows,seconds=time.perf_counter()-start))
if __name__=="__main__":main()
