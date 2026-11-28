"""Index complete public observations by their immutable release locator; retain every rejection."""
from collections import Counter
from time import perf_counter
from common import *
from engine.HotSearch.experience import read_rows

def main():
    tick=perf_counter()
    split=read(E/"split.json")
    dev=set(split["dev"])
    partitions={f:"train" for f in split["train"]}|{f:"dev" for f in dev}
    panel=read(E/"panel.json")
    assert len(set(partitions))==1041 and len({r["family"] for r in panel})==96
    excluded={r["family"] for r in panel}
    for p in ("cohort.json.gz","capacity-cohort.json.gz"):
        h=load(H5/p)
        assert excluded.isdisjoint(r["family"] for k in ("train","open") for r in h[k])
    for path,groups in [("m1-core5e/evidence/panel.gz",["confirm"]),("m1-core5d/evidence/panel.gz",["confirm"]),
                        ("m1-core5b/evidence/panel.gz",["fresh"]),("m1-core5c/evidence/protocol.gz",["fresh"])]:
        hist=load(HERE.parent/path)
        assert (set(partitions)|excluded).isdisjoint(composition(r["spec"]) for k in groups for r in hist[k])
    donors={r["id"]:r for r in read(ROOT/"logs/m1-dc1-formal/roots/families.json")}
    fields={}
    index=[]
    failed=[]
    for edition in ("data","capacity"):
        d=H5/edition
        m=read(d/"manifest.json")
        for s in m["shards"]:
            if s["split"]!="train":continue
            for r,v in zip(read_rows(d/s["file"]),read_rows(d/"public"/(s["shard"]+".gz")),strict=True):
                assert r["task_id"]==v["task_id"]
                if not r["eligible"]:
                    t=r["trajectory"]
                    failed.append(dict(edition=edition,task=r["task_id"],family=r["family"],kind=r["kind"],
                                       reason=t.get("reason",t.get("admission_error",t["status"]))))
                    continue
                part=partitions[r["family"]]
                index.append(dict(edition=edition,shard=s["shard"],task=r["task_id"],family=r["family"],kind=r["kind"],
                                  partition=part,segments=len(v["segments"]),steps=sum(len(x["steps"]) for x in v["segments"])))
                if r["kind"]=="natural":
                    s0=r["spec"]
                    vals=fields.setdefault(part,dict(acts=Counter(),sources=Counter(),encounters=Counter(),rows=0,C=0,
                                                    negative_net_C=0,changed_max=0,layered_C=0,late_C=0))
                    t=r["trajectory"]
                    cs=t["states"]
                    vals["rows"]+=1
                    vals["C"]+=len(cs)
                    vals["acts"][s0["act"]]+=1
                    vals["sources"][donors[r["donor"]]["source"]]+=1
                    vals["encounters"][s0["encounter"]]+=1
                    vals["changed_max"]+=sum(c["max_hp"]!=s0["max_hp"] for c in cs)
                    vals["negative_net_C"]+=sum(t["status"]=="Victory" and c["hp"]<t["terminal"]["hp"] for c in cs)
                    vals["late_C"]+=sum(c["turn"]>=6 for c in cs)
                    vals["layered_C"]+=sum(any(layer for z in c["card_state"].values() for item in z for layer in item["cost_layers"].values()) for c in cs)
    save(E/"admission.json",dict(fields=fields,rejections=failed,public_index=index,seconds=perf_counter()-tick))
if __name__=="__main__":main()
