"""Isolated diagnosis of the 5C pending-choice twin replay after a deterministic draw."""
from pathlib import Path
import json,sys
from panel5d import HERE
sys.path.insert(0,str(HERE.parent/"m1-core5c"))
import host5c
def extend(solver,sim,host):
    host5c.extend(solver,sim,host)
    host5c.build.replace(sim/"PublicDraw.cs","{ModelEnemy=previous.ModelEnemy};",
        "{ModelEnemy=previous.ModelEnemy,Complete=previous.Complete,ReferenceEvents=previous.ReferenceEvents};")
if __name__=="__main__":
    out=Path(sys.argv[1]).resolve()
    host5c.build.extension=extend
    host5c.build.build(out)
    (out/"build.json").write_text(json.dumps(host5c.build_state.manifest(out),indent=2))
