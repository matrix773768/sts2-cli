"""Re-fit archived samples and check the deployed tensor dictionary and frozen baselines."""
import hashlib,json
from time import perf_counter
from panel5d import E,OUT,FIVE,HERE
from fit5d import fit,torch
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def verify():
    start=perf_counter();folder=OUT/"refit";folder.mkdir(exist_ok=True,parents=True)
    fit(folder,folder/"fit.json")
    selected=json.loads((E/"selection.json").read_bytes())["winner"]
    path=folder/f"epoch{selected}.pt"
    tensors=torch.load(E/"v3.pt",weights_only=True)
    replay=torch.load(path,weights_only=True)
    assert tensors.keys()==replay.keys() and all(torch.equal(tensors[k],replay[k]) for k in tensors)
    arch=HERE.parent/"m1-core4"
    report=dict(v3=sha(E/"v3.pt"),refit=sha(path),weights_equal=True,parameters=sum(x.numel() for x in tensors.values()),
        v2=sha(FIVE/"evidence/v2.pt"),v1=sha(arch/"evidence/v1.pt"),encoder=sha(arch/"semantic.py"),
        seconds=perf_counter()-start)
    (E/"verification.json").write_text(json.dumps(report,indent=2))
if __name__=="__main__":verify()
