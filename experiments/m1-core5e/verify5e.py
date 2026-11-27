"""Refit the two arms from the archived records and verify the exact selected tensors."""
import hashlib,json,subprocess,sys
from time import perf_counter
from panel5e import E,OUT,ROOT
from fit5e import base_net,fit_arm,Corpus,torch
def run():
    t=perf_counter();torch.set_num_threads(2);torch.manual_seed(5705)
    folder=OUT/"refit";folder.mkdir(parents=True,exist_ok=True)
    base=base_net();train=Corpus("train",base);dev=Corpus("dev",base)
    result={}
    for name in ("mc","td"):
        curve=fit_arm(name,base,train,dev,folder);winner=curve["winner"]
        refit=folder/f"{name}-{winner}.pt"
        sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
        result[name]=dict(winner=winner,refit=sha(refit),published=sha(E/(name+".pt")))
        assert result[name]["refit"]==result[name]["published"]
    tests=subprocess.run([sys.executable,"-m","unittest","discover","-s","experiments/m1-core5e"],cwd=ROOT,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    result.update(tests=tests.stdout,status=tests.returncode,seconds=perf_counter()-t)
    (E/"verification.json").write_text(json.dumps(result,indent=2))
    if tests.returncode:raise SystemExit(tests.returncode)
if __name__=="__main__":run()
