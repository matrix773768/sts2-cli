"""Reproduce into a fresh directory using the pinned local game/solver assets from CORE-5B."""
import os,sys,subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
HERE=Path(__file__).resolve().parent
def reproduce(directory):
    dest=Path(directory).resolve()
    dest.mkdir(parents=True,exist_ok=False)
    host=dest/"host"
    env=os.environ|{"STS2_CORE5C_RUN":str(dest),"STS2_CORE5C_HOST":str(host)}
    def call(args):
        subprocess.run([sys.executable,str(HERE/args[0]),*args[1:]],cwd=HERE.parents[1],env=env,check=True)
    def batch(jobs):
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(call,jobs))
    call(["panel5c.py"])
    call(["host5c.py",str(host)])
    batch([["run5c.py","fresh",arm] for arm in ("base","medium","high","referenceOnly")])
    batch([["run5c.py","fresh",arm,str(i),"2"] for arm in ("V2complete","V1complete") for i in range(2)])
    batch([["run5c.py","regression","V2complete","0","1"],["run5c.py","regression","referenceOnly"],["placement5c.py"]])
    for arm in ("high","V2complete"):
        call(["run5c.py","cost",arm])
    batch([[script,tag] for script in ("witness5c.py","native5c.py") for tag in ("rescue","loss")])
    batch([["stress5c.py","ordered","4096"],["stress5c.py","ordered","32"],["stress5c.py","multiset","4096"]])
    for script in ("mechanisms5c","verify5c","summary5c","regression5c","ledger5c"):
        call([script+".py"])
if __name__=="__main__":
    reproduce(sys.argv[1])
