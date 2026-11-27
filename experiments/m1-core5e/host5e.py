"""Isolated environment-only resampler. The search/suffix kernel stays at frozen 5C."""
from pathlib import Path
import json,sys
here=Path(__file__).resolve().parent
sys.path.insert(0,str(here.parent/"m1-core5c"))
import host5c
from build_turn_review import add_world_sampler
def extend(solver,sim,host):
    host5c.extend(solver,sim,host)
    add_world_sampler(host)
if __name__=="__main__":
    out=Path(sys.argv[1]).resolve()
    host5c.build.extension=extend
    host5c.build.build(out)
    (out/"build.json").write_text(json.dumps(host5c.build_state.manifest(out),indent=2))
