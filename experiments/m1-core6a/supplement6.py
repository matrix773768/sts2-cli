"""Run the frozen direct clone control after the main workers finish."""
from concurrent.futures import ThreadPoolExecutor
import time
from campaign6 import E, read, launch
def main():
    while not (E/"clone-selection.json").exists():time.sleep(3)
    launch(("dev","clone",0))
    while not (E/"selection.json").exists():time.sleep(5)
    arms=read(E/"selection.json")["arms"]
    while not all((E/f"confirm-{arm}-9.json").exists() for arm in arms):time.sleep(5)
    with ThreadPoolExecutor(4) as workers:list(workers.map(launch,[("confirm","clone",i) for i in range(10)]))
if __name__=="__main__":main()
