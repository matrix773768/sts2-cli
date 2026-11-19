"""Stage the N2A.1 worker with a higher optional bounded action cap."""
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
base = runpy.run_path(str(HERE.parent / "m1-n2a1/build.py"))
s3a = base["s3a"]


if __name__ == "__main__":
    i1 = s3a.b1b.b1a.i1
    # EpisodeStep already uses the requested cap. Host accepts caps up to 2048.
    i1.build(i1.ROOT / "logs/m1-n2a2-build", base["stage"])
