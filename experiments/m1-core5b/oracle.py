from panel import *
sys.path.insert(0,str(HERE.parent/"m1-dc3a"))
import reference as dc
from time import perf_counter
def run():
    out=LOGS/"5b-oracle";out.mkdir(exist_ok=False)
    host=dc.Host(out,dc.BUILD,dc.config()|{"workers":1})
    start=perf_counter()
    with gzip.open(E/"oracle.gz","xt") as f:
        for w in json.load(gzip.open(E/"panel.gz","rt"))["oracle"]:
            row=dc.solve(host,w,((128,5),(512,12),(2048,30)))
            f.write(json.dumps(row,separators=(",",":"))+"\n");f.flush()
    (E/"oracle-cost.json").write_text(json.dumps(perf_counter()-start))
if __name__=="__main__":run()
