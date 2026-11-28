"""Certify the first closed historical chance program that deviates on a strict submass."""
import sys,time
from branch import Actor,H,E,W,s,portfolio,return_law,differences
sys.path.insert(0,str(H.parent/"m1-core6b1"))
import diagnose as old
from panel import gz,save

def main():
    t=time.perf_counter()
    roots=gz(E/"regression.gz")["roots"];pre=gz(H.parent/"m1-core6b1/evidence/prefixes.gz")
    actor=Actor("general");host=s.SearchClient(W/"conditional-check",False)
    checked=[]
    try:
        for key in sorted(roots):
            options=roots[key]["arms"]["general"]["options"]
            if not any(o["q"]["style"].startswith("branch-") and o["q"]["value"] is not None and o["q"]["chances"] for o in options):continue
            root=pre[key];turn=root["root"]["facts"]["turn"]
            st,hist=old.w.recover(old.w.Recorder(host),actor,dict(spec=root["spec"],prefix=root,turn=turn),dict(prefix=old.w.blank()))
            op={k:root["spec"][k] for k in ("hp","max_hp")};h=old.public_b(st["facts"])
            rank=actor.rank(h,hist,op);groups=portfolio(host,actor,rank,op,"tactical",32)
            ref=host.reference(rank[0],32,actor,h,hist,op)
            for g,q in groups:
                if not q["style"].startswith("branch-") or q["value"] is None or not q["chances"]:continue
                diff={tuple(e) for e in differences(g,ref)}
                changed={0:False}
                for edge in g["policy"]:
                    changed[edge["node"]]=changed[edge["parent"]] or (edge["parent"],edge["view"],edge["index"]) in diff
                leaves=[dict(cursor=l["cursor"],kind=l["kind"],mass=l["mass"],deviated=changed[l["cursor"]]) for l in g["leaves"]]
                mass=sum(l["mass"] for l in leaves if l["deviated"])
                checked.append(dict(root=key,at_menu=q["at_menu"],mass=mass))
                solo=actor.backup([g],op)[0]["value"]
                assert abs(solo-q["value"])<.002 and abs(sum(l["mass"] for l in leaves)-1)<1e-7
                if 1e-9<mass<1-1e-9:
                    save(E/"conditional-check.gz",dict(root=key,option=q,solo=solo,reference=ref["policy"],program=g["policy"],
                         leaves=leaves,law=return_law(g),checked=checked,seconds=time.perf_counter()-t))
                    return
    finally:host.close()
    save(E/"conditional-check.gz",dict(root=None,checked=checked,seconds=time.perf_counter()-t))
if __name__=="__main__":main()
