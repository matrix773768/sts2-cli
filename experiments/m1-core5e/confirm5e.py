"""Freeze selection before starting the trained confirmation arms."""
import json,subprocess,sys
from concurrent.futures import ThreadPoolExecutor
from panel5e import E,HERE,ROOT
from select5e import run as select
def run():
    select()
    name=json.loads((E/"selection.json").read_bytes())["challenger"]
    jobs=[("confirm",name,0,2),("confirm",name,1,2),("selection","anchor-"+name,0,1)]
    def call(job):
        subprocess.run([sys.executable,str(HERE/"battle5e.py"),*map(str,job)],cwd=ROOT,check=True)
    with ThreadPoolExecutor(max_workers=3) as workers:list(workers.map(call,jobs))
if __name__=="__main__":run()
