"""Continue the tuned MC curves with validation patience and explicit compute limits."""
import pickle,sys,time
from settings import *
import importlib.util
spec=importlib.util.spec_from_file_location("learn5g",G/"learn.py")
training=importlib.util.module_from_spec(spec)
spec.loader.exec_module(training)
evaluate,score,shuffled=training.evaluate,training.score,training.shuffled

def main(seed):
    tick=time.perf_counter()
    torch.set_num_threads(1)
    with (WORK/"corpus.pkl").open("rb") as f:t,d,_=pickle.load(f)
    order=read(A/"splits.json")["primary_train"]
    old=set(read(G.parent/"m1-core5f/evidence/split.json")["dev"])
    mask=torch.tensor([f in old for f in d.family])
    for size in (945,2048,4096):
        name=f"long-{size}"
        if (OUT/f"{name}-{seed}.json").exists():continue
        start=time.perf_counter()
        parent=f"tuned-{size}-{seed}"
        r=read(OUT/(parent+".json"))
        pick=next(x for x in r["curve"] if x["step"]==r["best_step"])
        net=base_net()
        net.load_state_dict(torch.load(OUT/(parent+".pt"),weights_only=True))
        fam=set(order[:size])
        ids=torch.tensor([i for i,k in enumerate(t.family) if k in fam])
        stream=shuffled(ids,torch.Generator().manual_seed(seed+31),96,True)
        probe=ids[torch.linspace(0,len(ids)-1,512).long()]
        opt=torch.optim.AdamW(net.parameters(),lr=8e-5,weight_decay=.01)
        curve=[pick]
        best=pick
        dest=OUT/f"{name}-{seed}.pt"
        torch.save(net.state_dict(),dest)
        best_nll=pick["natural"]["all"]["nll"]
        stale=0
        for j in range(1,9601):
            ix=next(stream)
            lp=logits(net,t,[t.keys[i] for i in ix]).log_softmax(-1)
            loss=-(lp*t.mc[ix]).sum(1).mean()
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(),2)
            opt.step()
            if j%800==0:
                m=evaluate(net,d,mask)
                with torch.no_grad():
                    pp=torch.cat([logits(net,t,[t.keys[i] for i in z]).log_softmax(-1) for z in probe.split(64)])
                    train_nll=float(-(pp*t.mc[probe]).sum(1).mean())
                row=m|dict(step=pick["step"]+j,presentations=pick["presentations"]+96*j,
                           passes=(pick["presentations"]+96*j)/len(ids),score=score(m),train_probe_nll=train_nll)
                curve.append(row)
                if row["score"]<best["score"]:
                    best=row
                    torch.save(net.state_dict(),dest)
                if m["natural"]["all"]["nll"]<best_nll-.002:
                    best_nll=m["natural"]["all"]["nll"]
                    stale=0
                else:stale+=1
                if stale>=3:break
        save(OUT/f"{name}-{seed}.json",dict(name=name,seed=seed,C=len(ids),batch=96,parent=parent,
             parent_step=pick["step"],steps=curve[-1]["step"],reason="patience" if stale>=3 else "cap",curve=curve,best_step=best["step"],
             score=best["score"],seconds=time.perf_counter()-start,sha256=sha(dest)))
        print(name,seed,curve[-1]["step"],flush=True)
    save(OUT/f"long-worker-{seed}.json",dict(seconds=time.perf_counter()-tick))
if __name__=="__main__":main(int(sys.argv[1]))
