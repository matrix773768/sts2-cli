from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import sys,subprocess
from paths5b import HERE as B,E
def worker(args):
    group,arm,i,n=args
    if (E/f"{group}-{arm}-{i}.json").exists():return
    subprocess.run([sys.executable,str(B/"deploy5b.py"),group,arm,str(i),str(n)],check=True)
if __name__=="__main__":
    jobs=[]
    for group,arms,n in (("historical",["base","ref768"],4),("fresh",["5A","base","medium","high","V1high"],2),
                         ("high",["G2","G2search","5A","base","high"],2)):
        for arm in arms:
            for i in range(n):jobs.append((group,arm,i,n))
    with ThreadPoolExecutor(4) as pool:list(pool.map(worker,jobs))
