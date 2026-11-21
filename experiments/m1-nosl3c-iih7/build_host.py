from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
HOST = "m1-nosl3c-iih7-host"

if __name__ == "__main__":
    reward = runpy.run_path(str(HERE.parent / "m1-nosl3c-iih/build_reward_host.py"))
    base = reward["COMPLETION"]["IIG"]["BASE"]["BASE"]["BASE"]["BASE"]["BINDING"].b1b.b1a.i1
    output = base.ROOT / "logs" / HOST
    output.mkdir(parents=True)
    base.build(output, reward["stage"])
