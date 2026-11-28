"""Join published public menus to checked behavior, without observing the suffix during encoding."""
import sys
import time
from collections import Counter
import numpy as np
from common6 import *
from policy6 import encode
sys.path.insert(0,str(A))
from engine.HotSearch import experience as published
sys.modules["experience"]=published
from verify2a_common import check_segment

GROUPS = ["forced","search_first","reference_first","open_first","search_follow","reference_follow","fallback","choice_search","choice_reference","choice_fallback"]
def signed(path):
    obj=read(path)
    assert digest({k:v for k,v in obj.items() if k!="id"})==obj["id"]
    return obj

def main():
    tick=time.perf_counter()
    rel=signed(A/"release.json")
    old=signed(H5/"release.json")
    assert rel["id"]=="dc7985a66a7cc0de2ac2a85f5dfa95cd804dc061286e366a7211bb1db43d4bb2"
    assert sha(A/"splits.json")==rel["artifacts"]["splits.json"]
    split=read(A/"splits.json")
    membership={f:"train" for f in split["primary_train"]}
    membership.update({f:"dev" for f in [*split["core5f"]["dev"],*split["new_dev_eligible"]]})
    assert len(membership)==4371
    sources=[(H5/v["path"],v) for v in old["editions"]]
    sources += [(A/k,v) for k,v in rel["editions"].items() if k in ("train","dev") or k.startswith("reserve-")]
    actor=Models()
    seen=set()
    summary={}
    for part in ("train","dev"):
        chunks=[]; metadata=[]; families=[]; counts=Counter(); hist=Counter()
        for base,edition in sources:
            manifest=signed(base/"manifest.json")
            public=signed(base/"public/index.json")
            assert manifest["id"]==edition["manifest"]==public["dataset"]
            for shard in manifest["shards"]:
                if shard["kind"]!="natural" or shard["split"]=="open":continue
                if base==A/"dev" and part=="train" or base==A/"train" and part=="dev":continue
                path=base/shard["file"]; views=base/"public"/(shard["shard"]+".gz")
                assert sha(path)==shard["sha256"] and sha(views)==public["files"][shard["shard"]]
                for r,obs in zip(read_rows(path),read_rows(views),strict=True):
                    assert r["task_id"]==obs["task_id"]
                    family=r["family"]
                    if not r["eligible"] or membership.get(family)!=part:continue
                    assert family not in seen and r["policy_id"]==POLICY and r["behavior_id"]==BEHAVIOR
                    seen.add(family); fam=len(families);families.append(family)
                    b=r["trajectory"]; seg,=obs["segments"]; check_segment(seg,b)
                    hist[b["status"]]+=1
                    queries={q["turn"]:q for q in b["queries"]}
                    started=set(); memory=actor.g2.encoder.initial_history(); opening=r["spec"]
                    battle=[]
                    for step in seg["steps"]:
                        state=step["observation"]; f=state["facts"]; i=step["index"]; turn=f["turn"]
                        choice=state["status"]=="choice"
                        h=choice_b(f,state) if choice else public_b(f)
                        q=queries.get(turn)
                        first=bool(q and not choice and len(h["actions"])>1 and turn not in started)
                        teacher=None; gap=0.; ref=-1
                        if first:
                            started.add(turn)
                            ref=q["reference"]; rv=q["reference_law"]["value"]
                            assert q["selected"]==i
                            mode="open_first" if rv is None else "search_first" if q["committed"] else "reference_first"
                            if rv is not None:
                                teacher=np.full(len(h["actions"]),np.nan,np.float32)
                                teacher[ref]=rv
                                for v in q["options"]:
                                    if v["value"] is not None:
                                        j=v["index"]; teacher[j]=np.fmax(teacher[j],v["value"])
                                assert abs(teacher[i]-np.nanmax(teacher))<.002
                                gap=float(teacher[i]-rv)
                                counts["closed_options"]+=sum(v["value"] is not None for v in q["options"])
                                counts["options_closed_reference"]+=len(q["options"])
                        else:
                            source=("search" if q["committed"] else "reference") if q and "policy" in q and turn in started else "fallback"
                            mode=("choice_"+source if choice else source+"_follow" if source!="fallback" else "fallback")
                        if len(h["actions"])==1:mode="forced"
                        counts[mode]+=1
                        if len(h["actions"])>1:
                            x,cards=encode(h,memory,opening)
                            ys=teacher if teacher is not None else np.full(len(cards),np.nan,np.float32)
                            battle.append((x,cards,ys));metadata.append((len(cards),i,GROUPS.index(mode),fam,ref,gap))
                        memory=actor.advance(memory,h,h["actions"][i])
                    assert started==set(queries)
                    if battle:chunks.append(tuple(np.concatenate(col) for col in zip(*battle)))
        arrays=[np.concatenate(col) for col in zip(*chunks)]
        np.savez(WORK/(part+".npz"),x=arrays[0],cards=arrays[1],values=arrays[2],meta=np.asarray(metadata),families=np.asarray(families))
        summary[part]=dict(families=len(families),terminal=hist,counts=counts,decisions=len(metadata),actions=len(arrays[0]),width=arrays[0].shape[1])
    assert seen==set(membership)
    save(E/"source.json",dict(releases=[old["id"],rel["id"]],partitions=summary,groups=GROUPS,seconds=time.perf_counter()-tick))
if __name__=="__main__":main()
