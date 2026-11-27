"""Index actual adjacent C records in frozen 5D data and measure frozen one-step target errors."""
import json,gzip,math
from statistics import mean
from time import perf_counter
from panel5e import D,E,rows
from targets5e import temporal_target,terminal_target
from fit5e import base_net
from semantic import expected,encode,pack,torch
from search5 import cached_row
from assessment import utility

@torch.no_grad()
def run():
    t=perf_counter();torch.set_num_threads(2);net=base_net();summary={}
    with gzip.open(E/"transitions.gz","xt") as out:
        for split in ("train","dev"):
            before=[];after=[];actual=[];overflow=[];nterm=0;discard=0
            for source in (split,split+"2"):
                for file in sorted(D.glob(source+"-V2-*.gz")):
                    for row in rows(file):
                        if not row["terminal"]:discard+=1;continue
                        cs=row["states"];hp=torch.tensor([c["hp"] for c in cs])
                        if not cs:continue
                        p=net(*pack([encode(c,row_fn=cached_row) for c in cs])).softmax(-1)
                        true=utility(row)
                        q,tail=temporal_target(p[1:],hp[:-1],hp[1:]) if len(cs)>1 else (p[:0],p.new_zeros(0))
                        orig=torch.tensor(row["hp"]);mx=torch.tensor(row["max_hp"])
                        before.extend(expected(p[:-1],orig,hp[:-1],mx).tolist())
                        after.extend(expected(q,orig,hp[:-1],mx).tolist())
                        actual.extend([true]*len(q));overflow.extend(tail.tolist())
                        for j,c in enumerate(cs):
                            nxt=cs[j+1] if j+1<len(cs) else None
                            if nxt is None:nterm+=1
                            item=dict(file=file.name,i=row["i"],family=row["family"],seed=row["seed"],c_index=j,
                                turn=c["turn"],next_turn=nxt["turn"] if nxt else None,
                                hp_delta=c["hp"]-(nxt or row["terminal"])["hp"],endpoint="C" if nxt else row["status"])
                            out.write(json.dumps(item,separators=(",",":"))+"\n")
            rmse=lambda vals:math.sqrt(mean((x-y)**2 for x,y in zip(vals,actual)))
            summary[split]=dict(edges=len(after),direct_terminals=nterm,unresolved_battles=discard,mean_overflow=mean(overflow),
                v2_mc_rmse=rmse(before),shifted_v2_mc_rmse=rmse(after),before_bias=mean(x-y for x,y in zip(before,actual)),
                after_bias=mean(x-y for x,y in zip(after,actual)))
    summary["seconds"]=perf_counter()-t
    (E/"transitions.json").write_text(json.dumps(summary,indent=2))
if __name__=="__main__":run()
