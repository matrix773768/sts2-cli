"""Repeat the four known failing strict trajectories at their original policy and budget."""
from pathlib import Path
import sys,json,gzip
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/"engine/HotSearch"))
from hot_produce import run
def main(out):
    out.mkdir(parents=True,exist_ok=False)
    opened=json.loads((ROOT/"experiments/m1-infra1h4/evidence/open-specs.json").read_bytes())
    specs=out/"specs.json"
    specs.write_text(json.dumps([opened[i] for i in (11,27)]))
    run(out/"open",[],"contingent",32,specs)
    run(out/"budget",[236,166],"contingent",512)
if __name__=="__main__":main(Path(sys.argv[1]))
