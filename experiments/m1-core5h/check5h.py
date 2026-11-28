"""Representation equivalence, masking, cross-token dependence and single-thread inference."""
import pickle,time
from statistics import median
from training_data import *
from semantic import pack

def main():
    tick=time.perf_counter()
    torch.manual_seed(5811)
    torch.set_num_threads(1)
    with (W/"corpus.pkl").open("rb") as f:_,d,_=pickle.load(f)
    samples=[d.states[k][0] for k in d.keys[::7][:96]]
    batches=[pack(samples[:1]),pack(samples[:16]),pack(samples[:64])]
    base=network("pool").eval()
    weights=torch.load(LONG,weights_only=True)
    base.load_state_dict(weights)
    output={}
    for kind in ("pool","local","interact"):
        net=network(kind).eval()
        missing=net.load_state_dict(weights,strict=False).missing_keys
        assert all(k.startswith("transform.") for k in missing)
        g,x,m=batches[1]
        torch.testing.assert_close(net(g,x,m),base(g,x,m),atol=2e-5,rtol=1e-5)
        if kind!="pool":
            last=net.transform.out if kind=="interact" else net.transform.layers[-1]
            torch.nn.init.normal_(last.weight,std=.04)
            vec=torch.randn(1,4,32,requires_grad=True)
            mask=torch.tensor([[True,True,True,False]])
            dy=torch.autograd.grad(net.transform(vec,mask)[0,0].sum(),vec)[0]
            assert bool(dy[0,1].abs().sum()>0)==(kind=="interact") and not dy[0,3].any()
        with torch.inference_mode():
            perm=torch.randperm(x.shape[1])
            torch.testing.assert_close(net(g,x,m),net(g,x[:,perm],m[:,perm]),atol=2e-5,rtol=1e-5)
            xp=torch.cat([x,torch.randn_like(x[:,:3])],1)
            mp=torch.cat([m,torch.zeros_like(m[:,:3])],1)
            torch.testing.assert_close(net(g,x,m),net(g,xp,mp),atol=2e-5,rtol=1e-5)
            latency={}
            for bs,(g1,x1,m1) in zip((1,16,64),batches):
                for _ in range(12):net(g1,x1,m1)
                times=[]
                for _ in range(9):
                    start=time.perf_counter()
                    for j in range(40):net(g1,x1,m1)
                    times.append((time.perf_counter()-start)*1000/40)
                latency[bs]=median(times)
        output[kind]=dict(parameters=sum(v.numel() for v in net.parameters()),batch_ms=latency)
    save(E/"network-checks.json",dict(networks=output,seconds=time.perf_counter()-tick))
if __name__=="__main__":main()
